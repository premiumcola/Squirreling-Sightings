"""`/api/weather/history`'s additive `since`/`until` params.

Added so a saved manual event's exact time range can be replayed even
when it no longer falls inside "the last N hours from now" — the
existing `hours`-only callers (the Wetterdaten panel) must see no
change at all.

`history()` computes its `hours`-based cutoff off `datetime.now()`
internally, so every test here pins that clock via a `datetime`
subclass rather than letting real wall-clock time leak into the
window math.
"""

from __future__ import annotations

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
        self._history_lock = __import__("threading").Lock()
        self._history = deque(samples)


def _rows(offsets_min):
    """One row per offset (minutes before NOW), each with a distinct
    value so a test can tell which rows survived a filter."""
    out = []
    for i, m in enumerate(offsets_min):
        ts = (NOW - timedelta(minutes=m)).isoformat(timespec="seconds")
        out.append({"ts": ts, "values": {"precipitation": float(i)}})
    return out


# ── mixin ────────────────────────────────────────────────────────────────


def test_hours_only_is_unchanged():
    ws = _WS(_rows([600, 300, 30]))
    out = ws.history(hours=1)
    assert len(out["samples"]) == 1


def test_since_overrides_the_hours_cutoff():
    """A since_iso 10 h back must reach a row the 1 h preset would miss —
    the fix this endpoint exists for (replaying an old manual-event save
    while the panel itself is set to a short preset)."""
    ws = _WS(_rows([600, 300, 30]))
    since = (NOW - timedelta(hours=10)).isoformat(timespec="seconds")
    out = ws.history(hours=1, since_iso=since)
    assert len(out["samples"]) == 3


def test_until_excludes_rows_after_it():
    ws = _WS(_rows([600, 300, 30]))
    since = (NOW - timedelta(hours=11)).isoformat(timespec="seconds")
    until = (NOW - timedelta(hours=6)).isoformat(timespec="seconds")
    out = ws.history(hours=1, since_iso=since, until_iso=until)
    # Only the 600-min-back row (10 h) is inside [since=11h, until=6h] —
    # the 300-min-back row (5 h) is after `until` and must be excluded.
    assert len(out["samples"]) == 1


def test_an_unparseable_since_falls_back_to_hours():
    ws = _WS(_rows([600, 300, 30]))
    out = ws.history(hours=1, since_iso="not-a-date")
    assert len(out["samples"]) == 1


# ── route ────────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    ws = _WS(_rows([600, 300, 30]))
    monkeypatch.setattr(app_state, "weather_service", ws, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(weather_routes.bp)
    return app.test_client()


def test_route_passes_since_and_until_through(client):
    since = (NOW - timedelta(hours=11)).isoformat(timespec="seconds")
    until = (NOW - timedelta(hours=6)).isoformat(timespec="seconds")
    r = client.get(f"/api/weather/history?hours=1&since={since}&until={until}")
    assert r.status_code == 200
    assert len(r.get_json()["samples"]) == 1


def test_route_without_since_until_keeps_old_behaviour(client):
    r = client.get("/api/weather/history?hours=1")
    assert len(r.get_json()["samples"]) == 1
