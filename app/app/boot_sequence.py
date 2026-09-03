"""The ordered side-effecting steps of a boot, lifted out of server.py.

``lifecycle.py`` owns the boot *helpers* (inventory rendering, shutdown
hooks, media scan). What lived in ``server.py`` and moves here is the
*sequence*: which migrations run, in what order, and what happens to a
failure in each. server.py was 610 lines against a 500 ceiling, and this
is the part of it that is a concern rather than a wiring diagram.

Every function here takes what it needs as an argument. None of them
touches a module-level global, which is the property that makes the move
safe: the service singletons in server.py (`telegram_service`,
`mqtt_service`, `weather_service`, `cfg`) are rebound through `global`
statements, and a function that does that cannot move to another module
without silently rebinding the wrong name. Those stayed behind.

Nothing here imports server.py — see routes/__init__ for why that import
must never exist (R01.6).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def log_route_inventory(app) -> None:
    """P26 · one INFO line summarising registered routes at boot.
    Anything that drops the count by ≥ 5 between deploys is a sign
    a blueprint failed to register silently. The DEBUG branch dumps
    each route so operators can grep for a specific path when
    diagnosing a 404."""
    _log = logging.getLogger(__name__)
    routes = sorted(
        (str(r), sorted(r.methods - {"HEAD", "OPTIONS"}))
        for r in app.url_map.iter_rules()
        if not str(r).startswith("/static")
    )
    _log.info("[boot] %d routes registered", len(routes))
    if _log.isEnabledFor(logging.DEBUG):
        for path, methods in routes:
            _log.debug("[boot]   %s  %s", ",".join(methods), path)


def emit_boot_inventory(base_cfg: dict, storage_root: Path) -> None:
    """Boot inventory — single block summarising the bootstrap state.

    Runs right after settings load, before any subsystem starts emitting
    its own log lines, so the inventory sits at the top of every
    restart's ``docker logs`` tail.
    """
    from .lifecycle import _emit_boot_inventory

    try:
        _emit_boot_inventory(base_cfg, storage_root)
    except Exception as e:
        logging.getLogger(__name__).warning("[boot] inventory render failed: %s", e)


def run_early_migrations(settings, storage_root: Path) -> None:
    """The two migrations that must finish before any runtime starts.

    Both are idempotent and both swallow-and-log rather than abort: a
    half-migrated store is still bootable, and refusing to start would
    leave the operator with no dashboard to fix it from.
    """
    # One-shot semantic-id migration. Idempotent — on a clean boot it logs
    # a single "no migration needed" line. Must run BEFORE rebuild_runtimes()
    # so the camera threads pick up the new ids on first start, never the old.
    try:
        from .storage_migration import migrate as _migrate_storage

        _migrate_storage(settings, storage_root)
    except Exception as e:
        logging.getLogger(__name__).error(
            "[migration] storage migration failed (continuing with existing state): %s",
            e,
            exc_info=True,
        )
    # Sun-Timelapse layout split: legacy `weather/<cam>/sun_timelapse/`
    # (mixed sunrise+sunset) → per-phase dirs. Idempotent, manifests are
    # backed up before rewrite. Touches only weather sighting files; never
    # settings.json. Must run before WeatherService starts so the service
    # only sees the new layout.
    try:
        from .weather_service import migrate_sun_timelapse_layout as _migrate_sun_tl

        _migrate_sun_tl(storage_root)
    except Exception as e:
        logging.getLogger(__name__).error(
            "[migration] sun_timelapse split failed (continuing with existing state): %s",
            e,
            exc_info=True,
        )


def start_tracking_worker(settings, base_cfg: dict, storage_root: Path) -> None:
    """Phase 1 object tracking — the singleton worker.

    Started right after the camera runtimes are up. The config getters
    pull the live blocks from settings on every job, so a settings reload
    swaps the detector (and the second-stage bird model the clip replay
    needs to put a NAME on what it finds) without restarting the worker
    thread.
    """
    from .tracking_worker import build_worker as build_tracking_worker

    def _detection_cfg():
        return settings.export_effective_config(base_cfg).get("processing", {}).get("detection", {})

    def _bird_cfg():
        return (
            settings.export_effective_config(base_cfg).get("processing", {}).get("bird_species", {})
        )

    build_tracking_worker(
        storage_root=storage_root,
        detection_cfg_getter=_detection_cfg,
        cam_cfg_getter=lambda cam_id: settings.get_camera(cam_id) or {},
        bird_cfg_getter=_bird_cfg,
    )


def run_boot_migrations(
    storage_root: Path, settings, store, base_cfg: dict, boot_ts: float
) -> None:
    """Boot-time migrations — see app/app/migrations.py.

    Each one spawns its own daemon thread; safe to re-run; idempotent.
    """
    from . import migrations as _migrations

    _migrations.cleanup_stale_timelapse_frames(storage_root=storage_root, settings=settings)
    # Tidy loose root-level <event_id>.json (+ .tracks.json) into their date
    # subfolders so the camera root stops collecting clutter. Reads use
    # rglob, so this is purely cosmetic for the on-disk layout.
    _migrations.relocate_root_event_jsons(storage_root=storage_root)
    _migrations.generate_missing_thumbnails(storage_root=storage_root)
    # Clips whose producer died mid-chain (restart, ffmpeg hang, power cut).
    # Everything still in flight from before _BOOT_TS is orphaned by
    # definition — recover it if its mp4 is on disk, otherwise mark it
    # failed so the card stops claiming it is still working.
    _migrations.adopt_orphaned_clips(
        storage_root=storage_root,
        settings=settings,
        base_cfg=base_cfg,
        started_at=datetime.fromtimestamp(boot_ts),
    )
    _migrations.migrate_timelapse_to_eventstore(
        storage_root=storage_root,
        settings=settings,
        store=store,
        base_cfg=base_cfg,
    )
    # Diagnostic only — logs a single line when older-schema tracks.json
    # sidecars are present so the operator knows to hit
    # /api/tracking/reindex-all. Never reindexes automatically.
    _migrations.check_tracks_schema_version(storage_root=storage_root)


def telegram_cfg_diff(prev: dict | None, new: dict) -> str:
    """One-line description of what changed between two telegram configs.

    T61 diagnostic. The Conflict this chases reappeared ~4 min after
    boot, well past the old fixed 120 s window, so the caller logs this
    on every reload — which is only affordable because the expensive
    half (the caller stack) is rate-limited separately.
    """
    if prev is None:
        return "prev=None"
    if prev == new:
        return "IDENTICAL — skip-guard should have fired"
    return (
        f"only_in_prev={sorted(set(prev) - set(new))} · "
        f"only_in_new={sorted(set(new) - set(prev))} · "
        f"changed_keys={sorted(k for k in set(prev) & set(new) if prev[k] != new[k])}"
    )
