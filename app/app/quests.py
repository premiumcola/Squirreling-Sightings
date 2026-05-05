"""Seasonal quests — progress-based achievements layered on the existing
species `achievements.json` file.

Why a separate module:
    The legacy achievement system in `routes/sichtungen.py` is binary
    (species seen yes/no). Quests need a counter, a window, and richer
    criteria (label sets, hour windows, distinct-species counts, weather
    overlap). Putting that next to the species code would either bloat the
    route file or muddy the data shape. Instead, the route file owns
    persistence (`_load_achievements` / `_save_achievements`) and this
    module owns the evaluation logic; the on-disk JSON gains a `quests`
    top-level key alongside the existing per-species entries.

Persistence shape (extends, doesn't break, the existing layout):

    {
      "robin": { "date": ..., "count": 47, ... },          # unchanged
      "quests": {
        "wintervorrat_2026": {
          "id": "wintervorrat_2026",
          "title": "Wintervorrat",
          "icon": "🐿️",
          "description": "50 Eichhörnchen-Sichtungen im Dezember",
          "target": 50,
          "progress": 23,
          "window": {"from": "...", "to": "..."},
          "criteria": {"label": "squirrel"},
          "completed_at": null,
          "notified_at": null
        },
        ...
      }
    }

Evaluation runs at three trigger points (see CLAUDE.md feature doc F09):
    a) inline after every motion event finalize (best-effort, full eval)
    b) hourly background timer in server.py
    c) manual "Re-Eval" button → POST /api/achievements/quests/reevaluate

`evaluate_quests` is idempotent — running it twice in a row produces the
same dict — so trigger (a) and (b) cannot diverge.
"""
from __future__ import annotations

import json as _json_mod
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("app.quests")


# ── Quest catalogue ────────────────────────────────────────────────────────
# Hardcoded by design — V1 has no user-editable quests. Adding a new entry
# here + a window type below is enough to ship one.
QUESTS: list[dict] = [
    {
        "id": "wintervorrat",
        "title": "Wintervorrat",
        "icon": "🐿️",
        "description": "50 Eichhörnchen-Sichtungen im Dezember",
        "target": 50,
        "window": "december",
        "criteria": {"label": "squirrel"},
    },
    {
        "id": "fruehlingschor",
        "title": "Frühlingschor",
        "icon": "🌸",
        "description": "10 verschiedene Vogelarten in einer Aprilwoche",
        "target": 10,
        "window": "april_rolling_week",
        "criteria": {"label": "bird", "count_distinct_species": True},
    },
    {
        "id": "mondtiere",
        "title": "Mondtiere",
        "icon": "🦊",
        "description": "5 Wildtier-Erkennungen zwischen 02:00 und 04:00",
        "target": 5,
        "window": "year_to_date",
        "criteria": {
            "labels": ["fox", "hedgehog", "squirrel"],
            "hour_in": [2, 3],
        },
    },
    {
        "id": "gewitterhueter",
        "title": "Gewitterhüter",
        "icon": "⚡",
        "description": "Sun-Timelapse durch ein Gewitter komplett aufgenommen",
        "target": 1,
        "window": "year_to_date",
        "criteria": {"event_type": "sun_tl_through_thunderstorm"},
    },
    {
        "id": "vollmondnacht",
        "title": "Vollmondnacht",
        "icon": "🌖",
        "description": "Sun-TL bei Vollmond mit ≥3 Wildtier-Sichtungen in derselben Nacht",
        "target": 1,
        "window": "year_to_date",
        "criteria": {"event_type": "sun_tl_full_moon_with_wildlife"},
    },
]

# Wildlife labels used by the "vollmondnacht" night-counter and the
# generic motion criteria ("mondtiere"). Mirrors the COCO-plus-wildlife
# label set the runtime emits today.
_WILDLIFE_LABELS = ("fox", "hedgehog", "squirrel", "marten", "deer")


# ── Window resolver ────────────────────────────────────────────────────────
def _resolve_window(name: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    """Map a quest window name to a concrete (start_dt, end_dt) pair.

    Returns (None, None) when the window is currently inactive — e.g.
    `april_rolling_week` outside April. The evaluator treats that as
    "skip this quest until the window opens again", so progress freezes
    rather than silently zeroing out.
    """
    year = now.year
    if name == "december":
        return (datetime(year, 12, 1, 0, 0, 0),
                datetime(year, 12, 31, 23, 59, 59))
    if name == "april_rolling_week":
        if now.month != 4:
            return (None, None)
        start = max(datetime(year, 4, 1, 0, 0, 0), now - timedelta(days=7))
        return (start, now)
    if name == "year_to_date":
        return (datetime(year, 1, 1, 0, 0, 0), now)
    log.warning("[quests] unknown window: %s", name)
    return (None, None)


def _quest_id_with_year(base_id: str, now: datetime, window: str) -> str:
    """Append a window-specific year suffix so each season's quest is its
    own historical entry. December and april windows are anchored to a
    single calendar year; year_to_date is too. All three suffix with the
    current year — we never re-use a completed quest id across years."""
    return f"{base_id}_{now.year}"


# ── Event matcher ──────────────────────────────────────────────────────────
def _event_matches(ev: dict, criteria: dict) -> bool:
    """Does a motion-event dict match the quest's criteria?

    Supported criteria keys:
      - "label":  single label that must appear in event.labels
      - "labels": list of labels — match if ANY appears in event.labels
      - "hour_in": list of ints (0–23) — match only when the event hour
                   is one of them
      - "event_type": handled separately (in evaluator) — never reaches
                      this matcher
      - "count_distinct_species": handled separately

    `criteria` keys not listed here are ignored.
    """
    ev_labels = set(ev.get("labels", []) or [])
    if "label" in criteria:
        if criteria["label"] not in ev_labels:
            return False
    if "labels" in criteria:
        wanted = set(criteria["labels"] or [])
        if not (wanted & ev_labels):
            return False
    if "hour_in" in criteria:
        try:
            ev_hour = int((ev.get("time") or "")[11:13])
        except ValueError:
            return False
        if ev_hour not in criteria["hour_in"]:
            return False
    return True


def _all_motion_events_in_window(store, start_dt: datetime,
                                 end_dt: datetime, cam_ids: list[str]) -> list[dict]:
    """Pull every motion event across all cameras within the window.

    Done once per evaluation pass and reused for every quest, so the
    expensive disk walk happens at most once per call. limit=10000 is a
    safety bound — even on a busy multi-cam install we never approach
    that within a single year window.
    """
    out: list[dict] = []
    start_iso = start_dt.isoformat(timespec="seconds")
    end_iso = end_dt.isoformat(timespec="seconds")
    for cam_id in cam_ids:
        try:
            evs = store.list_events(cam_id, start=start_iso, end=end_iso, limit=10000)
        except Exception as e:
            log.debug("[quests] list_events(%s) failed: %s", cam_id, e)
            continue
        out.extend(evs)
    return out


# ── Special event-type evaluators ──────────────────────────────────────────
def _evaluate_sun_tl_through_thunderstorm(storage_root: Path,
                                          start_dt: datetime,
                                          end_dt: datetime) -> int:
    """Count sun-timelapse sightings whose capture window overlaps a
    thunderstorm in `weather_history.json`.

    Heuristic: a sample with `lightning_potential > 0` inside the
    sighting's [started_at, ended_at] range is enough. We don't
    require a strict cell-overhead reading — Open-Meteo's lightning
    potential is a cloud-physics index, not radar, so any non-zero
    value during an outdoor 30-minute capture means the user got a
    real thunderstorm timelapse.
    """
    weather_root = storage_root / "weather"
    history_path = storage_root / "weather_history.json"
    if not weather_root.exists() or not history_path.exists():
        return 0
    try:
        history = _json_mod.loads(history_path.read_text(encoding="utf-8"))
        samples = history.get("samples", []) or []
    except Exception:
        return 0

    def _has_lightning_between(t1: datetime, t2: datetime) -> bool:
        for s in samples:
            try:
                ts = datetime.fromisoformat(s.get("ts", ""))
            except ValueError:
                continue
            if not (t1 <= ts <= t2):
                continue
            lp = (s.get("values") or {}).get("lightning_potential")
            if lp is not None and float(lp) > 0:
                return True
        return False

    hits = 0
    for cam_dir in weather_root.iterdir():
        if not cam_dir.is_dir():
            continue
        for evt_dir in cam_dir.iterdir():
            if not evt_dir.is_dir():
                continue
            if not evt_dir.name.startswith("sun_timelapse"):
                continue
            for jf in evt_dir.glob("*.json"):
                try:
                    m = _json_mod.loads(jf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                try:
                    started = datetime.fromisoformat(m.get("started_at", ""))
                    ended = datetime.fromisoformat(m.get("ended_at", "") or m.get("started_at", ""))
                except ValueError:
                    continue
                if not (start_dt <= started <= end_dt):
                    continue
                if _has_lightning_between(started, ended):
                    hits += 1
    return hits


def _evaluate_sun_tl_full_moon_with_wildlife(storage_root: Path,
                                              start_dt: datetime,
                                              end_dt: datetime,
                                              store, cam_ids: list[str]) -> int:
    """Count sun-timelapses captured around a full moon with ≥3
    wildlife motion events on the same calendar day.

    Full-moon test: astral.moon.phase returns a value in [0, 27.99). A
    full moon is at phase ~14, so we accept |phase - 14| <= 1. Cheap
    and forgiving — the user's intent here is "you got a memorable
    full-moon night", not a strict astronomical match.
    """
    try:
        from astral import moon as _astral_moon
    except ImportError:
        return 0
    weather_root = storage_root / "weather"
    if not weather_root.exists():
        return 0
    hits = 0
    for cam_dir in weather_root.iterdir():
        if not cam_dir.is_dir():
            continue
        for evt_dir in cam_dir.iterdir():
            if not evt_dir.is_dir() or not evt_dir.name.startswith("sun_timelapse"):
                continue
            for jf in evt_dir.glob("*.json"):
                try:
                    m = _json_mod.loads(jf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                try:
                    started = datetime.fromisoformat(m.get("started_at", ""))
                except ValueError:
                    continue
                if not (start_dt <= started <= end_dt):
                    continue
                phase = _astral_moon.phase(started.date())
                if abs(phase - 14.0) > 1.0:
                    continue
                # Count wildlife motion events on the same calendar day.
                day_start = started.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                wildlife_count = 0
                for ev in _all_motion_events_in_window(store, day_start, day_end, cam_ids):
                    ev_labels = set(ev.get("labels", []) or [])
                    if ev_labels & set(_WILDLIFE_LABELS):
                        wildlife_count += 1
                        if wildlife_count >= 3:
                            break
                if wildlife_count >= 3:
                    hits += 1
    return hits


# ── Main evaluator ─────────────────────────────────────────────────────────
def evaluate_quests(store, achievements_data: dict,
                    cam_ids: list[str],
                    storage_root: Path,
                    now: datetime | None = None,
                    notify: Callable[[dict], None] | None = None) -> tuple[dict, list[str]]:
    """Re-evaluate every quest against the current event index.

    Args:
        store:               EventStore — used to list motion events.
        achievements_data:   Existing achievements dict (loaded by caller,
                             saved by caller — this fn does NOT touch disk).
        cam_ids:             Every configured camera id; quests aggregate
                             across all of them.
        storage_root:        Path used for weather sightings + history.
        now:                 Override "now" for tests. Defaults to
                             `datetime.now()`.
        notify:              Optional callback(quest_dict) fired exactly
                             once per quest as it transitions to
                             completed (completed_at just set, notified_at
                             still None). The callback is responsible for
                             marking notified_at on the returned dict —
                             we do that here so a caller that fails to
                             persist the dict gets a re-notify on the
                             next eval.

    Returns: (updated_achievements, newly_completed_ids).
    """
    now = now or datetime.now()
    data = dict(achievements_data) if achievements_data else {}
    quests = dict(data.get("quests") or {})
    newly_completed: list[str] = []

    for quest_def in QUESTS:
        window_name = quest_def["window"]
        start_dt, end_dt = _resolve_window(window_name, now)
        qid = _quest_id_with_year(quest_def["id"], now, window_name)
        existing = quests.get(qid) or {}
        # Window inactive (e.g., april_rolling_week in May) — keep any
        # prior progress as-is, don't recount, don't reset.
        if start_dt is None or end_dt is None:
            quests[qid] = {
                **existing,
                "id": qid,
                "title": quest_def["title"],
                "icon": quest_def["icon"],
                "description": quest_def["description"],
                "target": quest_def["target"],
                "progress": existing.get("progress", 0),
                "window": existing.get("window", {"from": None, "to": None}),
                "criteria": quest_def["criteria"],
                "completed_at": existing.get("completed_at"),
                "notified_at": existing.get("notified_at"),
            }
            continue

        criteria = quest_def["criteria"]
        progress = 0

        event_type = criteria.get("event_type")
        if event_type == "sun_tl_through_thunderstorm":
            progress = _evaluate_sun_tl_through_thunderstorm(
                storage_root, start_dt, end_dt,
            )
        elif event_type == "sun_tl_full_moon_with_wildlife":
            progress = _evaluate_sun_tl_full_moon_with_wildlife(
                storage_root, start_dt, end_dt, store, cam_ids,
            )
        else:
            events = _all_motion_events_in_window(store, start_dt, end_dt, cam_ids)
            if criteria.get("count_distinct_species"):
                species_seen: set[str] = set()
                for ev in events:
                    if not _event_matches(ev, criteria):
                        continue
                    sp = (ev.get("bird_species") or "").strip()
                    if sp:
                        species_seen.add(sp.lower())
                progress = len(species_seen)
            else:
                for ev in events:
                    if _event_matches(ev, criteria):
                        progress += 1

        progress = min(progress, quest_def["target"])
        was_completed = bool(existing.get("completed_at"))
        completed_at = existing.get("completed_at")
        if not was_completed and progress >= quest_def["target"]:
            completed_at = now.isoformat(timespec="seconds")
            newly_completed.append(qid)

        quests[qid] = {
            "id": qid,
            "title": quest_def["title"],
            "icon": quest_def["icon"],
            "description": quest_def["description"],
            "target": quest_def["target"],
            "progress": progress,
            "window": {
                "from": start_dt.isoformat(timespec="seconds"),
                "to": end_dt.isoformat(timespec="seconds"),
            },
            "criteria": criteria,
            "completed_at": completed_at,
            "notified_at": existing.get("notified_at"),
        }

    # Notification pass — call the callback for every quest that just
    # completed AND hasn't been notified yet. We mark notified_at here
    # so a successful caller-save persists it; if the caller crashes
    # before writing, the next eval re-fires.
    if notify:
        for qid in list(quests.keys()):
            q = quests[qid]
            if q.get("completed_at") and not q.get("notified_at"):
                try:
                    notify(q)
                    q["notified_at"] = now.isoformat(timespec="seconds")
                except Exception as e:
                    log.warning("[quests] notify callback failed for %s: %s", qid, e)

    data["quests"] = quests
    return data, newly_completed


def reevaluate_and_save(now: datetime | None = None) -> dict:
    """One-call helper: load achievements, evaluate, save, return summary.

    Used by the hourly background job and the manual reevaluate API.
    Lives here so both call sites share the lock + telegram-notify wiring.
    """
    from . import app_state
    from .routes.sichtungen import (
        _ach_lock,
        _load_achievements,
        _save_achievements,
    )

    settings = app_state.settings
    storage_root = app_state.storage_root
    if settings is None or storage_root is None:
        return {"ok": False, "error": "app_state not initialised"}
    cams = settings.export_effective_config(app_state.base_cfg).get("cameras", []) or []
    cam_ids = [c["id"] for c in cams if c.get("id")]

    def _notify(q: dict):
        tg = app_state.telegram_service
        if tg is None or not getattr(tg, "enabled", False):
            return
        send = getattr(tg, "send_quest_completed", None)
        if callable(send):
            send(q)

    with _ach_lock:
        existing = _load_achievements()
        updated, newly = evaluate_quests(
            store=app_state.store,
            achievements_data=existing,
            cam_ids=cam_ids,
            storage_root=storage_root,
            now=now,
            notify=_notify,
        )
        _save_achievements(updated)
    log.info("[quests] re-evaluated %d quests, %d newly completed: %s",
             len(updated.get("quests") or {}), len(newly), newly)
    return {"ok": True, "evaluated": len(updated.get("quests") or {}),
            "newly_completed": newly}
