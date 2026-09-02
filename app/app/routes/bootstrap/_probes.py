"""Credential probes behind ``/api/discover/test-credentials``.

One vendor-specific HTTP probe (Reolink) and one vendor-agnostic RTSP
probe, plus the TCP-connect fallback that tells "wrong password" apart
from "camera offline". Kept out of the route module because the two
probes together are the bulk of the discovery surface.
"""

from __future__ import annotations

import contextlib
import logging

from ._helpers import _mask_pw


def _probe_reolink_login(host: str, user: str, password: str, timeout: float = 4.0) -> dict:
    """Distinguish auth-fail from network-fail in a single Reolink Login
    request. Returns one of:
      {"vendor": "reolink", "auth": "ok"}
      {"vendor": "reolink", "auth": "bad"}    — HTTP 200 + ``code != 0``
      {"vendor": "reolink", "auth": "net"}    — connect/HTTP/parse error
    The shipped ``reolink_api.login`` only signals success/None and was
    designed for the day-night override path, where any non-success is
    treated identically.  The discovery probe needs to tell the user
    *why* the login didn't work, so we issue the request directly.
    """
    import requests

    body = [
        {
            "cmd": "Login",
            "action": 0,
            "param": {"User": {"userName": user, "password": password or ""}},
        }
    ]
    try:
        r = requests.post(
            f"http://{host}/api.cgi",
            params={"cmd": "Login"},
            json=body,
            timeout=timeout,
        )
    except Exception as exc:
        logging.info(
            "[discovery] reolink login net-error host=%s user=%s pw=%s: %s",
            host,
            user,
            _mask_pw(password),
            exc,
        )
        return {"vendor": "reolink", "auth": "net"}
    if r.status_code != 200:
        logging.info(
            "[discovery] reolink login HTTP %s host=%s user=%s pw=%s",
            r.status_code,
            host,
            user,
            _mask_pw(password),
        )
        return {"vendor": "reolink", "auth": "net"}
    try:
        payload = r.json()
        first = payload[0] if isinstance(payload, list) and payload else {}
    except Exception as exc:
        logging.info("[discovery] reolink login parse host=%s: %s", host, exc)
        return {"vendor": "reolink", "auth": "net"}
    # Success shape: first.value.Token.name is set.
    token = ((first.get("value") or {}).get("Token") or {}).get("name")
    if token:
        # Best-effort logout — never let it raise.
        try:
            from ...reolink_api import logout as _rl_logout

            _rl_logout(host, token, timeout=2.0)
        except Exception:
            pass
        return {"vendor": "reolink", "auth": "ok"}
    # Reolink returns code != 0 with an error.detail string on bad creds —
    # rspCode -7 / -6 specifically. Any non-success code on a 200 here
    # means the request reached the camera, which means the network is
    # fine — the credentials are the problem.
    if isinstance(first, dict) and "error" in first:
        return {"vendor": "reolink", "auth": "bad"}
    code = first.get("code")
    if isinstance(code, int) and code != 0:
        return {"vendor": "reolink", "auth": "bad"}
    # Unrecognised shape — treat as network so the RTSP fallback runs
    # and either confirms or denies the auth.
    return {"vendor": "reolink", "auth": "net"}


def _probe_rtsp(
    ip: str, port: int, user: str, password: str, path: str, timeout_ms: int = 4000
) -> dict:
    """Vendor-agnostic RTSP probe via OpenCV+FFmpeg. Returns:
      {"vendor": "rtsp", "auth": "ok"}            — frame readable
      {"vendor": "rtsp", "auth": "bad"}           — 401 / Unauthorized
      {"vendor": "rtsp", "auth": "unreachable"}   — no route / refused
      {"vendor": "rtsp", "auth": "timeout"}       — open / read timed out
      {"vendor": "rtsp", "auth": "unknown"}       — opened but no frame
    OpenCV's FFmpeg backend writes the underlying error string to stderr
    only — we capture the timing of cap.isOpened() / read() and treat
    the absence of an opened handle as a generic network failure unless
    the FFmpeg log captured below mentions HTTP 401 / Unauthorized.
    """
    import os
    import urllib.parse

    import cv2  # noqa: PLC0415 — keep import local to keep boot fast

    from ...rtsp_options import capture_options, timeout_params

    enc_pw = urllib.parse.quote(password or "", safe="")
    enc_user = urllib.parse.quote(user or "", safe="")
    safe_path = path or ""
    if safe_path and not safe_path.startswith("/"):
        safe_path = "/" + safe_path
    rtsp_url = f"rtsp://{enc_user}:{enc_pw}@{ip}:{port}{safe_path}"
    masked = f"rtsp://{user}:{_mask_pw(password)}@{ip}:{port}{safe_path}"
    logging.info("[discovery] rtsp probe %s", masked)

    # FFmpeg socket-level timeout via env var, OpenCV's own open/read
    # timeouts via the constructor params vector — cap.set() is a no-op
    # for both on the FFmpeg backend. See app.rtsp_options.
    prev_env = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = capture_options(timeout_ms * 1000)
    cap = None
    try:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, timeout_params(timeout_ms, timeout_ms))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            # No way to ask FFmpeg "why?" via the OpenCV API. Distinguish
            # by trying a quick TCP connect to the port: refused/no-route
            # → unreachable, success → likely auth.
            return {"vendor": "rtsp", "auth": _classify_rtsp_open_fail(ip, port)}
        ok, frame = cap.read()
        if ok and frame is not None and getattr(frame, "size", 0) > 0:
            return {"vendor": "rtsp", "auth": "ok"}
        # Opened but no frame — common when the URL path is wrong on a
        # camera that does authenticate. Surface as ``unknown`` so the
        # UI lets the user save with a warning.
        return {"vendor": "rtsp", "auth": "unknown"}
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        # Restore the prior env var so we don't poison the rest of the
        # process (camera_runtime/_capture sets its own value before
        # opening the production stream, but a test request running
        # while no camera is up could leak otherwise).
        if prev_env is None:
            os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
        else:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = prev_env


def _classify_rtsp_open_fail(ip: str, port: int, timeout: float = 1.5) -> str:
    """Quick fallback classification when ``cap.isOpened()`` is false.
    A successful TCP connect means the port is up — so the most likely
    cause of OpenCV failing to open is an auth failure (401) or a wrong
    path. A refused/timed-out connect means the camera is unreachable.
    """
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        rc = s.connect_ex((ip, port))
        if rc == 0:
            return "bad"  # port reachable but FFmpeg couldn't open → auth
        return "unreachable"
    except Exception:
        return "timeout"
    finally:
        with contextlib.suppress(Exception):
            s.close()
