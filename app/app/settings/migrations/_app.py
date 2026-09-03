"""App-level blocks: telegram push, server location, runtime."""

from __future__ import annotations

import logging

from .._consts import SERVER_LOCATION_DEFAULTS, TELEGRAM_PUSH_DEFAULTS
from ._helpers import _deep_merge_defaults

log = logging.getLogger("app.settings.migrations")


def migrate_telegram_push_defaults(data: dict) -> None:
    """Additively backfill telegram.push so every key the UI expects exists."""
    tg = data.setdefault("telegram", {})
    push = tg.setdefault("push", {})
    if not isinstance(push, dict):
        push = {}
        tg["push"] = push
    # Lift a hand-edited `telegram.recording_ticker` into the documented
    # `telegram.push.recording_ticker` BEFORE the defaults land. The reader
    # in camera_runtime/_recording/_publish looked one level up from where
    # TELEGRAM_PUSH_DEFAULTS puts the key, so the only way an install could
    # carry a value at the old path was by editing settings.json directly —
    # and that value must survive, not be overwritten by the True default.
    # setdefault keeps it additive; the pop removes the now-dead key so the
    # drift cannot be re-read by anything later.
    legacy_ticker = tg.pop("recording_ticker", None)
    if legacy_ticker is not None:
        push.setdefault("recording_ticker", bool(legacy_ticker))
        log.info("[migration] recording_ticker: telegram → telegram.push verschoben")
    _deep_merge_defaults(push, TELEGRAM_PUSH_DEFAULTS)
    # Backfill night-alert lat/lon from server.location when present —
    # avoids forcing the user to re-enter coordinates already known to
    # the system.
    night = push.get("night_alert") or {}
    srv_loc = (data.get("server", {}) or {}).get("location") or {}
    if night.get("lat") is None and srv_loc.get("lat") is not None:
        night["lat"] = srv_loc.get("lat")
    if night.get("lon") is None and srv_loc.get("lon") is not None:
        night["lon"] = srv_loc.get("lon")


def migrate_server_location_defaults(data: dict) -> None:
    srv = data.setdefault("server", {})
    loc = srv.setdefault("location", {})
    if not isinstance(loc, dict):
        loc = {}
        srv["location"] = loc
    for k, v in SERVER_LOCATION_DEFAULTS.items():
        loc.setdefault(k, v)


def migrate_runtime_defaults(data: dict) -> None:
    rt = data.setdefault("runtime", {})
    if not isinstance(rt, dict):
        rt = {}
        data["runtime"] = rt
    rt.setdefault("event_feedback", {})
    rt.setdefault("suppress", {})
    rt.setdefault("system_state", {})
    rt.setdefault("alert_index", {})
    rt.setdefault("last_storage_warn_ts", 0)
    rt.setdefault("last_coral_state", "")
