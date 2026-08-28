"""Merge one camera into another — config, media and event history.

Carved out of routes/cameras.py (886 lines against a 500-line ceiling).
A single 150-line handler that moves files on disk and rewrites event
JSONs; it shares nothing with camera CRUD but the word "camera".
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
import shutil as _shutil
from pathlib import Path

from flask import Blueprint, jsonify

from .. import app_state

log = logging.getLogger(__name__)

bp = Blueprint("camera_merge", __name__)


@bp.post('/api/cameras/<source_id>/merge-into/<target_id>')
def api_camera_merge(source_id, target_id):
    """Move all media (events + timelapse) from source camera into target camera,
    rewrite affected JSON metadata so the events appear under the target on disk
    AND in the gallery, then delete the source camera entry from settings.

    Source may be archived (no settings entry, only files on disk) or an
    inactive/error camera that is still configured. Target must be a configured
    camera. Filename collisions get an `_m1`, `_m2`, … suffix; the same suffix
    is applied to the corresponding JSON so JSON ↔ media stay paired.
    """
    settings = app_state.settings
    runtimes = app_state.runtimes
    store = app_state.store
    storage_root = app_state.storage_root
    if source_id == target_id:
        return jsonify({"ok": False, "error": "Quelle und Ziel sind identisch"}), 400
    if not settings.get_camera(target_id):
        return jsonify({"ok": False, "error": "Ziel-Kamera nicht gefunden"}), 404

    src_events = store.events_dir / source_id
    tgt_events = store.events_dir / target_id
    src_tl = storage_root / "timelapse" / source_id
    tgt_tl = storage_root / "timelapse" / target_id

    moved_files = 0
    moved_events = 0
    moved_timelapses = 0

    def _resolve_collision(dest: Path) -> tuple[Path, str]:
        """Return a non-existing destination path + the suffix that was added.
        Suffix is appended to the stem (event_id) so the matching JSON can use
        the same suffix and stay paired with its media file."""
        if not dest.exists():
            return dest, ""
        for i in range(1, 10000):
            cand = dest.with_name(f"{dest.stem}_m{i}{dest.suffix}")
            if not cand.exists():
                return cand, f"_m{i}"
        raise RuntimeError("zu viele Kollisionen")

    # ── Events: walk JSON files first so we can rewrite + move their media ───
    if src_events.exists():
        tgt_events.mkdir(parents=True, exist_ok=True)
        for json_path in sorted(src_events.rglob("*.json")):
            rel_inside_cam = json_path.relative_to(src_events)
            tgt_json = tgt_events / rel_inside_cam
            tgt_json.parent.mkdir(parents=True, exist_ok=True)
            tgt_json, suffix = _resolve_collision(tgt_json)
            try:
                ev = _json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                # Corrupt JSON — just move it raw and skip rewrite
                json_path.rename(tgt_json)
                moved_files += 1
                continue

            old_event_id = ev.get("event_id") or json_path.stem
            new_event_id = old_event_id + suffix
            ev["event_id"] = new_event_id
            ev["camera_id"] = target_id
            ev["camera_name"] = settings.get_camera(target_id).get("name", target_id)

            # Move snapshot + video media files alongside the JSON
            for rel_key, url_key in (
                ("snapshot_relpath", "snapshot_url"),
                ("video_relpath", "video_url"),
            ):
                rel = ev.get(rel_key)
                if not rel:
                    continue
                src_media = storage_root / rel
                if not src_media.exists():
                    # Stale reference — drop it so the moved JSON isn't an orphan
                    ev[rel_key] = None
                    ev[url_key] = None
                    continue
                # Compute the path inside the source cam dir, then mirror it under target.
                try:
                    media_rel_inside_cam = src_media.relative_to(src_events)
                except ValueError:
                    # Media lives outside the camera tree (unusual) — skip move
                    continue
                tgt_media = tgt_events / media_rel_inside_cam
                tgt_media.parent.mkdir(parents=True, exist_ok=True)
                if suffix:
                    tgt_media = tgt_media.with_name(f"{tgt_media.stem}{suffix}{tgt_media.suffix}")
                # Final collision guard (should already be free thanks to suffix)
                tgt_media, _extra = _resolve_collision(tgt_media)
                src_media.rename(tgt_media)
                new_rel = tgt_media.relative_to(storage_root).as_posix()
                ev[rel_key] = new_rel
                ev[url_key] = f"/media/{new_rel}"
                moved_files += 1

            tgt_json.write_text(_json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
            json_path.unlink(missing_ok=True)
            moved_events += 1
            moved_files += 1

        # Sweep any orphan media still in the source tree (e.g. files that had
        # no JSON yet — scan_media_files would have registered them later).
        for media in list(src_events.rglob("*")):
            if not media.is_file():
                continue
            rel_inside_cam = media.relative_to(src_events)
            dest = tgt_events / rel_inside_cam
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest, _ = _resolve_collision(dest)
            media.rename(dest)
            moved_files += 1

        # Drop empty directories from the source tree
        with contextlib.suppress(Exception):
            _shutil.rmtree(src_events)

    # ── Timelapse: simple file move, no metadata to rewrite ───────────────────
    if src_tl.exists():
        tgt_tl.mkdir(parents=True, exist_ok=True)
        for f in list(src_tl.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src_tl)
            dest = tgt_tl / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest, _ = _resolve_collision(dest)
            f.rename(dest)
            moved_files += 1
            moved_timelapses += 1
        with contextlib.suppress(Exception):
            _shutil.rmtree(src_tl)

    # ── Drop the source camera entry + stop its runtime ───────────────────────
    if settings.get_camera(source_id):
        settings.delete_camera(source_id)
        rt = runtimes.pop(source_id, None)
        if rt:
            rt.stop()

    return jsonify(
        {
            "ok": True,
            "source_id": source_id,
            "target_id": target_id,
            "moved_files": moved_files,
            "moved_events": moved_events,
            "moved_timelapses": moved_timelapses,
        }
    )
