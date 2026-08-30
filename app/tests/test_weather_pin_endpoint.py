"""POST /api/weather/sightings/<id>/pin — routes/weather_pin.py.

The only UI surface for the "keep forever" flag the nightly retention
sweep (weather_service/_retention.py) reads. Own blueprint module
because routes/weather.py is already past the file ceiling — same
reasoning as routes/weather_episodes.py.
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask")

from app import app_state  # noqa: E402
from app.routes import weather_pin  # noqa: E402


class _WS:
    def __init__(self, sightings: dict):
        self._sightings = sightings
        self.set_calls = []

    def get_sighting(self, sighting_id):
        return self._sightings.get(sighting_id)

    def set_sighting_pinned(self, sighting_id, pinned):
        self.set_calls.append((sighting_id, pinned))
        if sighting_id not in self._sightings:
            return False
        self._sightings[sighting_id]["pinned"] = pinned
        return True


@pytest.fixture
def client(monkeypatch):
    ws = _WS({"cam1__thunder__20260101_120000": {"id": "cam1__thunder__20260101_120000"}})
    monkeypatch.setattr(app_state, "weather_service", ws, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(weather_pin.bp)
    c = app.test_client()
    c._ws = ws
    return c


def test_explicit_pin_true_is_set(client):
    r = client.post(
        "/api/weather/sightings/cam1__thunder__20260101_120000/pin", json={"pinned": True}
    )
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "pinned": True}
    assert client._ws.set_calls == [("cam1__thunder__20260101_120000", True)]


def test_explicit_pin_false_unsets_it(client):
    r = client.post(
        "/api/weather/sightings/cam1__thunder__20260101_120000/pin", json={"pinned": False}
    )
    assert r.get_json()["pinned"] is False


def test_an_empty_body_toggles_the_current_state(client):
    """No 'pinned' key = toggle — the convenience path a plain curl or
    a naive re-click gets for free; the real pin-toggle.js UI always
    sends an explicit value instead (see pin-toggle.js's own docstring)."""
    r = client.post("/api/weather/sightings/cam1__thunder__20260101_120000/pin")
    assert r.get_json()["pinned"] is True  # was unset (falsy) → toggles on

    r2 = client.post("/api/weather/sightings/cam1__thunder__20260101_120000/pin")
    assert r2.get_json()["pinned"] is False  # toggles back off


def test_an_unknown_sighting_id_is_404(client):
    r = client.post("/api/weather/sightings/does-not-exist/pin", json={"pinned": True})
    assert r.status_code == 404


def test_an_unknown_sighting_id_with_no_body_is_also_404(client):
    """The toggle branch must resolve the current state first — it
    cannot 404 later with a stale 'not found' from a different path."""
    r = client.post("/api/weather/sightings/does-not-exist/pin")
    assert r.status_code == 404


def test_service_unavailable_is_503(monkeypatch):
    monkeypatch.setattr(app_state, "weather_service", None, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(weather_pin.bp)
    r = app.test_client().post("/api/weather/sightings/x/pin", json={"pinned": True})
    assert r.status_code == 503
