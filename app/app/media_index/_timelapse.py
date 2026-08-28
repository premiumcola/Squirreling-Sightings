"""Register timelapse mp4s as EventStore entries — the reconciliation
nobody owned.

Only ``camera_runtime/_timelapse.py`` ever created a ``tl_*`` event. Every
timelapse produced through an HTTP route (the "jetzt bauen" button, the
QA-pill rebuild, the rolling build) wrote an mp4, a thumbnail and a QA
sidecar — but no metadata sidecar and no event. The boot migration
required that metadata sidecar, so those clips could never be
registered, and ``scan_media_files`` never even entered
``storage/timelapse/``. That is why "Neu scannen" could not fix the
count: it was structurally incapable of seeing a timelapse.

This registers from the **mp4 itself**, using the sidecar only for the
extra metadata when one happens to be there. Empty or truncated files
are refused, so a broken encode never becomes a tile — it shows up in
the integrity report instead.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ._scan import COUNTED_TREES, scan_camera
from ._types import MIN_VIDEO_BYTES

log = logging.getLogger(__name__)


def _event_time(stem: str, mp4: Path) -> str:
    """``YYYY-MM-DD`` prefix of the filename when the builder put one
    there, else the file's own mtime. Never ``now()`` — a rescan must not
    make a four-month-old clip look like it was made today."""
    head = stem[:10]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        try:
            datetime.strptime(head, "%Y-%m-%d")
            return f"{head}T12:00:00"
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(mp4.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return datetime.now().isoformat(timespec="seconds")


def _media_url(public_base: str, relpath: str) -> str:
    return f"{public_base}/media/{relpath}" if public_base else f"/media/{relpath}"


def _build_event(cam_id: str, stem: str, mp4: Path, meta: dict, public_base: str) -> dict:
    thumb = mp4.with_suffix(".jpg")
    video_rel = f"timelapse/{cam_id}/{mp4.name}"
    thumb_rel = f"timelapse/{cam_id}/{thumb.name}" if thumb.exists() else None
    thumb_url = _media_url(public_base, thumb_rel) if thumb_rel else None
    return {
        "event_id": f"tl_{stem}",
        "camera_id": cam_id,
        "camera_name": meta.get("camera_name") or cam_id,
        "type": "timelapse",
        "labels": ["timelapse"],
        "top_label": "timelapse",
        "time": meta.get("time") or _event_time(stem, mp4),
        "profile": meta.get("profile"),
        "window_key": meta.get("window_key"),
        "period_s": meta.get("period_s", 0),
        "target_s": meta.get("target_s", 0),
        "frame_count": meta.get("frame_count", 0),
        "filename": mp4.name,
        "video_relpath": video_rel,
        "video_url": _media_url(public_base, video_rel),
        "snapshot_relpath": thumb_rel,
        "snapshot_url": thumb_url,
        "thumb_url": thumb_url,
        "size_mb": meta.get("size_mb", 0),
        "duration_s": meta.get("duration_s", 0.0),
        "file_size_bytes": mp4.stat().st_size,
        "registered_by": "media_index",
    }


def _read_sidecar(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.debug("[timelapse] sidecar %s unreadable: %s", path.name, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def register_camera_timelapses(
    storage_root: Path, store, cam_id: str, public_base: str = ""
) -> int:
    """Register every playable mp4 under ``timelapse/<cam_id>/`` that has
    no ``tl_<stem>`` event yet. Idempotent; returns the number added."""
    cam_dir = storage_root / "timelapse" / cam_id
    if not cam_dir.is_dir():
        return 0
    index = scan_camera(storage_root, cam_id, trees=COUNTED_TREES)
    known = set(index.manifests) | set(index.tl_manifests)
    registered = 0
    for stem, rel in sorted(index.tl_media.items()):
        if f"tl_{stem}" in known:
            continue
        size = index.size_of(rel) or 0
        if size < MIN_VIDEO_BYTES:
            log.warning(
                "[timelapse] %s/%s.mp4 ist %d Byte gross — nicht registriert (kein Video)",
                cam_id,
                stem,
                size,
            )
            continue
        mp4 = storage_root / rel
        meta = _read_sidecar(cam_dir / f"{stem}.json") if stem in index.tl_sidecars else {}
        try:
            store.add_event(cam_id, _build_event(cam_id, stem, mp4, meta, public_base))
            registered += 1
        except Exception as exc:
            log.warning("[timelapse] register failed for %s/%s: %s", cam_id, stem, exc)
    return registered


def register_timelapse_events(storage_root: Path, store, public_base: str = "") -> int:
    """Run :func:`register_camera_timelapses` for every camera directory
    that exists under ``storage/timelapse/``."""
    tl_root = storage_root / "timelapse"
    if not tl_root.is_dir():
        return 0
    total = 0
    for cam_dir in sorted(tl_root.iterdir()):
        if cam_dir.is_dir():
            total += register_camera_timelapses(storage_root, store, cam_dir.name, public_base)
    if total:
        log.info("[timelapse] %d Timelapse-Video(s) im EventStore registriert", total)
    return total
