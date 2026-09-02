"""One history row per Open-Meteo 15-minute slot, not one per poll.

The poll runs every `poll_interval` (300 s), but `_latest_slice` anchors
on the `minutely_15` slot covering now — so three consecutive polls read
the SAME measurement. Writing all three was not extra resolution, it was
one measurement in triplicate, and it is what drew a visible staircase
under every curve in the Wetterstatistik chart.

What must NOT change while that duplicate is suppressed: the live
`current_values` snapshot the panel reads, and the per-poll storm sweep.
Both keep the full 5-minute cadence; only the history row is skipped.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime

import pytest

flask = pytest.importorskip("flask")

from app.weather_service import _history as history_module  # noqa: E402
from app.weather_service._history import HistoryMixin  # noqa: E402

NOW = datetime(2026, 8, 30, 12, 0, 0)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    monkeypatch.setattr(history_module, "datetime", _FixedDatetime)


class _WS(HistoryMixin):
    """The narrowest object `_record_sample` actually touches."""

    def __init__(self):
        self.cfg = {}
        self._history_lock = threading.Lock()
        self._lock = threading.Lock()
        self._history: deque = deque()
        self._status: dict = {}
        self._last_slot_time = None
        self.ledger: list = []
        self.sweeps = 0

    def _append_history(self, sample):
        self.ledger.append(sample)

    def _sweep_episodes(self):
        self.sweeps += 1


def _slot(time_str, gusts):
    return {"time": time_str, "wind_gusts_10m": gusts}


SUN = {"altitude": 31.5}


def test_three_polls_of_one_slot_record_one_row():
    ws = _WS()
    for _ in range(3):
        ws._record_sample(_slot("2026-08-30T12:00", 22.0), SUN)
    assert len(ws._history) == 1
    assert len(ws.ledger) == 1


def test_every_poll_still_sweeps_and_refreshes_current_values():
    """The skip is narrow on purpose — storm detection and the live panel
    must not lose the 5-minute cadence just because the chart did."""
    ws = _WS()
    for gusts in (22.0, 23.0, 24.0):
        ws._record_sample(_slot("2026-08-30T12:00", gusts), SUN)
    assert ws.sweeps == 3
    # The LAST poll's values, not the recorded row's.
    assert ws._status["current_values"]["wind_gusts_10m"] == 24.0


def test_a_new_slot_records_again():
    ws = _WS()
    ws._record_sample(_slot("2026-08-30T12:00", 22.0), SUN)
    ws._record_sample(_slot("2026-08-30T12:00", 22.0), SUN)
    ws._record_sample(_slot("2026-08-30T12:15", 31.0), SUN)
    assert len(ws._history) == 2
    assert [r["values"]["wind_gusts_10m"] for r in ws._history] == [22.0, 31.0]


def test_a_slot_without_a_time_always_records():
    """`_latest_slice` returns a bare {} when `minutely_15` is empty. If
    that compared equal to the previous one, a run of empty payloads
    would wedge the buffer shut for good."""
    ws = _WS()
    for _ in range(3):
        ws._record_sample({}, SUN)
    assert len(ws._history) == 3


def test_an_empty_payload_does_not_suppress_the_next_real_slot():
    ws = _WS()
    ws._record_sample(_slot("2026-08-30T12:00", 22.0), SUN)
    ws._record_sample({}, SUN)
    ws._record_sample(_slot("2026-08-30T12:00", 22.0), SUN)
    # The empty poll cleared the remembered slot, so the repeat is a
    # genuine "first row of this slot" again rather than a lost sample.
    assert len(ws._history) == 3


def test_a_missing_field_is_recorded_as_a_gap():
    """Unchanged behaviour: the chart shows a gap rather than inventing
    a value, and the dedupe must not turn that into a skipped row."""
    ws = _WS()
    ws._record_sample({"time": "2026-08-30T12:00"}, SUN)
    assert ws._history[0]["values"]["wind_gusts_10m"] is None
    assert ws._history[0]["values"]["sun_altitude"] == 31.5
