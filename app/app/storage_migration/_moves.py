"""Moving files between storage folders, and repointing what names them.

A single failed move is logged at ERROR but never aborts the run —
partial progress is fine, because the next boot picks up where we
stopped.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from ._consts import log


def _move_file(src: Path, dst: Path):
    """Move a single file from src to dst with collision handling.
    On collision keep the newer mtime, drop the older. Logs an ERROR on
    failure but does not raise — caller continues to the next file."""
    try:
        if dst.exists():
            try:
                src_mtime = src.stat().st_mtime
                dst_mtime = dst.stat().st_mtime
            except OSError:
                src_mtime = dst_mtime = 0.0
            if src_mtime > dst_mtime:
                src.replace(dst)
                log.debug("[migration] overwrite %s (newer)", dst)
            else:
                log.debug("[migration] drop older %s (kept %s)", src, dst)
                src.unlink()
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
    except Exception as e:
        log.error("[migration] move failed: %s → %s: %s", src, dst, e)


def _merge_folder(src: Path, target: Path) -> int:
    """Move every file in src (recursively) into target, preserving
    subpaths. Returns the number of files moved. Removes src when empty."""
    if src == target:
        return 0
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in list(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        _move_file(path, target / rel)
        moved += 1
    # rmdir empty subdirs deepest-first, then the source itself.
    for d in sorted((p for p in src.rglob("*") if p.is_dir()), reverse=True):
        with contextlib.suppress(OSError):
            d.rmdir()
    try:
        src.rmdir()
    except OSError as e:
        log.warning("[migration] source not empty after merge: %s (%s)", src, e)
    return moved


def _rewrite_event_jsons(events_dir: Path, old_ids: list[str], new_id: str) -> int:
    """Atomic-write rewrite of every .json under events_dir whose
    video_relpath / snapshot_relpath still contains an old id string.
    Returns the count of files actually rewritten."""
    if not events_dir.exists():
        return 0
    olds = [o for o in old_ids if o and o != new_id]
    if not olds:
        return 0
    rewritten = 0
    for jf in events_dir.rglob("*.json"):
        try:
            text = jf.read_text(encoding="utf-8")
        except Exception:
            continue
        new_text = text
        for old in olds:
            if old in new_text:
                new_text = new_text.replace(old, new_id)
        if new_text == text:
            continue
        tmp = jf.with_suffix(".json.tmp")
        try:
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(jf)
            rewritten += 1
        except Exception as e:
            log.error("[migration] event JSON rewrite failed for %s: %s", jf, e)
    return rewritten
