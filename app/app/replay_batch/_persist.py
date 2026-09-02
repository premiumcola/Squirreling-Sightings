"""Read/write the one persisted batch report.

Every other background job in this codebase keeps its record in process
memory and re-derives the work from on-disk artefacts after a restart
(media.py's task dicts, the sun-timelapse session, the tracking queue).
This one cannot: a batch replay's whole value IS the report, and there
is no artefact to re-derive it from short of running the hours of
inference again. So the report goes to disk, atomically, and the GET
endpoint falls back to it whenever no run is in flight.

Written via `io_utils.atomic_write_json` — the same tmp-then-replace
helper the tracks sidecars use — so a dashboard poll during the write
sees the previous report or the new one, never a truncated document.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..io_utils import atomic_write_json
from ._consts import REPORT_FILENAME

log = logging.getLogger(__name__)


def report_path(storage_root) -> Path:
    """Where the report lives. One slot per installation."""
    return Path(storage_root) / REPORT_FILENAME


def save_report(storage_root, report: dict) -> bool:
    """Persist `report`. Never raises — a report that cannot be written
    is logged and the in-memory copy still answers the current poll,
    exactly the stance replay/_persist.py::append_replay takes when the
    event store refuses a write."""
    try:
        atomic_write_json(report_path(storage_root), report)
        return True
    except Exception as e:
        log.warning("[tracking] batch replay: report not persisted: %s", e)
        return False


def load_report(storage_root) -> dict | None:
    """The last persisted report, or None when there is none / it is
    unreadable. An unreadable report is treated as absent rather than
    fatal: the operator can always start a new run."""
    path = report_path(storage_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("[tracking] batch replay: stored report unreadable: %s", e)
        return None
    return data if isinstance(data, dict) else None
