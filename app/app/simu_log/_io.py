"""Paths and atomic JSON round-trips for the SIMU run log.

Best-effort throughout, the same principle ``net_archive._io`` runs on:
the clipboard is the primary path for a debug run, so a failed write here
must cost the operator nothing. Every failure is swallowed and logged
under the ``[storage]`` tag.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ..storage import _atomic_write_text
from ._consts import LOG_DIRNAME, RUN_NAME_RE

log = logging.getLogger(__name__)


def log_root(storage_root) -> Path:
    return Path(storage_root) / LOG_DIRNAME


def camera_dir(storage_root, cam_id: str) -> Path:
    return log_root(storage_root) / cam_id


def run_name(now: datetime | None = None) -> str:
    """``YYYYMMDD-HHMMSS-ffffff.json`` — the event-id shape.

    Microseconds are not decoration: two taps inside the same second are
    entirely normal on a phone, and a name collision would silently
    overwrite the earlier run.
    """
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S-%f") + ".json"


def iter_runs(storage_root, cam_id: str):
    """Every stored run for one camera, NEWEST first.

    Sorted by name, which is the timestamp — no stat() call per file, and
    it stays correct when a copy operation resets the mtimes.
    """
    directory = camera_dir(storage_root, cam_id)
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.glob("*.json") if RUN_NAME_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )


def save_run(storage_root, cam_id: str, payload: dict) -> str | None:
    """Write one run. Returns its file name, or None on failure."""
    name = run_name()
    try:
        path = camera_dir(storage_root, cam_id) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
        return name
    except Exception as e:
        log.warning("[storage] simu_log: Lauf %s/%s nicht geschrieben: %s", cam_id, name, e)
        return None


def read_run(storage_root, cam_id: str, name: str) -> dict | None:
    """One stored run, or None. ``name`` is gated by RUN_NAME_RE before it
    touches the filesystem — camera ids reach paths directly in this
    project and a run name must not become the second way in."""
    if not RUN_NAME_RE.match(name or ""):
        return None
    path = camera_dir(storage_root, cam_id) / name
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("[storage] simu_log: unlesbarer Lauf %s/%s: %s", cam_id, name, e)
        return None
    return payload if isinstance(payload, dict) else None


def list_runs(storage_root, cam_id: str) -> list:
    """``[{name, bytes, stored_at}]`` newest first — enough for a picker
    without reading (and parsing) every file."""
    out = []
    for path in iter_runs(storage_root, cam_id):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        stem = path.stem
        out.append(
            {
                "name": path.name,
                "bytes": size,
                "stored_at": f"{stem[0:4]}-{stem[4:6]}-{stem[6:8]}T"
                f"{stem[9:11]}:{stem[11:13]}:{stem[13:15]}",
            }
        )
    return out


def delete_run(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        log.debug("[storage] simu_log: %s nicht gelöscht: %s", path.name, e)
