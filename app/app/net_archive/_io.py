"""Paths, atomic JSON round-trips and the frame re-encode.

Best-effort throughout, on the same principle as ``detection_feedback``:
an archive write must never break a capture loop or lose an alert. Every
failure is swallowed and logged with the ``[storage]`` tag.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..storage import _atomic_write_text
from ._consts import ARCHIVE_DIRNAME, FRAME_JPEG_QUALITY, FRAME_MAX_EDGE

log = logging.getLogger(__name__)


def archive_root(storage_root) -> Path:
    return Path(storage_root) / ARCHIVE_DIRNAME


def _month_of(event_id: str) -> str:
    """``YYYY-MM`` from an event id (``YYYYMMDD-HHMMSS-ffffff``).

    ``storage.event_date_subdir`` derives a day folder from the same
    first eight characters; this is the month-granular sibling. An id
    that does not carry a parsable date lands in ``unknown`` rather than
    being dropped — a record with a broken name is still a record.
    """
    head = (event_id or "")[:8]
    if len(head) == 8 and head.isdigit():
        return f"{head[:4]}-{head[4:6]}"
    return "unknown"


def record_path(storage_root, event_id: str) -> Path:
    return archive_root(storage_root) / _month_of(event_id) / f"{event_id}.json"


def frame_path(storage_root, event_id: str) -> Path:
    return archive_root(storage_root) / _month_of(event_id) / f"{event_id}.jpg"


def iter_record_paths(storage_root):
    """Every record JSON on disk, newest month first."""
    root = archive_root(storage_root)
    if not root.is_dir():
        return
    for month in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        yield from sorted(month.glob("*.json"), reverse=True)


def read_record(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("[storage] net_archive: unlesbarer Datensatz %s: %s", path.name, e)
        return None
    return payload if isinstance(payload, dict) else None


def load_record(storage_root, event_id: str) -> dict | None:
    path = record_path(storage_root, event_id)
    return read_record(path) if path.is_file() else None


def save_record(storage_root, event_id: str, payload: dict) -> bool:
    """Atomic write of one record. Returns success."""
    try:
        path = record_path(storage_root, event_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        log.warning("[storage] net_archive: Datensatz %s nicht geschrieben: %s", event_id, e)
        return False


def delete_record(storage_root, event_id: str) -> None:
    for path in (record_path(storage_root, event_id), frame_path(storage_root, event_id)):
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            log.debug("[storage] net_archive: %s nicht gelöscht: %s", path.name, e)


def save_frame(storage_root, event_id: str, jpeg_bytes) -> bool:
    """Store the archive's OWN copy of the frame, re-encoded small.

    Its own copy is the point: at 14 days retention sweeps the event
    JSON, the snapshot and the clip, and the historically interesting
    moment is precisely the one that must still have a picture. cv2 is
    imported lazily — the archive must degrade to "record without image"
    on a host where it is missing rather than refusing to write at all.
    """
    if not jpeg_bytes:
        return False
    try:
        import cv2
        import numpy as np

        buf = np.frombuffer(bytes(jpeg_bytes), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return False
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest > FRAME_MAX_EDGE:
            scale = FRAME_MAX_EDGE / float(longest)
            img = cv2.resize(
                img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA
            )
        ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), FRAME_JPEG_QUALITY])
        if not ok:
            return False
        path = frame_path(storage_root, event_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(enc.tobytes())
        return True
    except Exception as e:
        log.debug("[storage] net_archive: Bild zu %s nicht gespeichert: %s", event_id, e)
        return False
