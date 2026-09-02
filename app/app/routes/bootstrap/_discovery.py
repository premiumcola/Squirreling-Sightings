"""LAN discovery: the sync scan, the SSE scan, and the credential test."""

from __future__ import annotations

import logging

from flask import Response, jsonify, request

from ... import app_state
from ...discovery import discover_hosts, discover_hosts_stream
from ._blueprint import bp
from ._consts import _DETAIL_DE
from ._helpers import _auto_detect_subnet, _mask_pw
from ._probes import _probe_reolink_login, _probe_rtsp


@bp.get('/api/discover')
def api_discover():
    configured = (
        app_state.get_effective_config().get("server", {}).get("default_discovery_subnet", "")
    )
    subnet = request.args.get('subnet') or configured or _auto_detect_subnet()
    logging.info(f"[discovery] starting scan on subnet={subnet}")
    cameras, total_scanned = discover_hosts(subnet)
    logging.info(
        f"[discovery] scan done — {len(cameras)} cameras found out of {total_scanned} hosts"
    )
    return jsonify({"subnet": subnet, "results": cameras, "total_scanned": total_scanned})


@bp.get('/api/discover/stream')
def api_discover_stream():
    """Server-Sent Events variant of /api/discover. Streams progress
    events while the two-phase scan runs; ends with a `done` event
    that carries the same payload the sync endpoint returns.

    Event types:
      • phase        — {phase, subnet, total_hosts}
      • progress     — {scanned, total, current_ip}     (~5/s)
      • phase1_hit   — {ip, ports}
      • phase2_check — {ip, action}                     ("banner_fetch"|"vendor_guess")
      • candidate    — {ip, hostname, guess, open_ports}
      • done         — {subnet, total_scanned, found, results}
      • error        — {message}
    """
    import json as _json

    configured = (
        app_state.get_effective_config().get("server", {}).get("default_discovery_subnet", "")
    )
    subnet = request.args.get('subnet') or configured or _auto_detect_subnet()
    logging.info(f"[discovery] starting SSE scan on subnet={subnet}")

    def _gen():
        # Initial keep-alive comment so EventSource fires `open` even
        # before the first phase event lands.
        yield ": ready\n\n"
        try:
            for kind, payload in discover_hosts_stream(subnet):
                yield f"event: {kind}\ndata: {_json.dumps(payload)}\n\n"
                if kind == "done":
                    res = payload.get("results", [])
                    logging.info(
                        "[discovery] SSE scan done — %d cameras found out of %d hosts",
                        len(res),
                        payload.get("total_scanned", 0),
                    )
        except GeneratorExit:
            # Client disconnected mid-scan — silent.
            return
        except Exception as exc:
            logging.exception("[discovery] SSE scan failed")
            yield f"event: error\ndata: {_json.dumps({'message': str(exc)})}\n\n"

    return Response(
        _gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx/proxy buffering if any
            "Connection": "keep-alive",
        },
    )


@bp.post('/api/discover/test-credentials')
def api_discover_test_credentials():
    """Probe a candidate camera with the credentials the user just typed
    in the discovery modal. Always returns 200 — never raises — so the
    frontend stays responsive even when a camera is fully offline.

    Hard 6 s wall-clock cap: the Reolink HTTP probe (≤4 s) plus the
    RTSP fallback (≤4 s) only run sequentially in the worst case where
    Reolink is unreachable; ``_probe_reolink_login`` returns ``net``
    quickly enough that the combined budget fits.
    """
    payload = request.get_json(silent=True) or {}
    ip = (payload.get("ip") or "").strip()
    user = (payload.get("user") or "").strip()
    password = payload.get("password") or ""
    path = (payload.get("path") or "").strip()
    try:
        port = int(payload.get("port") or 554)
    except (TypeError, ValueError):
        port = 554
    if not ip:
        return jsonify(
            {
                "ok": False,
                "vendor": "unknown",
                "reason": "error",
                "detail": "Keine IP-Adresse angegeben.",
            }
        )
    if not user:
        # Empty user is sometimes valid for ONVIF anon, but the cam-add
        # form always pre-fills "admin" so an empty user here is a UI
        # bug — surface it instead of probing blindly.
        return jsonify(
            {
                "ok": False,
                "vendor": "unknown",
                "reason": "auth_failed",
                "detail": "Benutzername fehlt.",
            }
        )

    logging.info(
        "[discovery] credential test %s:%d user=%s pw=%s path=%s",
        ip,
        port,
        user,
        _mask_pw(password),
        path or "—",
    )

    # ── Reolink HTTP login first ────────────────────────────────────────
    rl = _probe_reolink_login(ip, user, password, timeout=4.0)
    if rl["auth"] == "ok":
        return jsonify(
            {
                "ok": True,
                "vendor": "reolink",
                "reason": "auth_ok",
                "detail": _DETAIL_DE["auth_ok"],
            }
        )
    if rl["auth"] == "bad":
        return jsonify(
            {
                "ok": False,
                "vendor": "reolink",
                "reason": "auth_failed",
                "detail": _DETAIL_DE["auth_failed"],
            }
        )
    # ``net`` → fall through to the RTSP fallback. Anything non-Reolink
    # always lands here.

    rt = _probe_rtsp(ip, port, user, password, path, timeout_ms=4000)
    if rt["auth"] == "ok":
        return jsonify(
            {
                "ok": True,
                "vendor": "rtsp",
                "reason": "auth_ok",
                "detail": _DETAIL_DE["auth_ok"],
            }
        )
    if rt["auth"] == "bad":
        return jsonify(
            {
                "ok": False,
                "vendor": "rtsp",
                "reason": "auth_failed",
                "detail": _DETAIL_DE["auth_failed"],
            }
        )
    if rt["auth"] == "timeout":
        return jsonify(
            {
                "ok": False,
                "vendor": "rtsp",
                "reason": "timeout",
                "detail": _DETAIL_DE["timeout"],
            }
        )
    if rt["auth"] == "unreachable":
        return jsonify(
            {
                "ok": False,
                "vendor": "rtsp",
                "reason": "unreachable",
                "detail": _DETAIL_DE["unreachable"],
            }
        )
    # ``unknown`` — opened, but no frame. Lets the user save anyway.
    return jsonify(
        {
            "ok": False,
            "vendor": "rtsp",
            "reason": "auth_unknown",
            "detail": _DETAIL_DE["auth_unknown"],
        }
    )
