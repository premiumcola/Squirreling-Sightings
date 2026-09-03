"""``/api/timelapse/status`` carries the weather timelapses too.

The dashboard already polls this endpoint on every ``loadAll()`` for the
periodic per-camera profiles. The sun and event timelapses had no
endpoint of their own that the dashboard read — ``/api/weather/status``
is only polled while the Settings → Wetter panel is open, and it carries
no timelapse information at all. Rather than add a second poller, the
weather service's activity report rides along here.

Pinned below: the absent-service case must not look like the
nothing-scheduled case. Those are different statements and the tile
renders them differently.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import flask

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)


def _client(monkeypatch, weather_service):
    from app import app_state
    from app.routes.timelapse import bp

    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={"cameras": []}), raising=False)
    monkeypatch.setattr(app_state, "weather_service", weather_service, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


def test_the_payload_carries_the_weather_activity(monkeypatch):
    report = {
        "available": True,
        "sun": [{"camera_id": "cam1", "phase": "sunset", "state": "running", "remaining_s": 900}],
        "event": [],
        "running_count": 1,
    }
    ws = SimpleNamespace(timelapse_activity=lambda: report)
    r = _client(monkeypatch, ws).get("/api/timelapse/status")
    assert r.status_code == 200
    assert r.get_json()["weather"] == report


def test_no_weather_service_is_reported_as_unavailable_not_as_empty(monkeypatch):
    """`available: False` and an empty sun list mean different things.
    Collapsing them would let the tile claim 'nothing scheduled' while
    the service that schedules is simply not up."""
    r = _client(monkeypatch, None).get("/api/timelapse/status")
    w = r.get_json()["weather"]
    assert w["available"] is False
    assert w["running_count"] == 0


def test_a_throwing_weather_service_does_not_take_the_endpoint_down(monkeypatch):
    """The periodic timelapse figures are the endpoint's primary job and
    must survive a broken weather report."""

    def _boom():
        raise RuntimeError("weather service is having a day")

    ws = SimpleNamespace(timelapse_activity=_boom)
    r = _client(monkeypatch, ws).get("/api/timelapse/status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["weather"]["available"] is False
