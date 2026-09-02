"""The one impure step: read live process state, hand back
``arcname -> text``.

Kept apart from :mod:`._sections` (which knows the shapes) and
:mod:`._writer` (which knows the disk) so a test can assemble a bundle
from stubs without a running app, and from ``app_state`` when there is
one.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from . import _summary
from ._consts import (
    ARC_CONFIG,
    ARC_EVENTS,
    ARC_LOG,
    ARC_STATUS,
    ARC_SUMMARY,
    ARC_TELEMETRY,
    ARC_TUNING,
    EVENT_COUNT,
)
from ._sections import (
    _dump,
    _guard,
    log_tail,
    recent_events,
    redact_settings,
    status_snapshot,
    telemetry_snapshot,
    tuning_snapshot,
)

log = logging.getLogger(__name__)


def _cameras(cfg: dict) -> list[dict]:
    """``[{id, name, role}, …]`` for the summary — the effective config's
    camera list, not settings.data, so a disabled camera still shows."""
    from ..thresholds._apply import camera_role

    out = []
    for cam in (cfg or {}).get("cameras") or []:
        cam_id = cam.get("id")
        if not cam_id:
            continue
        out.append({"id": cam_id, "name": cam.get("name") or cam_id, "role": camera_role(cam)})
    return out


def _event_entries(cams: list[dict]) -> dict[str, str]:
    """One file per event under ``events/``, named by event id."""
    from .. import app_state

    store = app_state.store
    if store is None:
        return {}
    events = recent_events(store, [c["id"] for c in cams], EVENT_COUNT)
    out = {}
    for idx, ev in enumerate(events):
        name = str(ev.get("event_id") or f"event-{idx:03d}").replace("/", "_")
        out[f"{ARC_EVENTS}/{name}.json"] = _dump(ev)
    return out


def build_entries(storage_root, now: datetime | None = None) -> dict[str, str]:
    """Every file the archive will carry, in the order they are written."""
    from .. import app_state

    stamp = now or datetime.now()
    cfg = _guard("Konfiguration", app_state.get_effective_config)
    cfg = cfg if isinstance(cfg, dict) else {}
    cams = _cameras(cfg)
    events = _event_entries(cams)
    entries = {
        ARC_SUMMARY: _summary.render(
            now=stamp, build=_build_info(), cameras=cams, events=len(events)
        ),
        ARC_STATUS: _dump(_guard("Status", status_snapshot)),
        ARC_TELEMETRY: _dump(_guard("Telemetrie", telemetry_snapshot)),
        ARC_CONFIG: _dump(redact_settings(cfg)),
        f"{ARC_TUNING}/net.json": _dump(
            _guard("Feinschliff", tuning_snapshot, [c["id"] for c in cams])
        ),
        ARC_LOG: _guard_text("Log", log_tail, Path(storage_root)),
    }
    entries.update(events)
    return entries


def _build_info() -> dict:
    from ..lifecycle import _BUILD_INFO

    return dict(_BUILD_INFO or {})


def _guard_text(name: str, fn, *args) -> str:
    out = _guard(name, fn, *args)
    return out if isinstance(out, str) else _dump(out)
