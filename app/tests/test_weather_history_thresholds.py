"""HYG · /api/weather/history must carry every configured threshold.

The payload builder read each event's boundary with a hard-coded
``ev_cfg.get("threshold")``. Fog does not store one: its key is
``vis_max_m`` (settings/_consts.py · WEATHER_DEFAULTS). So straight out
of the box the Sicht curve came back as ``enabled=True`` with
``threshold=None`` — an armed event with no line.

The project already knows the mapping. ``weather_episodes/_consts.py``
carries ``EVENT_THRESHOLD_KEY = {"fog": "vis_max_m"}`` and
``_thresholds.py`` looks every event up through it; ``_history.py`` was
the one place that did not, so the two sources disagreed.

What the operator saw: isolating "Sicht" in the Wetterstatistik printed
"keine Schwelle konfiguriert" (stats-thresholds.js) although Nebel was
configured at 1000 m and firing, and the all-lines view drew no tick for
it at all. A storm detail chart with no threshold snapshot of its own
falls back to this same payload and was equally blank.

Pure dict arithmetic over HistoryMixin.history() — no storage, no HTTP.
"""

from __future__ import annotations

import threading
from collections import deque

from app.settings._consts import WEATHER_DEFAULTS
from app.weather_service._consts import HISTORY_FIELD_TO_EVENT
from app.weather_service._history import HistoryMixin


class _WS(HistoryMixin):
    def __init__(self, events):
        self.cfg = {"events": events}
        self._history_lock = threading.Lock()
        self._history = deque()


def _payload(events=None):
    return _WS(events if events is not None else WEATHER_DEFAULTS["events"]).history(hours=1)


def test_the_configured_fog_threshold_reaches_the_chart():
    """1000 m is a shipped default, not an exotic setting."""
    out = _payload()
    assert out["events_enabled"]["visibility"] is True
    assert out["thresholds"]["visibility"] == 1000.0


def test_no_event_is_armed_without_a_line_to_draw():
    """The general property behind the fog case: if the payload says an
    event is switched on, it must also say where its boundary sits."""
    out = _payload()
    for field, armed in out["events_enabled"].items():
        if armed:
            assert out["thresholds"][field] is not None, (
                f"{field} is armed but ships no threshold — the chart "
                f"prints 'keine Schwelle konfiguriert' for a live trigger"
            )


def test_the_ordinary_threshold_key_still_works():
    out = _payload()
    assert out["thresholds"]["precipitation"] == 5.0
    assert out["thresholds"]["lightning_potential"] == 0.2
    assert out["thresholds"]["snowfall"] == 0.5


def test_gusts_carry_the_storm_threshold():
    """wind_gusts_10m gained an event (`storm`) in bc935af0; the comment
    on this block still listed it as field-without-an-event."""
    assert HISTORY_FIELD_TO_EVENT["wind_gusts_10m"] == "storm"
    assert _payload()["thresholds"]["wind_gusts_10m"] == 60.0


def test_a_field_with_no_event_stays_null_on_both_maps():
    out = _payload()
    for field in ("cloud_cover", "sun_altitude"):
        assert field not in HISTORY_FIELD_TO_EVENT
        assert out["thresholds"][field] is None
        assert out["events_enabled"][field] is None


def test_a_missing_or_unparsable_value_degrades_to_null_not_a_crash():
    out = _payload({"fog": {"enabled": True}, "heavy_rain": {"enabled": True, "threshold": "x"}})
    assert out["thresholds"]["visibility"] is None
    assert out["thresholds"]["precipitation"] is None
    assert out["events_enabled"]["visibility"] is True
