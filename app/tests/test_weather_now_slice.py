"""The weather poll must read NOW, not the end of the forecast.

`minutely_15` is a FORECAST: it begins in the past and runs days ahead.
`_latest_slice` walked back from the END of that array and took the
first row carrying any value — but the end is the forecast horizon, and
out there ICON-D2 still supplies `wind_gusts_10m` while precipitation,
visibility, cloud cover and lightning potential have all run out.

Observed on the live system during an actual storm: the status endpoint
reported `precipitation: null`, `visibility: null`, `lightning_potential:
null` and a single `wind_gusts_10m: 16.6` — and a stored sighting
carried `"time": "2026-08-30T02:45"` while the wall clock said the 28th.
Two days into the future.

Two consequences: `heavy_rain` could never fire, because a null is not
comparable to a 5.0 mm threshold; and the panel showed fair weather
while it was pouring outside.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.weather_service._detection import DetectionMixin


class _Svc(DetectionMixin):
    def __init__(self):
        self.server_cfg = {"location": {"lat": 49.57, "lon": 11.20}}
        self._sun_cache = (0.0, None)


def _payload(now=None, horizon_slots=200):
    """A realistic response: measurements around now, gusts-only far out."""
    now = now or datetime.now()
    base = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    # 8 slots of history, then the forecast horizon.
    start = base - timedelta(minutes=15 * 8)
    times, precip, gusts, vis = [], [], [], []
    for i in range(8 + horizon_slots):
        t = start + timedelta(minutes=15 * i)
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        near_now = t <= base
        # 12 mm/h right now — an unmistakable downpour.
        precip.append(12.0 if near_now else None)
        vis.append(3000.0 if near_now else None)
        # Gusts survive to the horizon; that asymmetry IS the bug.
        gusts.append(70.0 if near_now else 16.6)
    return {
        "minutely_15": {
            "time": times,
            "precipitation": precip,
            "visibility": vis,
            "wind_gusts_10m": gusts,
        }
    }


def test_it_reads_the_slot_covering_now():
    slot = _Svc()._latest_slice(_payload())

    assert (
        slot["precipitation"] == 12.0
    ), "picked a forecast row instead of now — heavy_rain can never fire on a null"
    assert slot["wind_gusts_10m"] == 70.0


def test_it_does_not_return_the_forecast_horizon():
    now = datetime.now()
    slot = _Svc()._latest_slice(_payload(now))
    picked = datetime.fromisoformat(slot["time"])

    assert picked <= now, f"picked {picked}, which is in the future"
    assert (now - picked) < timedelta(hours=2), "picked a stale row far in the past"


def test_the_storm_case_end_to_end():
    """12 mm/h against a 5.0 mm threshold must be comparable at all."""
    slot = _Svc()._latest_slice(_payload())
    assert slot["precipitation"] is not None
    assert slot["precipitation"] >= 5.0


def test_a_gap_at_now_falls_back_to_the_last_real_measurement():
    """Nulls at the current slot must walk BACKWARDS, not forwards."""
    p = _payload()
    for k in ("precipitation", "visibility", "wind_gusts_10m"):
        p["minutely_15"][k][8] = None  # the now-slot
    slot = _Svc()._latest_slice(p)

    assert slot["precipitation"] == 12.0
    assert datetime.fromisoformat(slot["time"]) <= datetime.now()


def test_an_all_history_payload_still_works():
    """No future rows at all — the common case for a replayed fixture."""
    p = _payload(horizon_slots=0)
    assert _Svc()._latest_slice(p)["precipitation"] == 12.0


@pytest.mark.parametrize("payload", [{}, {"minutely_15": {}}, {"minutely_15": {"time": []}}])
def test_degenerate_payloads_do_not_raise(payload):
    assert _Svc()._latest_slice(payload) == {}


def test_unparseable_timestamps_do_not_raise():
    p = _payload()
    p["minutely_15"]["time"][3] = "not-a-date"
    assert _Svc()._latest_slice(p)["precipitation"] is not None
