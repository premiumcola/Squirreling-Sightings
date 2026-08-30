"""Boot-time migrations applied to settings.json.

Each function takes the raw `data` dict and mutates it in place. The
ordered MIGRATIONS list at the bottom is the authoritative call
sequence — store.load() iterates it once on every load. Newer
migrations append to the end; never reorder existing entries because
they may depend on one another (e.g. migrate_class_severity reads
alarm_profile which migrate_camera_defaults backfills).
"""

from __future__ import annotations

import logging

from copy import deepcopy

from ._consts import (
    ALARM_PROFILE_TO_SEVERITY,
    CAMERA_NET_KEY_DEFAULTS,
    CAMERA_THRESHOLD_KEY_DEFAULTS,
    EVENT_TL_DEFAULTS,
    SERVER_LOCATION_DEFAULTS,
    STORAGE_DEFAULTS,
    SUN_TL_DEFAULTS,
    TELEGRAM_PUSH_DEFAULTS,
    TL_DEFAULT_PROFILES,
    WEATHER_DEFAULTS,
    WEATHER_RETENTION_DEFAULTS,
)
from .defaults import default_camera, window_minutes

log = logging.getLogger(__name__)


def _deep_merge_defaults(target: dict, defaults: dict) -> None:
    """Recursively fill missing keys in `target` from `defaults`.

    Existing user values are NEVER overwritten — only absent keys (and
    nested absent keys inside dicts) are added. Values whose existing
    type is not dict are left as-is even when the default is a dict;
    this protects against stomping on hand-edited overrides.
    """
    if not isinstance(target, dict):
        return
    for key, default_val in defaults.items():
        if isinstance(default_val, dict):
            sub = target.setdefault(key, {})
            if isinstance(sub, dict):
                _deep_merge_defaults(sub, default_val)
        else:
            target.setdefault(key, default_val)


def migrate_camera_defaults(data: dict, base_config: dict) -> None:
    cameras = data.setdefault("cameras", [])
    by_id = {c.get("id"): c for c in cameras}
    # Also index by display name so a seed cam that was renamed by the
    # storage_migration (e.g. "cam-Werkstatt.rechts.oben" →
    # "unknown_unknown_werkstatt_172") isn't blindly re-added under its
    # original id on the next boot. Two cams sharing the same name is
    # already handled elsewhere — this just stops the migration from
    # silently un-doing itself.
    by_name = {(c.get("name") or "").strip().lower(): c for c in cameras if c.get("name")}
    for c in base_config.get("cameras", []):
        base_name = (c.get("name") or "").strip().lower()
        if c["id"] in by_id:
            target = by_id[c["id"]]
        elif base_name and base_name in by_name:
            target = by_name[base_name]
        else:
            cameras.append(default_camera(c))
            continue
        # Only add missing keys; never overwrite user-saved values.
        defaults = default_camera(c)
        for key, val in defaults.items():
            target.setdefault(key, val)
    # The loop above only reaches cameras that also exist in
    # config.yaml — user-added cams never pass through it. THR-1's keys
    # have to land on EVERY camera, so the pass runs on its own below.
    migrate_threshold_keys(data)


def migrate_threshold_keys(data: dict) -> None:
    """THR-1 · additively land the new threshold-related keys.

    Purely additive: `setdefault` per key, so a value the operator
    already stored is never touched. Runs for every camera, including
    ones that only exist in settings.json.

    Chained from migrate_camera_defaults rather than registered as its
    own step in store.load() — the call sequence there belongs to a
    different package's file scope. Order is irrelevant: none of these
    keys is read by another migration.
    """
    touched_cams = 0
    for cam in data.get("cameras", []):
        if not isinstance(cam, dict):
            continue
        added = [k for k in CAMERA_THRESHOLD_KEY_DEFAULTS if k not in cam]
        for key in added:
            cam[key] = deepcopy(CAMERA_THRESHOLD_KEY_DEFAULTS[key])
        # NETZ · same additive rule, separate map. `net_auto` is a
        # boolean whose False is meaningful, so it must never travel
        # through an `or default` merge — setdefault is the only
        # correct operator here.
        net_added = [k for k in CAMERA_NET_KEY_DEFAULTS if k not in cam]
        for key in net_added:
            cam[key] = deepcopy(CAMERA_NET_KEY_DEFAULTS[key])
        if added or net_added:
            touched_cams += 1
    storage = data.setdefault("storage", {})
    if not isinstance(storage, dict):
        storage = {}
        data["storage"] = storage
    for key, val in STORAGE_DEFAULTS.items():
        storage.setdefault(key, val)
    if touched_cams:
        log.info("[migration] threshold-keys: %d Kameras nachgerüstet", touched_cams)


def migrate_schedules(data: dict) -> bool:
    """One-time migration: collapse legacy recording_schedule_* and the
    old alerting-only schedule {enabled,start,end} into one unified
    schedule {enabled, from, to, actions:{record,telegram,hard}}.

    Idempotent — a camera whose schedule already carries the 'actions'
    key is left untouched. Returns True if any cam was migrated so the
    caller can persist the result."""
    migrated = 0
    for cam in data.get("cameras", []):
        sch = cam.get("schedule")
        if isinstance(sch, dict) and "actions" in sch:
            # Already in the new shape; just make sure all sub-keys exist.
            sch.setdefault("from", sch.get("start", "21:00"))
            sch.setdefault("to", sch.get("end", "06:00"))
            acts = sch.setdefault("actions", {})
            acts.setdefault("record", True)
            acts.setdefault("telegram", True)
            acts.setdefault("hard", True)
            continue

        rec_enabled = bool(cam.get("recording_schedule_enabled"))
        rec_start = cam.get("recording_schedule_start", "08:00")
        rec_end = cam.get("recording_schedule_end", "22:00")
        ale_dict = sch if isinstance(sch, dict) else {}
        ale_enabled = bool(ale_dict.get("enabled"))
        ale_start = ale_dict.get("start", "22:00")
        ale_end = ale_dict.get("end", "06:00")

        if not rec_enabled and not ale_enabled:
            new_sched = {
                "enabled": False,
                "from": "21:00",
                "to": "06:00",
                "actions": {"record": True, "telegram": True, "hard": True},
            }
            src = "both-off"
        elif rec_enabled and not ale_enabled:
            new_sched = {
                "enabled": True,
                "from": rec_start,
                "to": rec_end,
                "actions": {"record": True, "telegram": True, "hard": False},
            }
            src = "recording-only"
        elif not rec_enabled and ale_enabled:
            new_sched = {
                "enabled": True,
                "from": ale_start,
                "to": ale_end,
                "actions": {"record": True, "telegram": True, "hard": True},
            }
            src = "alerting-only"
        else:
            # Both active — keep the larger window.
            rec_dur = window_minutes(rec_start, rec_end)
            ale_dur = window_minutes(ale_start, ale_end)
            if rec_dur >= ale_dur:
                f, t = rec_start, rec_end
            else:
                f, t = ale_start, ale_end
            new_sched = {
                "enabled": True,
                "from": f,
                "to": t,
                "actions": {"record": True, "telegram": True, "hard": True},
            }
            src = f"both-on (rec={rec_dur}m ale={ale_dur}m → wider)"

        cam["schedule"] = new_sched
        cam.pop("recording_schedule_enabled", None)
        cam.pop("recording_schedule_start", None)
        cam.pop("recording_schedule_end", None)
        log.info(
            "Schedule-Migration: %s → %s (%s → enabled=%s %s-%s actions=%s)",
            cam.get("id", "?"),
            src,
            f"rec={rec_enabled}/{rec_start}/{rec_end} " f"ale={ale_enabled}/{ale_start}/{ale_end}",
            new_sched["enabled"],
            new_sched["from"],
            new_sched["to"],
            new_sched["actions"],
        )
        migrated += 1
    return migrated > 0


def migrate_class_severity(data: dict) -> None:
    """One-time migration: derive class_severity dict from the legacy
    alarm_profile when class_severity is empty. The legacy alarm_profile
    field stays in storage so older code paths still read it;
    class_severity becomes the new source of truth. Idempotent —
    cameras that already carry a non-empty class_severity dict are
    left untouched.
    """
    migrated = 0
    for cam in data.get("cameras", []):
        if cam.get("class_severity"):
            continue
        profile = (cam.get("alarm_profile") or "soft").strip() or "soft"
        mapping = ALARM_PROFILE_TO_SEVERITY.get(profile, ALARM_PROFILE_TO_SEVERITY["soft"])
        cam["class_severity"] = dict(mapping)
        migrated += 1
        log.info(
            "[migration] class_severity: %s ← alarm_profile=%s → %s",
            cam.get("id", "?"),
            profile,
            mapping,
        )
    if migrated:
        log.info("[migration] class_severity: %d Kameras migriert", migrated)


def migrate_alerting_schedules(data: dict) -> None:
    """One-time migration: derive schedule_notify and schedule_record
    from the legacy schedule.actions structure. The legacy schedule
    field stays in storage but is no longer the source of truth — the
    runtime now reads schedule_notify for Telegram/MQTT gating and
    schedule_record for archive gating.

    Mapping:
      schedule_notify.enabled = legacy.enabled AND actions.telegram
      schedule_notify.from/to = legacy.from/to
      schedule_record.enabled = legacy.enabled AND actions.record
      schedule_record.from/to = legacy.from/to

    Idempotent — cameras that already carry both new schedules are
    left untouched. Empty schedule_notify or schedule_record keys are
    filled in even when the other already exists.
    """
    migrated = 0
    for cam in data.get("cameras", []):
        has_n = isinstance(cam.get("schedule_notify"), dict) and cam["schedule_notify"]
        has_r = isinstance(cam.get("schedule_record"), dict) and cam["schedule_record"]
        if has_n and has_r:
            continue
        sch = cam.get("schedule") or {}
        actions = sch.get("actions") or {}
        sch_enabled = bool(sch.get("enabled"))
        sch_from = sch.get("from") or "21:00"
        sch_to = sch.get("to") or "06:00"
        if not has_n:
            cam["schedule_notify"] = {
                "enabled": sch_enabled and actions.get("telegram", True) is not False,
                "from": sch_from,
                "to": sch_to,
            }
        if not has_r:
            cam["schedule_record"] = {
                "enabled": sch_enabled and actions.get("record", True) is not False,
                "from": sch_from,
                "to": sch_to,
            }
        migrated += 1
        log.info(
            "[migration] alerting-schedule: %s ← legacy=%s → notify=%s record=%s",
            cam.get("id", "?"),
            sch,
            cam["schedule_notify"],
            cam["schedule_record"],
        )
    if migrated:
        log.info("[migration] alerting-schedule: %d Kameras migriert", migrated)


def migrate_timelapse_settings(data: dict) -> None:
    data.setdefault("timelapse_settings", {"global_enabled": False})


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


def migrate_telegram_push_defaults(data: dict) -> None:
    """Additively backfill telegram.push so every key the UI expects exists."""
    tg = data.setdefault("telegram", {})
    push = tg.setdefault("push", {})
    if not isinstance(push, dict):
        push = {}
        tg["push"] = push
    # Lift a hand-edited `telegram.recording_ticker` into the documented
    # `telegram.push.recording_ticker` BEFORE the defaults land. The reader
    # in camera_runtime/_recording/_publish looked one level up from where
    # TELEGRAM_PUSH_DEFAULTS puts the key, so the only way an install could
    # carry a value at the old path was by editing settings.json directly —
    # and that value must survive, not be overwritten by the True default.
    # setdefault keeps it additive; the pop removes the now-dead key so the
    # drift cannot be re-read by anything later.
    legacy_ticker = tg.pop("recording_ticker", None)
    if legacy_ticker is not None:
        push.setdefault("recording_ticker", bool(legacy_ticker))
        log.info("[migration] recording_ticker: telegram → telegram.push verschoben")
    _deep_merge_defaults(push, TELEGRAM_PUSH_DEFAULTS)
    # Backfill night-alert lat/lon from server.location when present —
    # avoids forcing the user to re-enter coordinates already known to
    # the system.
    night = push.get("night_alert") or {}
    srv_loc = (data.get("server", {}) or {}).get("location") or {}
    if night.get("lat") is None and srv_loc.get("lat") is not None:
        night["lat"] = srv_loc.get("lat")
    if night.get("lon") is None and srv_loc.get("lon") is not None:
        night["lon"] = srv_loc.get("lon")


def migrate_server_location_defaults(data: dict) -> None:
    srv = data.setdefault("server", {})
    loc = srv.setdefault("location", {})
    if not isinstance(loc, dict):
        loc = {}
        srv["location"] = loc
    for k, v in SERVER_LOCATION_DEFAULTS.items():
        loc.setdefault(k, v)


def migrate_weather_defaults(data: dict) -> None:
    """Additively backfill the global weather block + per-camera flag."""
    w = data.setdefault("weather", {})
    if not isinstance(w, dict):
        w = {}
        data["weather"] = w
    _deep_merge_defaults(w, WEATHER_DEFAULTS)
    # Per-category retention (Wetter-Wartung) — setdefault-only, so a
    # real install's existing blanket `retention_days` is left exactly
    # as it is; only the new per-category keys are backfilled.
    _deep_merge_defaults(w, WEATHER_RETENTION_DEFAULTS)
    # Make sure every camera carries the opt-in flag in the new shape;
    # existing cameras with handcrafted weather dicts are left alone.
    # The sun_timelapse sub-block is added unconditionally — it's the
    # nested-default backfill the WeatherService relies on at startup.
    for cam in data.get("cameras", []):
        cw = cam.setdefault("weather", {"enabled": False})
        if not isinstance(cw, dict):
            cam["weather"] = {"enabled": False}
            continue
        cw.setdefault("enabled", False)
        sun_tl = cw.setdefault("sun_timelapse", {})
        if isinstance(sun_tl, dict):
            _deep_merge_defaults(sun_tl, SUN_TL_DEFAULTS)
        evt_tl = cw.setdefault("event_timelapse", {})
        if isinstance(evt_tl, dict):
            _deep_merge_defaults(evt_tl, EVENT_TL_DEFAULTS)


# No plausible LPI threshold is anywhere near this. The physical index
# runs 0.2–0.8 J/kg in observed thunderstorms and tops out in the low
# tens; anything at or above 100 can only have come from reading "J/kg"
# as a CAPE-like quantity.
_LPI_WRONG_SCALE_MIN = 100.0


def migrate_thunder_lpi_scale(data: dict) -> None:
    """Correct a thunder threshold left on the CAPE scale.

    `lightning_potential` is the Lightning Potential Index (Lynn & Yair
    2010), a native ICON-D2 field. Its unit is J/kg, which reads like
    CAPE and is nothing like it: observed thunderstorm cases run
    0.2–0.8 J/kg. The shipped default was 1000.0, so the thunder trigger
    could not fire for any storm that has ever existed — and on
    2026-08-28 it did not, through a thunderstorm the operator watched
    with visible lightning.

    This deliberately OVERWRITES an existing value, which the rest of
    this module never does. The justification is narrow and it matters:
    a threshold three orders of magnitude outside its own index's range
    is not a preference the operator expressed, it is a unit error, and
    leaving it in place would mean the additive-merge rule preserves a
    bug forever. The guard is conservative — only values at or above
    100 are touched, so any hand-tuned LPI number survives untouched.
    """
    events = ((data.get("weather") or {}).get("events") or {}).get("thunder")
    if not isinstance(events, dict):
        return
    try:
        current = float(events.get("threshold"))
    except (TypeError, ValueError):
        return
    if current < _LPI_WRONG_SCALE_MIN:
        return
    corrected = float(WEATHER_DEFAULTS["events"]["thunder"]["threshold"])
    events["threshold"] = corrected
    log.warning(
        "[migration] thunder-Schwelle %.1f J/kg lag auf der CAPE-Skala – "
        "korrigiert auf %.2f J/kg (LPI-Bereich 0.2–0.8)",
        current,
        corrected,
    )


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


def migrate_label_thresholds(data: dict) -> None:
    """Rewrite the legacy person threshold default 0.65 → 0.45.

    A live test (user standing arms-out in frame) had Coral score
    person 0.28 and 0.44; both were rejected by the 0.65 floor and
    the user saw "Person wird nicht erkannt". 0.65 was the previous
    LABEL_THRESHOLD_DEFAULTS["person"], i.e. a value that landed
    in storage purely because it was the default at write time, not
    because the operator chose it. We rewrite ONLY that exact 0.65
    value — any other stored threshold (e.g. a deliberately raised
    0.55 or 0.80) is left untouched. Idempotent: cameras already on
    0.45 (or any non-0.65 value) skip the touch path.
    """
    touched = 0
    for cam in data.get("cameras", []):
        thrs = cam.get("label_thresholds")
        if not isinstance(thrs, dict):
            continue
        person = thrs.get("person")
        if not isinstance(person, (int, float)):
            continue
        if abs(float(person) - 0.65) < 1e-9:
            thrs["person"] = 0.45
            touched += 1
    if touched:
        log.info(
            "[migration] label-thresholds: rewrote stale person=0.65 → 0.45 " "on %d Kameras",
            touched,
        )


def migrate_runtime_defaults(data: dict) -> None:
    rt = data.setdefault("runtime", {})
    if not isinstance(rt, dict):
        rt = {}
        data["runtime"] = rt
    rt.setdefault("event_feedback", {})
    rt.setdefault("suppress", {})
    rt.setdefault("system_state", {})
    rt.setdefault("alert_index", {})
    rt.setdefault("last_storage_warn_ts", 0)
    rt.setdefault("last_coral_state", "")


def migrate_rtsp_password_encoding(data: dict) -> None:
    """Percent-encode passwords sitting raw inside stored camera URLs.

    An RTSP password routinely contains ``@``, ``:`` or ``/``. Written raw
    into a URL's userinfo those characters ARE the syntax: ffmpeg reads
    ``rtsp://admin:p@ss@host/x`` as host ``ss`` and refuses the stream
    with "Port missing in uri", so the camera never opens and the live
    tile shows KEIN SIGNAL. The browser used to send an already-encoded
    URL; when the credential-redaction refactor moved URL assembly to the
    server, nothing encoded it any more and every camera whose password
    held a reserved character stopped connecting.

    Rewrites only the userinfo, only when re-encoding actually changes the
    string, and only when the camera has a stored password to put back —
    so a correctly-encoded URL, a credential-free one and a camera with no
    password are all left exactly as they are.
    """
    from ..routes._secrets import CAMERA_URL_KEYS, reencode_url_password

    fixed = 0
    for cam in data.get("cameras") or []:
        if not isinstance(cam, dict):
            continue
        password = cam.get("password") or ""
        if not password:
            continue
        for key in CAMERA_URL_KEYS:
            url = cam.get(key) or ""
            if not url:
                continue
            repaired = reencode_url_password(url, password)
            if repaired != url:
                cam[key] = repaired
                fixed += 1
    if fixed:
        log.info("[migration] %d Kamera-URL(s) mit kodiertem Passwort neu geschrieben", fixed)


#: Canvas sizes the zone editor has ever drawn on, smallest first. The
#: editor sizes its canvas to the snapshot's natural dimensions, and the
#: snapshot is the camera's substream preview — so these are the substream
#: resolutions the Reolinks actually serve, plus the 1280x720 fallback the
#: editor uses when the snapshot fails to load.
_ZONE_CANVASES = ((640, 360), (960, 540), (1280, 720), (1920, 1080), (2560, 1440))


def _infer_zone_canvas(points) -> tuple[int, int] | None:
    """Smallest editor canvas that could hold every point, or ``None``.

    Only ever consulted for a polygon with NO ``source_w``/``source_h``
    stamp, which today is read as 1280x720 by the runtime and as the
    camera's current preview resolution by the browser — two different
    guesses, neither of them recorded. Bounding the points is at least a
    guess made from the data.
    """
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    if not xs or not ys:
        return None
    need_w, need_h = max(xs) + 1, max(ys) + 1
    for w, h in _ZONE_CANVASES:
        if need_w <= w and need_h <= h:
            return w, h
    return None


def migrate_zone_source_space(data: dict) -> None:
    """Stamp the drawing canvas onto polygons that never recorded one.

    THE BUG: ``mask_zones.point_in_poly`` scales a detection's centre into
    the polygon's own space using ``source_w``/``source_h``. Polygons
    drawn before that stamp existed fall back to the hard-coded
    1280x720 canvas — but the Werkstatt zone's own coordinates top out at
    636x356, i.e. it was drawn at 640x360. The gate therefore probed
    y=468 on a polygon that ends at y=356, so EVERY person in the lower
    part of the frame was rejected as "outside applicable zones". A
    security camera that detected a person at 87 % and never reported it.

    Verified against the real data: at the inferred 640x360 the two
    logged 86/87 % person centres land INSIDE, while a genuine 21 %
    detection in the top corner correctly stays outside.

    Deliberately NOT done instead: changing the 1280x720 fallback
    constant. That same constant also governs EXCLUSION MASKS, so moving
    it would shift masks on cameras that work correctly today and could
    open a new blind spot on a security camera. Recording what each
    polygon was actually drawn on is the repair; re-interpreting a shared
    constant is not.
    """
    from ..mask_zones import flatten_poly_points, point_xy

    stamped = 0
    for cam in data.get("cameras") or []:
        if not isinstance(cam, dict):
            continue
        for key in ("zones", "masks"):
            for poly in cam.get(key) or []:
                if not isinstance(poly, dict) or poly.get("source_w") or poly.get("source_h"):
                    continue
                pts = [point_xy(p) for p in flatten_poly_points(poly)]
                canvas = _infer_zone_canvas(pts)
                if not canvas:
                    continue
                poly["source_w"], poly["source_h"] = canvas
                stamped += 1
                log.warning(
                    "[migration] %s: %s ohne Zeichenraum — auf %dx%d gestempelt "
                    "(bitte im Editor prüfen)",
                    cam.get("id"),
                    key,
                    canvas[0],
                    canvas[1],
                )
    if stamped:
        log.warning(
            "[migration] %d Polygon(e) nachgestempelt — vorher wurden sie gegen "
            "1280x720 geprüft und konnten Treffer fälschlich verwerfen",
            stamped,
        )
