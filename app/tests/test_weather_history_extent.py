"""`/api/weather/history` reports what the archive actually holds.

The range picker offers a fixed 1 h / 6 h / 24 h / 7 d / 30 d ladder. It
used to offer all five unconditionally, so a fresh install drew three
hours of data stretched across a month-wide axis. The client cannot work
this out for itself — asking for 30 h and getting 3 h back looks exactly
like a service that only kept 3 h — so the payload carries the buffer's
own oldest/newest/count, independent of the requested window.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timedelta

import pytest

flask = pytest.importorskip("flask")

from app import app_state  # noqa: E402
from app.routes import weather as weather_routes  # noqa: E402
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
    def __init__(self, samples):
        self.cfg = {}
        self._history_lock = threading.Lock()
        self._history = deque(samples)


def _rows(offsets_min):
    """Oldest first, as the deque is guaranteed to be."""
    return [
        {
            "ts": (NOW - timedelta(minutes=m)).isoformat(timespec="seconds"),
            "values": {"precipitation": float(i)},
        }
        for i, m in enumerate(sorted(offsets_min, reverse=True))
    ]


def test_extent_reports_the_buffer_not_the_window():
    """The whole point: a narrow request must still say how much exists."""
    ws = _WS(_rows([600, 300, 30]))
    out = ws.history(hours=1)
    assert len(out["samples"]) == 1
    assert out["extent"]["count"] == 3
    assert out["extent"]["oldest"] == (NOW - timedelta(minutes=600)).isoformat(timespec="seconds")
    assert out["extent"]["newest"] == (NOW - timedelta(minutes=30)).isoformat(timespec="seconds")


def test_extent_on_an_empty_buffer_says_so_without_raising():
    out = _WS([]).history(hours=24)
    assert out["extent"] == {"oldest": None, "newest": None, "count": 0}


def test_a_since_until_replay_still_reports_the_full_extent():
    """The manual-event replay path narrows the window hardest of all."""
    ws = _WS(_rows([600, 300, 30]))
    since = (NOW - timedelta(minutes=320)).isoformat(timespec="seconds")
    until = (NOW - timedelta(minutes=280)).isoformat(timespec="seconds")
    out = ws.history(hours=24, since_iso=since, until_iso=until)
    assert len(out["samples"]) == 1
    assert out["extent"]["count"] == 3


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_state, "weather_service", _WS(_rows([600, 30])), raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(weather_routes.bp)
    return app.test_client()


def test_the_route_carries_extent(client):
    assert client.get("/api/weather/history?hours=1").get_json()["extent"]["count"] == 2


def test_the_service_down_fallback_carries_the_same_key(monkeypatch):
    """Both branches must answer the same shape, or the picker sees a
    payload with no extent and cannot tell 'unknown' from 'empty'."""
    monkeypatch.setattr(app_state, "weather_service", None, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(weather_routes.bp)
    body = app.test_client().get("/api/weather/history").get_json()
    assert body["extent"] == {"oldest": None, "newest": None, "count": 0}
