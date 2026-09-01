"""Periodic maintenance loops carved out of ``server.py``.

Each function moved verbatim; references to server.py module-level
globals (``store``, ``base_cfg``, ``runtimes``, ``settings``,
``weather_service``, ``telegram_service``) flow through
:mod:`app_state` instead. The heartbeat shares timing primitives
with the shutdown bilanz, so ``_BOOT_TS`` / ``_format_uptime`` /
``_disk_free_gb_cached`` live in :mod:`lifecycle` and are imported
here rather than duplicated.
"""

from __future__ import annotations

import logging
import threading
import time

from . import app_state
from .lifecycle import _BOOT_TS, _disk_free_gb_cached, _format_uptime
from .storage_retention import nightly_window


#: Fallback when neither layer carries a usable ``retention_days``.
DEFAULT_RETENTION_DAYS = 14


def _storage_layer(source, key):
    """``storage.<key>`` out of one config layer, or None."""
    if isinstance(source, dict):
        section = source.get("storage")
        if isinstance(section, dict) and section.get(key) is not None:
            return section[key]
    return None


def _storage_setting(key: str, fallback):
    """``settings.json`` first, ``config.yaml`` second — the resolution
    order the UI implies. Read-only, so the additive-merge rule holds."""
    for source in (getattr(app_state.settings, "data", None), app_state.base_cfg):
        value = _storage_layer(source, key)
        if value is not None:
            return value
    return fallback


def _days(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def resolve_retention_days(override=None) -> int:
    """The retention window actually in force.

    The nightly sweep used to read ``config.yaml`` only, while the
    Aufbewahrung slider writes ``settings.json`` — so the number on
    screen was not the number being enforced, and moving the slider
    changed nothing except the manual button. Both callers now come
    through here.

    ``override`` is honoured whenever it is given, including ``0``. The
    old ``override or …`` swallowed an explicit zero and fell back to
    the configured window, which hid the one value the sweep must
    refuse outright instead of quietly reinterpreting.
    """
    if override is not None:
        return _days(override, DEFAULT_RETENTION_DAYS)
    return _days(_storage_setting("retention_days", DEFAULT_RETENTION_DAYS), DEFAULT_RETENTION_DAYS)


def config_retention_days() -> int:
    """The window ``config.yaml`` asks for — i.e. what the nightly sweep
    enforced before ``settings.json`` entered the resolution order. It is
    the baseline the widening guard measures a change against on an
    install that has never recorded one."""
    return _days(_storage_layer(app_state.base_cfg, "retention_days"), DEFAULT_RETENTION_DAYS)


def auto_cleanup_enabled() -> bool:
    """``storage.auto_cleanup_enabled`` — persisted, validated, echoed
    back to the UI, and until now read by nothing at all: the toggle was
    decorative and the sweep ran regardless. Defaults to on so an
    install that never touched the switch keeps its current behaviour."""
    return bool(_storage_setting("auto_cleanup_enabled", True))


def _row_days(key: str) -> int:
    """Resolved window of one Mediathek-Verwaltung row, by catalog key."""
    from .retention_catalog import RETENTION_ROWS, resolve_days

    row = next(r for r in RETENTION_ROWS if r.key == key)
    return resolve_days(row)


def _row_runtime_key(key: str) -> str:
    from .retention_catalog import RETENTION_ROWS

    return next(r for r in RETENTION_ROWS if r.key == key).runtime_key


def _sweep_motion_clips(log) -> None:
    # `nightly_window` is the guard between "the slider says 7" and "the
    # unattended sweep deletes everything older than 7 tonight". A
    # narrower window is announced and deferred until the operator
    # confirms it by saving the panel (or with "Jetzt bereinigen").
    retention = nightly_window(resolve_retention_days(), config_retention_days())
    removed = app_state.store.cleanup_old(retention)
    if removed:
        log.info("[storage] Removed %d old event files (>%dd)", removed, retention)


def _sweep_camera_timelapses(log) -> None:
    """Kamera-Timelapses. Off unless the operator set a window — the
    category was exempt from every sweep until this row existed, so 0
    (nie löschen) short-circuits BEFORE the widening guard, which would
    otherwise hand back a previously-enforced window for a row that has
    just been switched off."""
    from .timelapse_retention import sweep_camera_timelapses

    resolved = _row_days("camera_timelapses")
    if resolved <= 0:
        return
    window = nightly_window(resolved, resolved, key=_row_runtime_key("camera_timelapses"))
    retired = sweep_camera_timelapses(app_state.store, window)
    if retired:
        log.info("[timelapse] %d Timelapse-Dateien in den Papierkorb verschoben", retired)


def _sweep_trash(log) -> None:
    """trash.cleanup_expired() shipped with the docstring "wire into the
    existing daily maintenance cron in a follow-up commit" — that commit
    never landed, so storage/.trash grew unbounded and only emptied via a
    manual POST /api/trash/empty (11 GB of May entries were found once).
    This is that follow-up.

    Deliberately NOT gated on auto_cleanup_enabled: the trash holds
    content the operator already deleted, under its own documented grace
    period. Freezing it with the archive-retention switch would turn
    "keep my recordings longer" into "never reclaim deleted space", which
    is not what that toggle says.

    It IS gated on the widening guard, because a shortened grace period
    hard-deletes the last copy of files the operator may still want back.
    """
    from .trash import _DEFAULT_GRACE_DAYS, cleanup_expired

    grace = nightly_window(
        _row_days("trash_grace"), _DEFAULT_GRACE_DAYS, key=_row_runtime_key("trash_grace")
    )
    purged = cleanup_expired(grace)
    if purged:
        log.info("[storage] Trash: %d expired entries purged (>%dd)", purged, grace)


def _sweep_bird_species(log) -> None:
    """Bounded catch-up pass: fills `bird_species` on already-archived
    events whose live classifier crop never ran or never scored high
    enough — see bird_species_backfill.py for the full rationale.

    Piggybacks on this existing daily timer rather than a new thread:
    the operator explicitly framed this as non-realtime, so once a day
    is plenty for passive catch-up. A manual "Vogelarten nachträglich
    bestimmen" trigger (POST /api/bird-species/backfill, routes/
    sichtungen.py) covers "I just installed the model, don't make me
    wait until tonight".

    NOT gated on auto_cleanup_enabled — this sweep only ever ADDS a
    field to an existing event, it never deletes anything, so it has
    nothing to do with that toggle's contract.
    """
    from .bird_species_backfill import (
        build_backfill_classifier,
        dossier_hook_for,
        sweep_bird_species_backfill,
    )

    classifier = build_backfill_classifier(app_state.get_effective_config())
    if not classifier.available:
        return
    cams = app_state.get_effective_config().get("cameras", []) or []
    cam_ids = [c["id"] for c in cams if c.get("id")]
    result = sweep_bird_species_backfill(
        app_state.store,
        app_state.storage_root,
        classifier,
        cam_ids,
        dossier_hook=dossier_hook_for(app_state.bird_dossiers),
    )
    if result["changed"]:
        log.info(
            "[det] bird backfill: %d/%d archived events stamped with a species",
            result["changed"],
            result["examined"],
        )


def _run_daily_cleanup():
    log = logging.getLogger(__name__)
    if not auto_cleanup_enabled():
        log.info("[storage] autoclean deaktiviert (storage.auto_cleanup_enabled) — übersprungen")
    else:
        for sweep in (_sweep_motion_clips, _sweep_camera_timelapses):
            try:
                sweep(log)
            except Exception as e:
                log.warning("[storage] Failed: %s", e)
    try:
        _sweep_trash(log)
    except Exception as e:
        log.warning("[storage] Trash cleanup failed: %s", e)
    try:
        _sweep_bird_species(log)
    except Exception as e:
        log.warning("[det] bird backfill sweep failed: %s", e)
    t = threading.Timer(86400, _run_daily_cleanup)
    t.daemon = True
    t.start()


def _run_hourly_quest_eval():
    """Trigger (b) for the F09 quest system: hourly full re-evaluation.

    The motion-finalize hook (trigger a) covers the common case, but
    this safety net catches drift — e.g. when events get deleted from
    the archive or when a window-boundary tick crosses a quest's
    `from`/`to`. Idempotent; runs detached.
    """
    import threading as _thr

    try:
        from .quests import reevaluate_and_save

        reevaluate_and_save()
    except Exception as e:
        logging.getLogger(__name__).warning("[quests] hourly eval failed: %s", e)
    t = _thr.Timer(3600, _run_hourly_quest_eval)
    t.daemon = True
    t.start()


def _seconds_until_rollover_check() -> float:
    """Seconds from now until the next 00:05 local-time tick. The
    rollover timer fires once per day at that offset (5 min past
    midnight) so the date has fully advanced before we check whether
    today is Monday / day-of-month-1."""
    import time as _time

    now = _time.localtime()
    # Build a struct_time for tomorrow at 00:05.
    tomorrow_secs = _time.mktime(now) + 86400
    target = _time.localtime(tomorrow_secs)
    target_t = _time.struct_time(
        (
            target.tm_year,
            target.tm_mon,
            target.tm_mday,
            0,
            5,
            0,
            target.tm_wday,
            target.tm_yday,
            target.tm_isdst,
        )
    )
    target_secs = _time.mktime(target_t)
    return max(60.0, target_secs - _time.mktime(now))


def _run_daily_quest_rollover_check():
    """Daily wake-up that checks whether today is a week-start
    (Monday) or month-start (day-of-month == 1). When either is
    true we run a full re-evaluation with ``is_rollover=True`` so the
    archive sweep + rollover log line happen at that boundary. On
    every other day this is a 1-line check and re-arm — cheap.

    Runs in addition to the hourly job; the hourly catches drift
    BETWEEN rollovers, the daily handles the rollover itself."""
    import threading as _thr
    from datetime import datetime as _dt

    try:
        today = _dt.now()
        is_week_start = today.weekday() == 0  # Monday
        is_month_start = today.day == 1
        if is_week_start or is_month_start:
            from .quests import reevaluate_and_save

            reevaluate_and_save(is_rollover=True)
    except Exception as e:
        logging.getLogger(__name__).warning(
            "[quests] daily rollover check failed: %s",
            e,
        )
    t = _thr.Timer(_seconds_until_rollover_check(), _run_daily_quest_rollover_check)
    t.daemon = True
    t.start()


def _heartbeat_emit():
    """Single periodic [heartbeat] line that summarises every subsystem in
    one row. Reuses values already exposed elsewhere (rt.status(), the
    weather runtime poll ts, the polling status). When something is
    unhealthy, the line escalates to WARNING so the rate-limit filter
    coalesces repeats without losing the signal."""
    log = logging.getLogger("app.app.heartbeat")
    parts = [f"uptime={_format_uptime(time.time() - _BOOT_TS)}"]
    unhealthy = False
    # Camera roster
    cam_bits = []
    cams_iter = list(app_state.runtimes.items())
    cam_bits_count = len(cams_iter)
    for cam_id, rt in cams_iter:
        try:
            st = rt.status() or {}
        except Exception:
            st = {}
        name = (st.get("name") or cam_id).split()[0]  # one word per cam keeps the line short
        if st.get("status") in ("active", "starting"):
            fps = st.get("preview_fps") or 0
            r24 = st.get("reconnect_count_24h", 0)
            cam_bits.append(f"{name} {fps:.0f}fps r24h={r24}")
        else:
            age = st.get("frame_age_s")
            age_str = f"{int(age) // 60}m" if isinstance(age, (int, float)) else "?"
            cam_bits.append(f"{name} OFFLINE (last frame {age_str} ago)")
            unhealthy = True
    parts.append(f"cams={cam_bits_count} ({', '.join(cam_bits) if cam_bits else '—'})")
    # Weather
    try:
        last_iso = app_state.settings.runtime_get("weather_last_poll_ts")
        if last_iso:
            age_min = int((time.time() - float(last_iso)) / 60)
            if age_min < 15:
                wpart = f"weather=ok (last poll {age_min}m"
            else:
                wpart = f"weather=stale (last poll {age_min}m"
                unhealthy = True
            # Active events from weather_service.status()
            active = []
            try:
                if app_state.weather_service:
                    cur = (app_state.weather_service.status() or {}).get("current_state") or {}
                    from .weather_service import EVENT_LABEL_DE as _W_LBL

                    active = [_W_LBL.get(k, k) for k, on in cur.items() if on]
            except Exception:
                pass
            wpart += f", active={', '.join(active) if active else 'keine'})"
            parts.append(wpart)
        else:
            parts.append("weather=no-poll-yet")
    except Exception:
        pass
    # Coral inference avg
    coral_avgs = []
    for _id, rt in cams_iter:
        try:
            v = (rt.status() or {}).get("inference_avg_ms")
        except Exception:
            v = None
        if isinstance(v, (int, float)) and v > 0:
            coral_avgs.append(v)
    if coral_avgs:
        parts.append(f"coral={sum(coral_avgs) / len(coral_avgs):.0f}ms")
        # Break that average into its cost centres — a rising total means
        # nothing on its own, but "invoke steady, wait climbing" points
        # straight at lock contention between the camera threads.
        for _id, rt in cams_iter:
            try:
                bd = (rt.status() or {}).get("inference_breakdown_ms") or {}
            except Exception:
                bd = {}
            if bd.get("samples"):
                parts.append(
                    f"det[pre={bd['pre']:.0f} wait={bd['wait']:.0f} "
                    f"inv={bd['invoke']:.0f} post={bd['post']:.0f}]ms"
                )
                break
    # M2 · tile-rescue effectiveness across all cameras. A permanent 0/0
    # means roi_mode is off everywhere and the small-object rescue is
    # inert; hits well below attempts means it fires but rarely helps.
    roi_att = roi_hit = 0
    for _id, rt in cams_iter:
        try:
            st = rt.status() or {}
        except Exception:
            continue
        roi_att += int(st.get("roi_rescue_attempts") or 0)
        roi_hit += int(st.get("roi_rescue_hits") or 0)
    if roi_att:
        parts.append(f"roi_rescue={roi_hit}/{roi_att}")
    # Disk
    free_gb = _disk_free_gb_cached()
    if free_gb < 10:
        parts.append(f"disk={free_gb:.1f}GB free  ⚠")
        unhealthy = True
    elif free_gb < 25:
        parts.append(f"disk={free_gb:.0f}GB free")
        unhealthy = True
    else:
        parts.append(f"disk={free_gb:.0f}GB free")
    # Telegram polling
    try:
        ps = app_state.telegram_service.get_polling_status() if app_state.telegram_service else {}
    except Exception:
        ps = {}
    pstate = ps.get("state", "?")
    if pstate == "active":
        parts.append(f"tg=polling {ps.get('since_seconds', 0) // 60}m")
    else:
        parts.append(f"tg={pstate}")
        unhealthy = True
    # Emit
    msg = "[heartbeat] " + " · ".join(parts)
    if unhealthy:
        log.warning(msg)
    else:
        log.info(msg)
    # Re-arm.
    t = threading.Timer(300.0, _heartbeat_emit)
    t.daemon = True
    t.start()
