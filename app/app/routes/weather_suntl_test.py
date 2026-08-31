"""Ad-hoc sun-timelapse test capture — start / status / cancel.

Own module for the same reason as ``routes/weather_maintenance.py``:
``routes/weather.py`` was past the 500-line ceiling, and this trio is
a self-contained diagnostic surface. It drives the same capture path
production uses (``weather_service/_sun_tl.py``) so a bug reproduces,
but nothing in the live weather pipeline calls into it.

Pure delegation — every route reads ``app_state.weather_service``
fresh, because ``rebuild_services`` may replace the instance after a
settings save, and hands straight through to the service.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from .. import app_state

bp = Blueprint("weather_suntl_test", __name__)

log = logging.getLogger(__name__)


@bp.post('/api/weather/sun-tl/test')
def api_weather_sun_tl_test_start():
    """Start an ad-hoc sunrise/sunset capture for live diagnostic
    observation. Re-uses the production capture path so the
    bug we're chasing reproduces; surfaces frame counters and the
    daynight-override result via /api/weather/sun-tl/test/status.

    G5 · duration_s + target_duration_s parsing fails LOUD (HTTP 400)
    instead of silently defaulting to 120 / None. The full allowlists
    live in app/app/weather_service/_sun_tl.py and must stay aligned
    with web/static/js/weather/settings-suntltest.js · _DURATIONS /
    _TARGET_LENGTHS; mismatched values bubble up as the start_sun_tl_
    test() error reply, which we surface as 400."""
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"ok": False, "error": "weather service not available"}), 503
    body = request.get_json(silent=True) or {}
    cam_id = (body.get("cam_id") or "").strip()
    phase = (body.get("phase") or "").strip()
    # G5 · explicit 400 instead of the previous silent fallback to
    # 120 s. A type error here means the frontend sent something
    # malformed and the operator needs to see WHY, not get a quiet
    # 120 s coercion that misaligns the math readout.
    raw_duration = body.get("duration_s")
    if raw_duration is None:
        return jsonify({"ok": False, "error": "duration_s required"}), 400
    try:
        duration_s = int(raw_duration)
    except (TypeError, ValueError):
        return jsonify(
            {"ok": False, "error": f"duration_s must be an integer (got {raw_duration!r})"}
        ), 400
    raw_target = body.get("target_duration_s")
    target_duration_s = None
    if raw_target is not None:
        try:
            target_duration_s = int(raw_target)
        except (TypeError, ValueError):
            return jsonify(
                {
                    "ok": False,
                    "error": f"target_duration_s must be an integer or null (got {raw_target!r})",
                }
            ), 400
    if not cam_id or not phase:
        return jsonify({"ok": False, "error": "cam_id and phase required"}), 400
    res = ws.start_sun_tl_test(cam_id, phase, duration_s, target_duration_s=target_duration_s)
    if not res.get("ok"):
        # G5 · "not in allowlist" errors from start_sun_tl_test fall
        # under HTTP 400 (client supplied a value the server doesn't
        # accept). The legacy "test already running" stays at 409 so
        # the frontend's existing toast wording still applies.
        err = res.get("error") or ""
        code = 400 if "allowlist" in err or "must be an integer" in err else 409
        return jsonify(res), code
    return jsonify(res)


@bp.get('/api/weather/sun-tl/test/status')
def api_weather_sun_tl_test_status():
    """Live snapshot of the active (or most recently completed)
    sun-tl test session. Polled by the UI every ~1.5 s while running.

    G2 · ``?since=<epoch_s>`` filters slot_events to entries strictly
    newer than that timestamp so the poller can ship just the delta.
    Default (no since) returns the full slot_events history."""
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"running": False, "session": None})
    try:
        since = float(request.args.get("since") or 0.0)
    except (TypeError, ValueError):
        since = 0.0
    return jsonify(ws.get_sun_tl_test_status(since=since))


@bp.post('/api/weather/sun-tl/test/cancel')
def api_weather_sun_tl_test_cancel():
    """Signal the active sun-tl test capture to stop at the next
    poll boundary (~0.5 s). The capture loop sets ``cancelled=True``
    and skips the encode path; the status endpoint surfaces the
    cancellation so the frontend can render the right end-state."""
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"ok": False, "error": "weather service not available"}), 503
    res = ws.cancel_sun_tl_test()
    if not res.get("ok"):
        return jsonify(res), 409
    return jsonify(res)
