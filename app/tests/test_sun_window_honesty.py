"""The sun-timelapse preview must quote the window that is recorded.

``_register_sun_jobs`` and ``_run_sun_capture`` both size the capture
from ``_SUN_TL_LOCKED_WINDOW_MIN`` (75 min) — the per-phase
``window_min`` in settings.json is not consulted by either. But
``sun_times_today``, which powers ``/api/weather/sun-times`` and the
Settings → Wetter preview row, read that stored value and derived
``window_start`` / ``window_end`` from it. With the shipped default of
30 the operator was shown a window 45 minutes shorter than the one the
recorder actually uses, right next to a chip reading "75 min · fest".

The rule pinned here: the number on screen is the number that records.
The response also echoes the honoured ``window_min`` / ``fps`` back, so
a consumer reading the phase block sees the locked values rather than
whatever stale pair sits in settings.json.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.weather_service._sun_tl import (
    _SUN_TL_LOCKED_FPS,
    _SUN_TL_LOCKED_WINDOW_MIN,
    SunTimelapseMixin,
)

# Far enough ahead that today's window has not started, so sun_times_today
# stays on today's event and the assertions don't depend on wall clock.
_EVENT_HOUR = 23


class _Svc(SunTimelapseMixin):
    """Just enough of WeatherService for sun_times_today — same stub
    pattern as test_weather_retention_sweep.py's `_Svc`."""

    def __init__(self, cams: list[dict]):
        self.server_cfg = {"location": {"lat": 49.45, "lon": 11.08}}
        self._cams = cams

    def _cfg_cameras(self) -> list[dict]:
        return self._cams

    def sun_event_today(self, phase: str, when: date | None = None) -> datetime:
        day = when or date.today()
        return datetime(day.year, day.month, day.day, _EVENT_HOUR, 0, 0)


def _cam(stored_window_min: int) -> dict:
    return {
        "id": "cam1",
        "name": "Garten",
        "weather": {
            "enabled": True,
            "sun_timelapse": {
                "sunrise": {"enabled": True, "window_min": stored_window_min, "fps": 3},
                "sunset": {"enabled": False},
            },
        },
    }


def _span_minutes(phase: dict) -> int:
    start = datetime.fromisoformat(phase["capture_start_iso"])
    end = datetime.fromisoformat(phase["capture_end_iso"])
    return int(round((end - start) / timedelta(minutes=1)))


def test_preview_window_spans_the_locked_window_not_the_stored_one():
    out = _Svc([_cam(stored_window_min=30)]).sun_times_today()
    sunrise = out["cameras"][0]["sunrise"]
    assert _span_minutes(sunrise) == _SUN_TL_LOCKED_WINDOW_MIN


def test_preview_ignores_even_a_hand_edited_window_min():
    """A settings.json poked to 10 must not shrink the quoted window —
    the recorder would still capture 75 minutes."""
    out = _Svc([_cam(stored_window_min=10)]).sun_times_today()
    assert _span_minutes(out["cameras"][0]["sunrise"]) == _SUN_TL_LOCKED_WINDOW_MIN


def test_response_echoes_the_honoured_window_and_fps():
    out = _Svc([_cam(stored_window_min=30)]).sun_times_today()
    sunrise = out["cameras"][0]["sunrise"]
    assert sunrise["window_min"] == _SUN_TL_LOCKED_WINDOW_MIN
    assert sunrise["fps"] == _SUN_TL_LOCKED_FPS


def test_settings_defaults_no_longer_seed_a_window_nobody_reads():
    """A fresh install must not persist a `window_min` the capture path
    overrides — that value only ever existed to be displayed wrongly."""
    from app.settings._consts import SUN_TL_DEFAULTS

    for phase in ("sunrise", "sunset"):
        assert "window_min" not in SUN_TL_DEFAULTS[phase]
