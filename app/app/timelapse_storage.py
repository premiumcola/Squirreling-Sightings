"""Cached on-disk accounting for timelapse frame directories.

``storage/timelapse_frames/`` is the largest transient consumer on the
box — a single daily profile holds ~900 JPEGs at ~300 KB each, i.e.
~264 MB per camera, and it was invisible to both the timelapse status
panel and /api/media/storage-stats.

Measuring it is cheap but not free: ``scandir`` + ``stat`` over a
900-file window costs ~2.4 ms, and a dashboard that polls every 5 s
across 3 cameras × 6 profiles would spend ~29 ms per request doing
nothing but counting. Telemetry that costs what it measures is worse
than none, so every read goes through a 60 s TTL cache. The fastest
profile writes one frame every 96 s, so a 60 s entry can never be more
than a frame or two stale.

The cache is recomputed lazily on read — a closed dashboard costs
nothing — and invalidated explicitly when a window is encoded and its
frames are deleted, so the panel drops to zero immediately instead of
showing a stale 264 MB for up to a minute.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

TTL_S = 60.0

# key -> (expires_at_monotonic, payload)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _scan_window(window_dir: Path) -> dict:
    """One scandir pass — count, bytes, oldest / newest mtime."""
    count = 0
    total = 0
    oldest: float | None = None
    newest: float | None = None
    try:
        with os.scandir(window_dir) as it:
            for entry in it:
                if not entry.name.endswith(".jpg"):
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                count += 1
                total += st.st_size
                if oldest is None or st.st_mtime < oldest:
                    oldest = st.st_mtime
                if newest is None or st.st_mtime > newest:
                    newest = st.st_mtime
    except OSError:
        pass
    return {
        "frame_count": count,
        "bytes_on_disk": total,
        "oldest_frame": _iso(oldest),
        "newest_frame": _iso(newest),
    }


def _empty(window_key: str | None = None) -> dict:
    return {
        "window_key": window_key,
        "frame_count": 0,
        "bytes_on_disk": 0,
        "oldest_frame": None,
        "newest_frame": None,
        "captured": 0,
        "rejected": 0,
    }


def _compute(storage_root: Path, camera_id: str, profile_name: str) -> dict:
    profile_dir = Path(storage_root) / "timelapse_frames" / camera_id / profile_name
    if not profile_dir.is_dir():
        return _empty()
    windows = [d for d in profile_dir.iterdir() if d.is_dir()]
    if not windows:
        return _empty()
    # Newest window by mtime — works for calendar keys (daily/weekly/…)
    # and for the custom profile's ``<date>_<HHMMSS>`` keys alike, so no
    # caller has to know how a profile names its windows.
    current = max(windows, key=lambda d: d.stat().st_mtime)
    out = _empty(current.name)
    out.update(_scan_window(current))
    # The capture loop already writes captured / invalid counters next to
    # the frames on every interval — read them instead of recomputing.
    from .frame_helpers import read_capture_stats

    stats = read_capture_stats(current) or {}
    out["captured"] = int(stats.get("captured_frames") or 0)
    out["rejected"] = int(stats.get("invalid_frames") or 0)
    return out


def profile_usage(storage_root: Path, camera_id: str, profile_name: str) -> dict:
    """Disk facts for a profile's current window. Cached for ``TTL_S``."""
    key = (camera_id, profile_name)
    now = _now()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return dict(hit[1])
    try:
        payload = _compute(Path(storage_root), camera_id, profile_name)
    except Exception as e:
        log.debug("[timelapse] usage scan failed for %s/%s: %s", camera_id, profile_name, e)
        payload = _empty()
    with _lock:
        _cache[key] = (now + TTL_S, payload)
    return dict(payload)


def invalidate(camera_id: str, profile_name: str | None = None) -> None:
    """Drop cached entries. Called right after a window is encoded and
    its frame directory removed, so the panel doesn't keep reporting
    frames that no longer exist."""
    with _lock:
        if profile_name is not None:
            _cache.pop((camera_id, profile_name), None)
            return
        for key in [k for k in _cache if k[0] == camera_id]:
            _cache.pop(key, None)


def camera_frames_bytes(storage_root: Path, camera_id: str, profiles: tuple[str, ...]) -> int:
    """Total bytes held by this camera's timelapse frame windows.

    Sums the cached per-profile figures rather than walking the tree, so
    /api/media/storage-stats gains the missing number without gaining
    the walk that made it expensive.
    """
    return sum(profile_usage(storage_root, camera_id, p).get("bytes_on_disk", 0) for p in profiles)


def projected_bytes(usage: dict, expected_frames: int) -> int:
    """Extrapolate the full-window footprint from what is on disk now.

    Uses the observed mean frame size rather than a hard-coded KB
    constant — the frontend's 40 KB/frame guess was ~7.5× under the
    ~300 KB a 2560×1440 JPEG at q=72 actually costs.
    """
    count = int(usage.get("frame_count") or 0)
    if count <= 0 or expected_frames <= 0:
        return 0
    mean = int(usage.get("bytes_on_disk") or 0) / count
    return int(mean * max(count, expected_frames))
