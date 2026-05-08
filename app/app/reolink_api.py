"""Reolink HTTP CGI helper — minimal subset used by the day/night override
for the sun-timelapse capture window.

Three short sync calls, all 5 s timeouts, all swallow network errors and
log a single WARNING on failure (the caller is the weather scheduler — a
flaky API call must never abort the timelapse capture).

Login flow per Reolink CGI: POST /api.cgi?cmd=Login → token → use token
in subsequent SetIspCfg / Logout calls. Token has a short session
lifetime; callers should not cache it across jobs — login → set → logout
in one short burst (the function signatures encourage exactly that).
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

# Module-level session reused across calls in the same worker thread so
# that overriding many cams in sequence doesn't re-handshake TCP each
# time. requests.Session is documented as thread-safe for separate hosts;
# all our calls hit one cam per worker invocation so we never share a
# Session object across threads at the same host anyway.
_session = requests.Session()


def _base_url(host: str) -> str:
    return f"http://{host}/api.cgi"


def login(host: str, username: str, password: str, timeout: float = 5.0) -> str | None:
    """POST cmd=Login and return the session token, or None on failure."""
    if not host or not username:
        # password may legitimately be empty on factory-default cams;
        # only bail if we have neither host nor user.
        log.warning("[reolink] daynight override needs cam credentials, skipping (host=%r user=%r)",
                    host, username or "")
        return None
    body = [{
        "cmd":    "Login",
        "action": 0,
        "param":  {"User": {"userName": username, "password": password or ""}},
    }]
    try:
        r = _session.post(
            _base_url(host),
            params={"cmd": "Login"},
            json=body,
            timeout=timeout,
        )
    except Exception as e:
        log.warning("[reolink] login network error host=%s: %s", host, e)
        return None
    if r.status_code != 200:
        log.warning("[reolink] login HTTP %s host=%s", r.status_code, host)
        return None
    try:
        payload = r.json()
        first = payload[0] if isinstance(payload, list) and payload else {}
        rsp = (first.get("value") or {}).get("Token") or {}
        token = rsp.get("name")
        if not token:
            log.warning("[reolink] login OK but no token in response host=%s body=%s",
                        host, str(payload)[:200])
            return None
        return token
    except Exception as e:
        log.warning("[reolink] login parse error host=%s: %s body=%s",
                    host, e, r.text[:200])
        return None


# Reolink rspCode mapping. Sourced from the published API doc + the
# firmware-shape variations we've observed in the wild on RLC-810A
# and CX810 cameras. Used to translate the cryptic numeric code into
# a human-readable hint in the WARNING line — important when a user
# is staring at "set_daynight … rspCode=-6" trying to figure out why
# the override silently no-ops.
_REOLINK_RSPCODE_HINTS: dict[int, str] = {
     0: "ok",
    -1: "ungültige Parameter (Firmware erwartet andere Feldnamen?)",
    -6: "kein Admin-Recht — User-Account hat keine ISP-Rechte",
    -7: "Login fehlgeschlagen / Token ungültig",
   -10: "Fähigkeit nicht unterstützt (Firmware kennt SetIspCfg.dayNight nicht)",
}


def set_daynight(host: str, token: str, mode: str,
                 channel: int = 0, timeout: float = 5.0) -> bool:
    """Force the cam's day/night mode. mode ∈ {Color, Black&White, Auto}.

    Returns True iff Reolink reports a success rspCode (0 or 200 —
    different firmware versions report success with either). False on
    any other response, network error or parse failure. Failure paths
    log the full HTTP status, rspCode, and Reolink ``error.detail``
    string so the operator can tell apart "wrong field" / "no admin
    right" / "command not supported by firmware" without rerunning
    against tcpdump.
    """
    if mode not in ("Color", "Black&White", "Auto"):
        log.warning("[reolink] set_daynight invalid mode=%r", mode)
        return False
    if not token:
        log.warning("[reolink] set_daynight host=%s mode=%s: empty token", host, mode)
        return False
    body = [{
        "cmd":    "SetIspCfg",
        "action": 0,
        "param":  {"Isp": {"channel": channel, "dayNight": mode}},
    }]
    try:
        r = _session.post(
            _base_url(host),
            # Mask the token in any debug logging — the token is a
            # short-lived session id, but it grants ISP-write access
            # for ~30 min, so don't leak it into log files. The
            # underlying request still carries the full token; we
            # just keep it out of any string we format ourselves.
            params={"cmd": "SetIspCfg", "token": token},
            json=body,
            timeout=timeout,
        )
    except Exception as e:
        log.warning(
            "[reolink] set_daynight network error host=%s mode=%s ch=%d: %s",
            host, mode, channel, e,
        )
        return False
    status = r.status_code
    body_txt = (r.text or "")
    # Truncate the formatted body in the log line to 600 chars — the
    # full JSON for an error response runs ~120 chars but a future
    # firmware may pad it; 600 is a safe upper bound that still fits
    # one log line.
    body_log = body_txt[:600]
    if status != 200:
        log.warning(
            "[reolink] set_daynight HTTP %d host=%s mode=%s ch=%d body=%s",
            status, host, mode, channel, body_log,
        )
        return False
    try:
        payload = r.json()
    except Exception as e:
        log.warning(
            "[reolink] set_daynight parse error host=%s mode=%s: %s body=%s",
            host, mode, e, body_log,
        )
        return False
    first = payload[0] if isinstance(payload, list) and payload else {}
    # Two response shapes — success carries the rspCode under
    # ``value.rspCode``, error carries it under ``error.rspCode`` plus
    # a human ``error.detail`` string. We read both so a permission
    # rejection doesn't slip through as "unknown failure".
    value = first.get("value") if isinstance(first.get("value"), dict) else None
    err = first.get("error") if isinstance(first.get("error"), dict) else None
    rsp_code = None
    if value is not None and "rspCode" in value:
        rsp_code = value.get("rspCode")
    elif err is not None and "rspCode" in err:
        rsp_code = err.get("rspCode")
    err_detail = (err or {}).get("detail", "") if err else ""
    outer_code = first.get("code")
    # Success conditions:
    #   • value.rspCode == 200 (RLC-810A / older firmware)
    #   • value.rspCode == 0   (CX810 / newer firmware)
    #   • outer code == 0 with no error block (some firmwares omit
    #     value entirely on a no-op success)
    if rsp_code in (0, 200):
        return True
    if outer_code == 0 and err is None:
        return True
    # Failure path — emit a single rich WARNING the operator can
    # diagnose from. Include outer code, rspCode (when present),
    # error.detail, and the truncated raw body as a last-resort
    # forensic anchor.
    hint = ""
    if isinstance(rsp_code, int):
        hint = _REOLINK_RSPCODE_HINTS.get(rsp_code, "")
    log.warning(
        "[reolink] set_daynight host=%s mode=%s ch=%d FAILED · "
        "outer_code=%s rspCode=%s detail=%r%s · body=%s",
        host, mode, channel, outer_code, rsp_code, err_detail,
        f" · hint={hint!r}" if hint else "",
        body_log,
    )
    return False


def get_device_info(host: str, token: str, timeout: float = 5.0) -> dict | None:
    """Query Reolink GetDevInfo CGI — used by the cam-save auto-detect flow
    so the user doesn't have to type "Reolink" / "RLC-810A" by hand and
    the canonical camera-id can be built without "unknown_unknown_…"
    fallbacks. Returns:

      {"manufacturer": "Reolink",
       "model":        "RLC-810A",   # exact GetDevInfo model string
       "firmware":     "v3.0.0.494",
       "hardware":     "IPC_523128M5MP"}

    or None on any failure (no token, network error, non-200 HTTP, error
    rspCode, missing model). Failures are silent at WARNING level so a
    flaky probe never blocks a save.
    """
    if not token:
        return None
    body = [{"cmd": "GetDevInfo", "action": 0, "param": {}}]
    try:
        r = _session.post(
            _base_url(host),
            params={"cmd": "GetDevInfo", "token": token},
            json=body,
            timeout=timeout,
        )
    except Exception as e:
        log.warning("[reolink] get_device_info network error host=%s: %s", host, e)
        return None
    if r.status_code != 200:
        log.warning("[reolink] get_device_info HTTP %s host=%s", r.status_code, host)
        return None
    try:
        payload = r.json()
        first = payload[0] if isinstance(payload, list) and payload else {}
        if first.get("code") != 0:
            log.warning("[reolink] get_device_info host=%s code=%s rsp=%s",
                        host, first.get("code"), str(payload)[:200])
            return None
        dev = (first.get("value") or {}).get("DevInfo") or {}
        model = str(dev.get("model", "") or "").strip()
        if not model:
            return None
        return {
            "manufacturer": "Reolink",
            "model":        model,
            "firmware":     str(dev.get("firmVer", "") or "").strip(),
            "hardware":     str(dev.get("hardVer", "") or "").strip(),
        }
    except Exception as e:
        log.warning("[reolink] get_device_info parse error host=%s: %s body=%s",
                    host, e, r.text[:200])
        return None


def logout(host: str, token: str, timeout: float = 5.0) -> None:
    """Best-effort token release. Errors are swallowed and only logged at
    DEBUG — leaking a token to its 30-min server-side timeout is not a
    real problem."""
    if not token:
        return
    try:
        _session.post(
            _base_url(host),
            params={"cmd": "Logout", "token": token},
            json=[{"cmd": "Logout", "action": 0, "param": {}}],
            timeout=timeout,
        )
    except Exception as e:
        log.debug("[reolink] logout swallowed host=%s: %s", host, e)
