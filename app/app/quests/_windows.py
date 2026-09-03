"""Quest window vocabulary: when a quest counts, and when it is over.

Three distinct questions, deliberately answered by three functions:

  ``_resolve_window``      is the window open right now, and over what span?
  ``_next_window_start``   when does a seasonal window open next? (preview UI)
  ``_window_logical_end``  after which moment is a STORED entry historical?

The last one is not the ``to`` field of the stored window — that is only
a snapshot of the evaluation timestamp and would mark every window closed
on the next tick.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("app.quests")


def _resolve_window(name: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    """Map a quest window name to a concrete (start_dt, end_dt) pair.

    Returns (None, None) when the window is currently inactive — e.g.
    `april_rolling_week` outside April. The evaluator treats that as
    "skip this quest until the window opens again", so progress freezes
    rather than silently zeroing out.

    Window vocabulary:
      december               — 1.–31. December of the current year
      april_rolling_week     — last 7 days, clamped to April
      year_to_date           — Jan 1 of the current year through now
      current_calendar_month — 1. of the current month through now
                               (rolls automatically on the 1st)
      current_rolling_week   — last 7 days, every day of the year
    """
    year = now.year
    if name == "december":
        if now.month != 12:
            return (None, None)
        return (datetime(year, 12, 1, 0, 0, 0), now)
    if name == "april_rolling_week":
        if now.month != 4:
            return (None, None)
        start = max(datetime(year, 4, 1, 0, 0, 0), now - timedelta(days=7))
        return (start, now)
    if name == "year_to_date":
        return (datetime(year, 1, 1, 0, 0, 0), now)
    if name == "current_calendar_month":
        return (datetime(year, now.month, 1, 0, 0, 0), now)
    if name == "current_rolling_week":
        return (now - timedelta(days=7), now)
    log.warning("[quests] unknown window: %s", name)
    return (None, None)


def _next_window_start(name: str, now: datetime) -> datetime | None:
    """Return the NEXT window-open datetime for ``name`` after ``now``,
    or None when the window is either always active (``year_to_date``,
    ``current_calendar_month``, ``current_rolling_week``) or unknown.

    Used by ``preview_upcoming_quests`` to surface seasonal quests
    before their window opens. We only care about windows that have a
    distinct future "opens at" date the user can plan around — a
    rolling-week window is always-on, so it has no "next" opening."""
    year = now.year
    if name == "december":
        opens = datetime(year, 12, 1, 0, 0, 0)
        if now >= opens:
            opens = datetime(year + 1, 12, 1, 0, 0, 0)
        return opens
    if name == "april_rolling_week":
        opens = datetime(year, 4, 1, 0, 0, 0)
        if now >= datetime(year, 5, 1, 0, 0, 0):
            opens = datetime(year + 1, 4, 1, 0, 0, 0)
        elif now >= opens:
            # We're inside April — the window is currently active, so
            # this quest is on the active pinboard, not the preview.
            return None
        return opens
    return None


def _next_window_close(name: str, opens_at: datetime) -> datetime | None:
    """Return the close datetime corresponding to the next opening of
    ``name``. Used purely for the preview UI's "läuft bis DD.MM." label
    — never feeds the evaluator."""
    if name == "december":
        return datetime(opens_at.year, 12, 31, 23, 59, 59)
    if name == "april_rolling_week":
        return datetime(opens_at.year, 4, 30, 23, 59, 59)
    return None


def _window_logical_end(name: str, stored_from: datetime | None) -> datetime | None:
    """Return the LOGICAL end of a window given the stored start. This
    is the date AFTER which a stored quest is considered "from a past
    period" and eligible for archiving — distinct from the (start, now)
    snapshot the evaluator persists.

      december               → Dec 31 of the stored year
      april_rolling_week     → April 30 of the stored year
      year_to_date           → Dec 31 of the stored year
      current_calendar_month → last day of the stored month
      current_rolling_week   → None (always rolling, never logically closes)
    """
    if stored_from is None:
        return None
    year = stored_from.year
    if name == "december":
        return datetime(year, 12, 31, 23, 59, 59)
    if name == "april_rolling_week":
        return datetime(year, 4, 30, 23, 59, 59)
    if name == "year_to_date":
        return datetime(year, 12, 31, 23, 59, 59)
    if name == "current_calendar_month":
        # last day of month: jump to next month's day 1 minus 1 second
        if stored_from.month == 12:
            next_first = datetime(year + 1, 1, 1, 0, 0, 0)
        else:
            next_first = datetime(year, stored_from.month + 1, 1, 0, 0, 0)
        return next_first - timedelta(seconds=1)
    return None


def _quest_id_with_year(base_id: str, now: datetime, window: str) -> str:
    """Append a window-specific year suffix so each season's quest is its
    own historical entry. December and april windows are anchored to a
    single calendar year; year_to_date is too. All three suffix with the
    current year — we never re-use a completed quest id across years."""
    return f"{base_id}_{now.year}"
