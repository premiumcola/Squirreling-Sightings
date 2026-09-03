"""The one call the rest of the app makes: load, evaluate, archive, save.

Persistence lives in ``routes/sichtungen.py`` (``_load_achievements`` /
``_save_achievements``); this module owns only the ordering and the lock.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ._archive import archive_closed_quests
from ._evaluate import evaluate_quests

log = logging.getLogger("app.quests")


def reevaluate_and_save(now: datetime | None = None, *, is_rollover: bool = False) -> dict:
    """One-call helper: load achievements, evaluate, archive, save,
    return summary. Used by the hourly background job, the daily
    rollover timer, the inline post-event hook, and the manual
    /api/achievements/quests/reevaluate API.

    ``is_rollover`` triggers an extra INFO line summarising the
    archive churn at week/month boundary so the operator sees the
    rotation in `docker logs`.
    """
    from .. import app_state
    from ..routes.sichtungen import (
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
        # Archive any closed-window or catalog-removed entries the eval
        # just produced. archive_closed_quests is idempotent — running
        # twice yields the same dict.
        updated, archived = archive_closed_quests(updated, now=now)
        _save_achievements(updated)
    log.info(
        "[quests] re-evaluated %d quests, %d newly completed, %d archived: %s",
        len(updated.get("quests") or {}),
        len(newly),
        len(archived),
        newly,
    )
    if is_rollover:
        log.info(
            "[quests] rollover: archived=%d new_active=%d",
            len(archived),
            len(updated.get("quests") or {}),
        )
    return {
        "ok": True,
        "evaluated": len(updated.get("quests") or {}),
        "newly_completed": newly,
        "archived": [a["id"] for a in archived],
    }
