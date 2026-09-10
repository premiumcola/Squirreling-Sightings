"""The daily maintenance pass runs AT NIGHT, not 24 h after boot.

„Den service lauf nachts hast du vergessen??"

It re-armed with a flat ``threading.Timer(86400, …)``, which anchors the
slot to whenever the process last started rather than to a time of day.
A container brought up at 22:00 therefore ran its retention sweep, its
bird-species backfill and its Feinspur catch-up at 22:00 every day —
the busiest hour on these cameras — and every redeploy moved the slot
again. The quest rollover next door has always targeted a wall clock;
this pins that both are computed by ONE helper (CLAUDE.md's
no-parallel-implementations rule) and that the maintenance one aims at
night.
"""

from __future__ import annotations

import time

from app.maintenance import (
    DAILY_MAINTENANCE_AT,
    _seconds_until_rollover_check,
    seconds_until_local,
)


def _at(delay_s: float) -> time.struct_time:
    """The local time a timer armed with `delay_s` would fire at."""
    return time.localtime(time.time() + delay_s)


def test_the_maintenance_slot_is_at_night():
    hour, minute = DAILY_MAINTENANCE_AT
    assert 1 <= hour <= 5, f"{hour}:00 is not night"
    fires = _at(seconds_until_local(hour, minute))
    assert (fires.tm_hour, fires.tm_min) == (hour, minute)


def test_every_hour_of_the_day_lands_on_its_own_slot():
    """The helper must not be right only for the hour the suite happens
    to run in — that is exactly how a scheduling bug survives a test."""
    for hour in range(24):
        fires = _at(seconds_until_local(hour, 30))
        assert (fires.tm_hour, fires.tm_min) == (hour, 30), f"{hour}:30 landed on {fires.tm_hour}"


def test_the_slot_is_always_ahead_and_never_further_than_a_day():
    for hour in range(24):
        delay = seconds_until_local(hour, 0)
        assert 60 <= delay <= 86400 + 3600, f"{hour}:00 → {delay}s"


def test_a_slot_standing_on_right_now_goes_to_tomorrow_rather_than_spinning():
    """Re-arming at the very moment the slot comes round must not produce
    a zero delay and a timer storm."""
    now = time.localtime()
    delay = seconds_until_local(now.tm_hour, now.tm_min)
    assert delay >= 60
    fires = _at(delay)
    assert (fires.tm_hour, fires.tm_min) == (now.tm_hour, now.tm_min)


def test_the_quest_rollover_uses_the_same_helper_and_still_targets_00_05():
    fires = _at(_seconds_until_rollover_check())
    assert (fires.tm_hour, fires.tm_min) == (0, 5)


def test_the_pass_no_longer_re_arms_on_a_bare_interval():
    """Source-text, because the alternative is waiting out a day-long
    timer: the re-arm must go through the wall-clock helper."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app" / "maintenance.py").read_text(
        encoding="utf-8"
    )
    body = src[src.index("def _run_daily_cleanup") : src.index("def _seconds_until_rollover_check")]
    assert "seconds_until_local(" in body, "the nightly pass is not aimed at a wall clock"
    assert "Timer(86400" not in body, "the flat 24 h re-arm is back"


# ── Boot clears the archive; the nights stay short ──────────────────────
# „Kannst du jetzt einmalig alle aktualisieren! - jede nacht brauchen wir
# danach nicht mehr auf alle videos weil die ja korrekt aufgenommen
# werden!"


def _daily_cleanup_src() -> str:
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parent.parent / "app" / "maintenance.py").read_text(
        encoding="utf-8"
    )
    return src[src.index("def _run_daily_cleanup") : src.index("def seconds_until_local")]


def test_the_species_headline_pass_runs_only_on_the_boot_call():
    body = _daily_cleanup_src()
    at = body.index("_sweep_species_headlines(log)")
    guard = body.rindex("if first_run:", 0, at)
    assert guard > 0, "the archive-wide species pass must not run every night"


def test_the_nightly_fine_track_pass_is_scoped_to_a_lookback():
    from pathlib import Path as _P

    from app.maintenance import NIGHTLY_LOOKBACK_DAYS

    assert 1 <= NIGHTLY_LOOKBACK_DAYS <= 14
    src = (_P(__file__).resolve().parent.parent / "app" / "maintenance.py").read_text(
        encoding="utf-8"
    )
    body = src[src.index("def _sweep_tracking_backfill") : src.index("def _run_daily_cleanup")]
    assert (
        "since_days=None if first_run else NIGHTLY_LOOKBACK_DAYS" in body
    ), "the nightly catch-up must look back a few days, not walk the whole archive"


def test_the_boot_call_is_the_one_server_makes():
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parent.parent / "app" / "server.py").read_text(encoding="utf-8")
    assert "_run_daily_cleanup(first_run=True)" in src


def test_the_re_armed_timer_is_not_a_boot_pass():
    """The timer calls it with no arguments, so `first_run` defaults
    False — that default is what keeps every later night short."""
    import inspect

    from app.maintenance import _run_daily_cleanup

    assert inspect.signature(_run_daily_cleanup).parameters["first_run"].default is False
    assert "Timer(delay, _run_daily_cleanup)" in _daily_cleanup_src()
