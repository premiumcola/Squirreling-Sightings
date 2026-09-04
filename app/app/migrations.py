"""Boot-time migration helpers — idempotent, safe to re-run.

Carved out of server.py during R01.6. Each helper spawns its own
daemon thread so server.py's main boot sequence never blocks on
filesystem I/O. Receive their dependencies (storage paths, settings
store, event store, base config) as plain arguments so this module
has zero coupling back to server.py.
"""

from __future__ import annotations

import json as _json
import logging
import shutil as _shutil
import threading
import time as _time
from datetime import datetime
from pathlib import Path

import cv2 as _cv2

from . import clip_recovery
from .media_index import register_timelapse_events
from .storage import event_date_subdir

log = logging.getLogger(__name__)


def cleanup_stale_timelapse_frames(*, storage_root: Path, settings) -> None:
    """Drop ``timelapse_frames/`` directories for deleted cameras and for
    profiles that are switched off.

    This used to ALSO delete every ``tl_*.json`` from
    ``motion_detection/``, on the theory that timelapses were tracked by
    sidecars next to the mp4 instead. It was written as a one-shot but
    ran on every boot — while :func:`migrate_timelapse_to_eventstore`,
    started six statements later in a second unordered daemon thread,
    recreated exactly those files. Two migrations with opposite intent
    raced at every start, so how many timelapse tiles the Mediathek
    showed depended on which thread won. The deleter is gone; the
    EventStore entry is now the single record of a timelapse.
    """

    def _do_migrate():
        # Clean up stale timelapse_frames dirs for cameras that no longer exist
        try:
            frames_root = storage_root / "timelapse_frames"
            if not frames_root.exists():
                return
            cameras = settings.data.get("cameras") or []
            active_ids = {c["id"] for c in cameras}
            # Build map of which profiles are enabled per camera
            enabled_profiles: dict[str, set] = {}
            for c in cameras:
                tl = c.get("timelapse") or {}
                profs = tl.get("profiles") or {}
                enabled_profiles[c["id"]] = {p for p, cfg in profs.items() if cfg.get("enabled")}

            cleaned = 0
            for cam_dir in frames_root.iterdir():
                if not cam_dir.is_dir():
                    continue
                if cam_dir.name not in active_ids:
                    try:
                        _shutil.rmtree(str(cam_dir))
                        cleaned += 1
                        log.info(
                            "[migration] Removed frame dir for deleted camera: %s", cam_dir.name
                        )
                    except Exception as e:
                        log.warning("[migration] Could not remove %s: %s", cam_dir.name, e)
                    continue
                # For active cameras: remove frame dirs for DISABLED profiles
                active_profs = enabled_profiles.get(cam_dir.name, set())
                for prof_dir in cam_dir.iterdir():
                    if not prof_dir.is_dir():
                        continue
                    if prof_dir.name not in active_profs:
                        try:
                            _shutil.rmtree(str(prof_dir))
                            cleaned += 1
                            log.info(
                                "[migration] Removed frame dir for disabled profile: %s/%s",
                                cam_dir.name,
                                prof_dir.name,
                            )
                        except Exception as e:
                            log.warning("[migration] Could not remove %s: %s", prof_dir, e)
            if cleaned:
                log.info("[migration] Cleaned %d stale frame directories", cleaned)
        except Exception as e:
            log.warning("[migration] Stale frame dir cleanup failed: %s", e)

    threading.Thread(target=_do_migrate, daemon=True).start()


def generate_missing_thumbnails(*, storage_root: Path) -> None:
    """Generate thumbnail .jpg for any timelapse .mp4 that does not have one yet.
    Runs once on startup in background — safe to re-run, skips if thumb exists."""

    def _do():
        tl_base = storage_root / "timelapse"
        if not tl_base.exists():
            return
        count = 0
        for cam_dir in tl_base.iterdir():
            if not cam_dir.is_dir():
                continue
            for mp4 in cam_dir.glob("*.mp4"):
                thumb = mp4.with_suffix(".jpg")
                if thumb.exists():
                    continue
                try:
                    cap = _cv2.VideoCapture(str(mp4))
                    total = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
                    if total > 0:
                        cap.set(_cv2.CAP_PROP_POS_FRAMES, total // 2)
                    ok, frame = cap.read()
                    cap.release()
                    if ok and frame is not None:
                        tw, th = frame.shape[1], frame.shape[0]
                        if tw > 640:
                            scale = 640 / tw
                            frame = _cv2.resize(frame, (640, int(th * scale)))
                        _cv2.imwrite(str(thumb), frame, [int(_cv2.IMWRITE_JPEG_QUALITY), 80])
                        del frame
                        count += 1
                except Exception as e:
                    log.debug("[thumb] failed for %s: %s", mp4.name, e)
                _time.sleep(0.05)  # pace startup
        if count:
            log.info("[boot] Generated %d missing timelapse thumbnails", count)

    threading.Thread(target=_do, daemon=True).start()


def generate_missing_scrub_sprites(*, storage_root: Path, store=None) -> None:
    """Backfill the scrub filmstrip for motion clips recorded before it.

    Every clip from here on gets its sheet in the re-encode thread. The
    archive does not, and a player whose drag-preview works only on
    clips newer than one deploy is the kind of half-feature that reads
    as broken. So: one pass at boot, in the background, skipping
    anything that already has a sheet.

    PACED ON PURPOSE. This is a full sequential decode per clip, and an
    archive can hold thousands. The sleep between clips is what keeps a
    backfill from competing with live recording for the same cores —
    the same reason ``generate_missing_thumbnails`` paces itself, and
    the same reason ``check_tracks_schema_version`` refuses to
    auto-reindex.

    The event JSON is updated too, when a store is supplied: the sheet
    on disk is useless to the player without the grid that addresses
    it. A clip whose manifest cannot be found still gets its sheet, so
    a later reconcile can pick it up.
    """

    def _do():
        base = storage_root / "motion_detection"
        if not base.exists():
            return
        from .scrub_sprite import build_scrub_sprite, sprite_path_for

        made = 0
        for cam_dir in sorted(base.iterdir()):
            if not cam_dir.is_dir():
                continue
            for mp4 in sorted(cam_dir.rglob("*.mp4")):
                # `.raw.mp4` is the stream copy, not the clip the player
                # plays — a sheet built from it would drift from the
                # spliced, re-encoded file by the whole pre-roll.
                if mp4.name.endswith(".raw.mp4"):
                    continue
                if sprite_path_for(mp4).exists():
                    continue
                try:
                    geo = build_scrub_sprite(mp4)
                    if not geo:
                        continue
                    made += 1
                    if store is not None:
                        _attach_scrub(store, cam_dir.name, mp4.stem, geo)
                except Exception as e:
                    log.debug("[scrub] backfill failed for %s: %s", mp4.name, e)
                _time.sleep(0.05)  # pace startup
        if made:
            log.info("[boot] %d Scrub-Filmstreifen nachgebaut", made)

    threading.Thread(target=_do, daemon=True).start()


def _attach_scrub(store, camera_id: str, event_id: str, geo: dict) -> None:
    """Put one backfilled sheet's geometry onto its event JSON.

    Additive by construction — reads the manifest, sets one key, writes
    it back through the store's own atomic path. Never touches anything
    else on the event.
    """
    try:
        ev = store.get_event(camera_id, event_id)
        if not ev:
            return
        ev["scrub"] = geo
        store.update_event(camera_id, event_id, ev)
    except Exception as e:
        log.debug("[scrub] manifest update failed for %s: %s", event_id, e)


def check_tracks_schema_version(*, storage_root: Path) -> None:
    """Boot scan: count existing tracks.json sidecars whose schema
    version is older than the current ``TRACKS_SCHEMA``. The intent is
    purely diagnostic — we log a single line so the operator knows to
    hit ``/api/tracking/reindex-all`` once after a schema bump. We do
    NOT auto-reindex: a large archive could spawn thousands of jobs
    and saturate the worker for an hour.
    """

    def _do():
        try:
            # Local import keeps this helper independent of worker
            # construction order at boot.
            from .tracking_worker import TRACKS_SCHEMA

            events_root = storage_root / "motion_detection"
            if not events_root.exists():
                return
            stale = 0
            current = 0
            # Group stale by the schema we saw so the log line shows
            # the user exactly which migration step the archive is on.
            by_old: dict = {}
            for cam_dir in events_root.iterdir():
                if not cam_dir.is_dir():
                    continue
                for tp in cam_dir.rglob("*.tracks.json"):
                    try:
                        payload = _json.loads(tp.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    schema = payload.get("schema")
                    if schema == TRACKS_SCHEMA:
                        current += 1
                    else:
                        stale += 1
                        by_old[schema] = by_old.get(schema, 0) + 1
            if stale:
                versions = ", ".join(
                    f"v{k}={v}"
                    for k, v in sorted(
                        by_old.items(),
                        key=lambda kv: (kv[0] is None, kv[0]),
                    )
                )
                log.info(
                    "[tracking] schema=%d (was=%d old sidecars detected: %s, "
                    "run /api/tracking/reindex-all to refresh)",
                    TRACKS_SCHEMA,
                    stale,
                    versions,
                )
            elif current:
                log.debug("[tracking] schema=%d (%d sidecars current)", TRACKS_SCHEMA, current)
        except Exception as e:
            log.warning("[tracking] schema scan failed: %s", e)

    threading.Thread(target=_do, daemon=True).start()


def _relocate_root_event_jsons_sync(storage_root: Path) -> int:
    """Synchronous worker for :func:`relocate_root_event_jsons` — returns
    the number of files moved. Factored out so the boot wrapper can run
    it in a daemon thread while the test suite drives it deterministically."""
    events_root = storage_root / "motion_detection"
    if not events_root.exists():
        return 0
    moved = 0
    for cam_dir in events_root.iterdir():
        if not cam_dir.is_dir():
            continue
        # Non-recursive: only files sitting directly in the camera root.
        # Anything already inside a date subdir is skipped.
        for jf in list(cam_dir.glob("*.json")):
            name = jf.name
            if name.startswith("tl_"):
                continue  # timelapse — the tl_ event lives at the camera root
            if name.endswith(".tracks.json"):
                event_id = name[: -len(".tracks.json")]
            else:
                event_id = jf.stem
            subdir = event_date_subdir(event_id)
            if subdir is None:
                continue  # unparseable id — leave in place
            target_dir = cam_dir / subdir
            target = target_dir / name
            if target.exists():
                continue  # already relocated / clash — never overwrite
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                _shutil.move(str(jf), str(target))
                moved += 1
            except Exception as e:
                log.warning("[migration] relocate %s failed: %s", name, e)
    return moved


def relocate_root_event_jsons(*, storage_root: Path) -> None:
    """One-time, idempotent: move loose ``<event_id>.json`` (and the
    matching ``<event_id>.tracks.json`` sidecar) that sit directly in a
    camera root under ``storage/motion_detection/<cam>/`` into the date
    subfolder derived from ``event_id[:8]`` (``YYYYMMDD`` -> ``YYYY-MM-DD``),
    co-locating them with their mp4/jpg media.

    Leaves untouched: files whose id isn't an 8-digit date prefix
    (custom/legacy ids), and ``tl_*.json`` timelapse entries (owned by
    :func:`migrate_timelapse_to_eventstore`). Skips a move when the target
    already exists (no overwrite). Safe to re-run — the non-recursive
    glob only sees still-loose files, so once everything is relocated it
    finds nothing and logs nothing."""

    def _do():
        try:
            moved = _relocate_root_event_jsons_sync(storage_root)
            if moved:
                log.info(
                    "[migration] relocated %d root-level event JSON(s) into date subfolders",
                    moved,
                )
        except Exception as e:
            log.warning("[migration] event-JSON relocation failed: %s", e)

    threading.Thread(target=_do, daemon=True).start()


def adopt_orphaned_clips(
    *, storage_root: Path, settings, base_cfg: dict, started_at: datetime
) -> None:
    """Give every clip left in flight by a dead process its terminal state.

    A clip only ever moved forward through its stages, and only by the
    thread doing the work, so a container restart mid-encode froze the
    manifest at ``encoding`` for good — the card read "hängt · 5 h 51
    min" with no recovery path but manual deletion. At boot the owning
    process is gone by definition, so the file on disk is the only
    truth left: a playable mp4 next to the manifest becomes ``ready``,
    everything else becomes an honest ``failed``. See
    :mod:`app.app.clip_recovery`; nothing is deleted.

    ``started_at`` is the process start. Cameras are already live when
    this thread runs, so it is what keeps the sweep off a recording
    that began seconds ago.
    """

    def _do():
        try:
            cfg = settings.export_effective_config(base_cfg)
            public_base = (cfg.get("server", {}).get("public_base_url") or "").rstrip("/")
            result = clip_recovery.sweep_orphaned_clips(
                storage_root, started_at=started_at, public_base=public_base
            )
            if result["recovered"] or result["failed"]:
                log.info(
                    "[migration] %d abgebrochene(r) Clip(s) wiederhergestellt, "
                    "%d als fehlgeschlagen markiert",
                    result["recovered"],
                    result["failed"],
                )
        except Exception as e:
            log.warning("[migration] Clip-Adoption fehlgeschlagen: %s", e)

    threading.Thread(target=_do, daemon=True).start()


def migrate_timelapse_to_eventstore(*, storage_root: Path, settings, store, base_cfg: dict) -> None:
    """Register every timelapse mp4 as an EventStore entry.

    The old implementation iterated ``timelapse/<cam>/*.json`` and
    required a metadata sidecar next to the mp4. Only the camera runtime
    writes that sidecar — every timelapse produced through an HTTP route
    ("jetzt bauen", QA-Rebuild, rolling) has an mp4, a thumbnail and a QA
    file but no sidecar, so it could never be registered and never
    appeared in the grid while the badge counted it. Registration now
    starts from the mp4 (:mod:`app.media_index`), which is the file the
    operator actually cares about.
    """

    def _do():
        try:
            cfg = settings.export_effective_config(base_cfg)
            public_base = (cfg.get("server", {}).get("public_base_url") or "").rstrip("/")
            register_timelapse_events(storage_root, store, public_base)
        except Exception as e:
            log.warning("[migration] timelapse registration failed: %s", e)

    threading.Thread(target=_do, daemon=True).start()
