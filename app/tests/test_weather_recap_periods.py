"""HYG · a quarterly recap must cover its own quarter and nothing else.

`_recap_definitions` built `period_end` with the usual "day 28 + 4 days,
then step back to the last day of the month" idiom — but only the first
half of it. `date(2026, 3, 28) + 4d` is 1 April, and the trim block
underneath then re-derived "last day of *that* month" and landed on
30 April. The comment on the line called itself `# last day of month,
sloppy`; the trim block below it was written to clean that up and
instead cemented it.

The value is not cosmetic. It is written into the recap manifest
(`_recaps.py` · `"period_end": r["period_end"].isoformat()`) and read
back by `library/_weather_readers.py` as the end of the feed window, so
a Q1 recap was dated into April and answered a `since=2026-04-01` query
as though it covered a month belonging to Q2. `_collect_recap_candidates`
also swept the same month twice — harmless only because the job fires on
the last Sunday of March, when April is still empty.

Pure arithmetic over `_recap_definitions`. No storage, no scheduler.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.weather_service._recaps import RecapsMixin  # noqa: E402


class _Svc(RecapsMixin):
    """_recap_definitions touches no instance state; the mixin needs a
    body only because it is a mixin."""


def _defs(year: int) -> dict[str, dict]:
    return {r["period_id"]: r for r in _Svc()._recap_definitions(year)}


def test_a_quarter_ends_on_the_last_day_of_its_own_quarter():
    d = _defs(2026)
    assert d["q1_2026"]["period_end"] == date(2026, 3, 31)
    assert d["q2_2026"]["period_end"] == date(2026, 6, 30)
    assert d["q3_2026"]["period_end"] == date(2026, 9, 30)
    assert d["q4_2026"]["period_end"] == date(2026, 12, 31)


def test_the_year_recap_spans_the_whole_calendar_year():
    y = _defs(2026)["year_2026"]
    assert y["period_start"] == date(2026, 1, 1)
    assert y["period_end"] == date(2026, 12, 31)


def test_quarters_tile_the_year_without_gap_or_overlap():
    """Two recaps claiming the same day is what sent a Q1 manifest into
    April. Walk the four quarters end-to-start across three years so a
    leap year and a 30-day quarter-end are both covered."""
    from datetime import timedelta

    for year in (2024, 2026, 2027):
        d = _defs(year)
        quarters = [d[f"q{q}_{year}"] for q in (1, 2, 3, 4)]
        assert quarters[0]["period_start"] == date(year, 1, 1)
        assert quarters[-1]["period_end"] == date(year, 12, 31)
        for earlier, later in zip(quarters, quarters[1:]):
            assert earlier["period_end"] < later["period_start"], (
                f"{year}: {earlier['period_id']} runs past " f"{later['period_id']}'s start"
            )
            assert (
                earlier["period_end"] + timedelta(days=1) == later["period_start"]
            ), f"{year}: gap between {earlier['period_id']} and {later['period_id']}"


def test_every_period_end_is_a_real_month_end():
    """The failure mode was an end date one month past the quarter, which
    still *looked* like a month end. Assert the stronger property: the
    day after every period_end is the first of a month."""
    from datetime import timedelta

    for year in (2025, 2026):
        for r in _Svc()._recap_definitions(year):
            nxt = r["period_end"] + timedelta(days=1)
            assert nxt.day == 1, f"{r['period_id']} ends mid-month on {r['period_end']}"
