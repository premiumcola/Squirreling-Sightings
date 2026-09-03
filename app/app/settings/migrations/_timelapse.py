"""Timelapse profile seeding and interval clamping."""

from __future__ import annotations

import logging

from .._consts import TL_DEFAULT_PROFILES

log = logging.getLogger("app.settings.migrations")


def migrate_timelapse_profiles(data: dict) -> None:
    """Additively add missing timelapse profile keys to existing cameras."""
    for cam in data.get("cameras", []):
        tl = cam.setdefault("timelapse", {})
        profiles = tl.setdefault("profiles", {})
        for pname, pdefault in TL_DEFAULT_PROFILES.items():
            prof = profiles.setdefault(pname, {})
            for k, v in pdefault.items():
                prof.setdefault(k, v)
        # Migrate: if old timelapse.enabled=True but no profile enabled, enable daily
        if tl.get("enabled") and not any(p.get("enabled") for p in profiles.values()):
            profiles["daily"]["enabled"] = True


def migrate_timelapse_intervals(data: dict) -> None:
    """E1 · enforce the 2026-05-16 timelapse floor on legacy settings.json
    files: every capture interval clamps to ≥ 8 s, every fps locks to
    15. Two-pronged regression defuse:

      * Reolink's HTTP snapshot endpoint serves the same JPEG bytes
        for ~5–14 consecutive pulls at a 3 s interval (cached buffer);
        an 8 s floor drops the duplicate-frame rate from ~20 % to a
        single-digit residue without any camera-side change.
      * The encoder's "stretch to target_duration_s" math produces a
        choppy 4–5 fps MP4 the moment dedup drops too many frames.
        Locking the output to 15 fps eliminates that whole class of
        bug.

    Only the four fields below are mutated; every other key on
    every camera / weather block is left untouched (the migration
    must never destructively rewrite the JSON). Setdefault-style
    additive guards above the clamp catch the "block exists but
    field missing" case so a half-populated legacy file still gets
    valid 8 s / 15 fps values."""
    floor_s = 8
    fixed_fps = 15
    touched_intervals = 0
    touched_fps = 0
    for cam in data.get("cameras", []):
        if not isinstance(cam, dict):
            continue
        # Per-camera motion-snapshot interval. Used by storage compaction
        # AND by the recording layer; only the integer field moves.
        si = cam.get("snapshot_interval_s")
        if isinstance(si, (int, float)) and int(si) < floor_s:
            cam["snapshot_interval_s"] = floor_s
            touched_intervals += 1
        # Camera-side recurring timelapse (daily/weekly/...).
        tl = cam.get("timelapse")
        if isinstance(tl, dict) and tl.get("fps") not in (None, fixed_fps):
            tl["fps"] = fixed_fps
            touched_fps += 1
        # Weather block: sun_timelapse.{sunrise,sunset} + event_timelapse.
        cw = cam.get("weather")
        if not isinstance(cw, dict):
            continue
        sun_tl = cw.get("sun_timelapse")
        if isinstance(sun_tl, dict):
            for phase in ("sunrise", "sunset"):
                p = sun_tl.get(phase)
                if not isinstance(p, dict):
                    continue
                pi = p.get("interval_s")
                if isinstance(pi, (int, float)) and int(pi) < floor_s:
                    p["interval_s"] = floor_s
                    touched_intervals += 1
                if p.get("fps") not in (None, fixed_fps):
                    p["fps"] = fixed_fps
                    touched_fps += 1
        evt_tl = cw.get("event_timelapse")
        if isinstance(evt_tl, dict):
            ei = evt_tl.get("interval_s")
            if isinstance(ei, (int, float)) and int(ei) < floor_s:
                evt_tl["interval_s"] = floor_s
                touched_intervals += 1
            if evt_tl.get("fps") not in (None, fixed_fps):
                evt_tl["fps"] = fixed_fps
                touched_fps += 1
    if touched_intervals or touched_fps:
        log.info(
            "[migration] timelapse-floor: clamped %d interval_s ≥ %ds, " "forced %d fps → %d",
            touched_intervals,
            floor_s,
            touched_fps,
            fixed_fps,
        )
