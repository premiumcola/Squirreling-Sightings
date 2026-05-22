"""Filesystem helpers shared across services.

Hosts ``atomic_write_json`` — the single consolidation point for
crash-safe JSON writes. Two near-identical helpers had been
co-existing (``bird_dossiers._atomic_write_json`` and
``weather_service._consts._atomic_write_json``); future call sites
land here so we don't grow a third.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any


# P30 · cache for static Path.exists() checks on hot paths.
#
# IMPORTANT — only use for paths that do NOT change during the
# process lifetime. Safe:
#   • model files in /app/models/*.tflite
#   • static assets baked into the image
#   • config.yaml (read-only at boot)
# UNSAFE — these change at runtime and the cache will go stale:
#   • settings.json (atomic rename → new inode each save)
#   • storage/motion_detection/** (events created/deleted live)
#   • storage/timelapse/** (cron-built mp4s appear during runtime)
#   • any path under storage/
#
# The cache is in-process; no inter-worker invalidation. A test
# that mutates a "static" path mid-run must call
# ``path_exists_cached.cache_clear()`` to reset.
@lru_cache(maxsize=512)
def path_exists_cached(p: str) -> bool:
    """Cached existence check for paths that don't change at
    runtime. Pass a string (not a Path) so the LRU key stays
    hashable across Path identity quirks. See module docstring
    for the "what is safe to cache" rules."""
    return Path(p).exists()


def path_cache_invalidate(p: str | None = None) -> None:
    """Drop one entry (when ``p`` is given) or the whole cache.
    Migrations that rename many files at once should call this
    with no arg so the next exists-check sees the new layout."""
    if p is None:
        path_exists_cached.cache_clear()
    else:
        # functools.lru_cache has no per-key delete — re-prime by
        # clearing the whole cache. Cheap (rare-call) so we don't
        # bother with a custom cache implementation.
        path_exists_cached.cache_clear()


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    indent: int = 2,
    fsync: bool = False,
) -> None:
    """Write ``payload`` as JSON to ``path`` atomically.

    Pattern: write to a temp file in the same directory, then
    ``os.replace`` over the target. This guarantees a concurrent
    reader sees either the previous version or the new one — never
    a truncated mid-write file, even if the process is killed
    between ``open`` and ``close``.

    The temp file name carries the writer's pid + tid so two
    threads racing to update the same file don't trample each
    other's temp blob (the underlying issue that motivated the
    weather_service variant of this helper).

    Pass ``fsync=True`` for files whose loss across an OS-level
    crash matters (e.g. weather history, time-series state). The
    default is False because for derived files (manifests,
    sidecars) we'd rather the cheap path than the durable one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    if fsync:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=indent)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
    else:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=indent),
            encoding="utf-8",
        )
    os.replace(str(tmp), str(path))
