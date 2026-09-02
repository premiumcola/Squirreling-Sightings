"""A closed monthly quest window must be archived, not overwritten.

Four of the seven catalogue quests (``vogelvielfalt``, ``goldene_stunde``,
``stammgast``, ``morgenrunde``) use the ``current_calendar_month`` window.

``_window_logical_end`` has a dedicated branch for that window — it
computes the last second of the STORED month, which only makes sense if
a month-old entry is meant to be archived on the 1st. But the quest id
carries the YEAR alone (``_quest_id_with_year`` → ``<base>_<year>``), so
in April the evaluator writes April's window and progress straight over
the March entry under the same key. ``reevaluate_and_save`` then runs
``archive_closed_quests`` on the already-overwritten dict, which now
reads a window that opened yesterday and is plainly still open.

Net effect: on every 1st of the month, four of seven quests lose the
previous month's progress silently, and the ``current_calendar_month``
branch of ``_window_logical_end`` is unreachable in production.

``current_rolling_week`` is deliberately excluded — its logical end is
documented as None ("always rolling, never logically closes").
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.quests import (  # noqa: E402
    QUESTS,
    archive_closed_quests,
    evaluate_quests,
)


class _EmptyStore:
    """EventStore stand-in with no events — progress always evaluates 0."""

    def list_events(self, cam_id, start=None, end=None, limit=0):
        return []


_MONTHLY = [q for q in QUESTS if q["window"] == "current_calendar_month"]


def _march_progress(qid: str, progress: int = 5) -> dict:
    """Achievements blob as it stands at the end of March 2026."""
    return {
        "quests": {
            qid: {
                "id": qid,
                "title": "Vogelvielfalt",
                "icon": "bird",
                "description": "",
                "target": 10,
                "progress": progress,
                "window": {"from": "2026-03-01T00:00:00", "to": "2026-03-31T23:00:00"},
                "criteria": {},
                "completed_at": None,
                "notified_at": None,
            }
        }
    }


def test_the_catalogue_still_has_monthly_quests():
    """Guards the premise — if the catalogue drops them this test is moot."""
    assert _MONTHLY, "no current_calendar_month quests left in the catalogue"


def test_march_progress_survives_the_first_of_april():
    """Run the production order — evaluate, then archive — across the
    boundary and look for March's 5 in either the active set or the
    archive. It must not simply vanish."""
    qid = f"{_MONTHLY[0]['id']}_2026"
    data = _march_progress(qid)
    now = datetime(2026, 4, 2, 9, 0, 0)

    updated, _newly = evaluate_quests(
        store=_EmptyStore(),
        achievements_data=data,
        cam_ids=["cam-a"],
        storage_root=Path("/nonexistent"),
        now=now,
    )
    updated, archived = archive_closed_quests(updated, now=now)

    archive = updated.get("quests_archive") or {}
    active = updated.get("quests") or {}
    march = [
        q
        for q in list(archive.values()) + list(active.values())
        if ((q.get("window") or {}).get("from") or "").startswith("2026-03")
    ]
    assert march, (
        "March's window is gone from both the active set and the archive — "
        f"the month rollover destroyed it (archived={[a['id'] for a in archived]})"
    )
    assert march[0].get("progress") == 5, "March's progress was reset instead of preserved"


def _tick(data: dict, now: datetime) -> tuple[dict, list[dict]]:
    """One production pass: evaluate, then archive, as
    ``reevaluate_and_save`` does."""
    updated, _newly = evaluate_quests(
        store=_EmptyStore(),
        achievements_data=data,
        cam_ids=["cam-a"],
        storage_root=Path("/nonexistent"),
        now=now,
    )
    return archive_closed_quests(updated, now=now)


def test_a_completed_month_does_not_freeze_on_its_old_window():
    """``archive_closed_quests`` deliberately skips anything carrying
    ``completed_at``. Holding a completed entry back for the archiver
    would therefore pin it to a window that never moves again."""
    qid = f"{_MONTHLY[0]['id']}_2026"
    data = _march_progress(qid, progress=10)
    data["quests"][qid]["completed_at"] = "2026-03-20T12:00:00"
    now = datetime(2026, 4, 2, 9, 0, 0)

    rolled, _ = _tick(data, now)
    entry = (rolled.get("quests") or {}).get(qid)
    assert entry is not None, f"{qid} vanished — a completed quest must stay on the pinboard"
    frm = (entry.get("window") or {}).get("from") or ""
    assert frm.startswith("2026-04"), f"{qid} is frozen on its March window ({frm!r})"
    assert entry.get("completed_at") == "2026-03-20T12:00:00", "the completion was lost"


def test_the_new_month_starts_clean_on_the_next_pass():
    """The closed month leaves the active set on the rollover pass, and
    the pass after it opens April under the same id."""
    qid = f"{_MONTHLY[0]['id']}_2026"
    now = datetime(2026, 4, 2, 9, 0, 0)

    rolled, _ = _tick(_march_progress(qid), now)
    assert qid not in (rolled.get("quests") or {}), "the closed month is still on the pinboard"

    settled, _ = _tick(rolled, now)
    entry = (settled.get("quests") or {}).get(qid)
    assert entry is not None, f"{qid} never came back for the new month"
    frm = (entry.get("window") or {}).get("from") or ""
    assert frm.startswith("2026-04"), f"{qid} did not open April's window ({frm!r})"
    assert entry.get("progress") == 0, "April opened carrying March's count"
