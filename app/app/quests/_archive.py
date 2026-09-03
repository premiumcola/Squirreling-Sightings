"""Retiring quests whose window is over, and previewing the ones ahead.

Both sides of the pinboard's edges: ``archive_closed_quests`` takes an
entry off it once its window is historical, ``preview_upcoming_quests``
announces a seasonal quest before its window opens.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ._catalogue import QUESTS
from ._windows import _next_window_close, _next_window_start, _resolve_window, _window_logical_end

log = logging.getLogger("app.quests")


def _base_id(qid: str) -> str:
    """Strip the year suffix (``wintervorrat_2026`` → ``wintervorrat``)
    so a stored id can be compared to the catalogue's base ids."""
    base_id = qid.rsplit("_", 1)[0]
    try:
        int(qid.rsplit("_", 1)[-1])
    except ValueError:
        base_id = qid  # no year suffix — use the whole id
    return base_id


def _archive_reason(qid: str, q: dict, catalogue: dict, now: datetime) -> str | None:
    """Why this entry should leave the pinboard, or None to keep it."""
    base_id = _base_id(qid)
    if base_id not in catalogue:
        return "catalog_removed"
    # A window is considered logically closed when `now` is past the
    # END-of-period date (Dec 31 / last-of-month / etc.). The stored
    # {from, to} pair is just a snapshot — the `to` field always equals
    # the eval timestamp and would incorrectly mark every window as
    # closed-on-next-tick.
    stored_from_str = (q.get("window") or {}).get("from")
    try:
        stored_from = datetime.fromisoformat(stored_from_str) if stored_from_str else None
    except ValueError:
        stored_from = None
    logical_end = _window_logical_end(catalogue[base_id]["window"], stored_from)
    if logical_end is not None and now > logical_end:
        return "window_closed_incomplete"
    return None


def _summarise(qid: str, q: dict, progress: int, reason: str) -> dict:
    """The record ``reevaluate_and_save`` logs for one archived quest."""
    return {
        "id": qid,
        "title": q.get("title"),
        "progress": progress,
        "target": q.get("target"),
        "window": q.get("window"),
        "archived_reason": reason,
    }


def archive_closed_quests(
    achievements_data: dict,
    now: datetime | None = None,
) -> tuple[dict, list[dict]]:
    """Move window-closed quests with progress > 0 to ``quests_archive``;
    drop window-closed quests with progress == 0 silently.

    Rules (applied to every quest in ``data["quests"]``):
      * ``completed_at`` set → leave alone (the 30-day pinboard rule in
        the frontend handles eventual disappearance).
      * Catalog entry no longer exists (id base not in QUESTS):
          - progress > 0 → archive, reason ``catalog_removed``
          - progress == 0 → drop
      * Window's `to` field is in the past AND quest not completed:
          - progress > 0 → archive, reason ``window_closed_incomplete``
          - progress == 0 → drop

    Returns ``(updated_data, archived_summaries)`` where each summary is
    ``{id, title, progress, target, window, archived_reason}`` — the
    caller (reevaluate_and_save) logs them.
    """
    now = now or datetime.now()
    data = dict(achievements_data) if achievements_data else {}
    quests = dict(data.get("quests") or {})
    archive = dict(data.get("quests_archive") or {})
    archived_summaries: list[dict] = []
    catalogue = {q["id"]: q for q in QUESTS}

    for qid, q in list(quests.items()):
        if q.get("completed_at"):
            continue
        reason = _archive_reason(qid, q, catalogue, now)
        if reason is None:
            continue

        progress = int(q.get("progress") or 0)
        # Pop from active quests in either case.
        quests.pop(qid, None)
        if progress <= 0:
            log.debug("[quests] dropped %s (progress=0, reason=%s)", qid, reason)
            continue
        archive[qid] = {
            **q,
            "archived_at": now.isoformat(timespec="seconds"),
            "archived_reason": reason,
        }
        archived_summaries.append(_summarise(qid, q, progress, reason))
        log.info(
            "[quests] archived %s (%d/%s) reason=%s window=%s..%s",
            qid,
            progress,
            q.get("target"),
            reason,
            (q.get("window") or {}).get("from"),
            (q.get("window") or {}).get("to"),
        )

    data["quests"] = quests
    data["quests_archive"] = archive
    return data, archived_summaries


def preview_upcoming_quests(
    now: datetime | None = None,
    horizon_days: int = 60,
) -> list[dict]:
    """Walk QUESTS and return the entries whose NEXT window opens within
    ``horizon_days``. Skips quests whose current window is already active
    (those are on the active pinboard, not the preview). Result is
    sorted soonest-first."""
    now = now or datetime.now()
    horizon = now + timedelta(days=int(horizon_days))
    out: list[dict] = []
    for q in QUESTS:
        # Quests whose window resolves to a concrete (start, end) at
        # `now` are already active — skip from the preview.
        start_now, _end_now = _resolve_window(q["window"], now)
        if start_now is not None:
            continue
        opens_at = _next_window_start(q["window"], now)
        if opens_at is None or opens_at > horizon:
            continue
        closes_at = _next_window_close(q["window"], opens_at)
        out.append(
            {
                "id": q["id"],
                "title": q["title"],
                "icon": q["icon"],
                "description": q["description"],
                "opens_at": opens_at.isoformat(timespec="seconds"),
                "closes_at": closes_at.isoformat(timespec="seconds") if closes_at else None,
                "opens_in_days": max(0, (opens_at - now).days),
            }
        )
    out.sort(key=lambda x: x["opens_at"])
    return out
