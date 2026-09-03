"""Collapsing the legacy recording/alerting schedules into one shape."""

from __future__ import annotations

import logging

from ..defaults import window_minutes

log = logging.getLogger("app.settings.migrations")


def _fill_missing_subkeys(sch: dict) -> None:
    """A schedule already in the new shape: make sure every sub-key
    exists, without disturbing anything the operator has set."""
    sch.setdefault("from", sch.get("start", "21:00"))
    sch.setdefault("to", sch.get("end", "06:00"))
    acts = sch.setdefault("actions", {})
    acts.setdefault("record", True)
    acts.setdefault("telegram", True)
    acts.setdefault("hard", True)


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
            _fill_missing_subkeys(sch)
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
