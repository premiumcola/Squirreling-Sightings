"""The filter chips counted events the grid could never show.

`list_sightings` builds `counts` over the FULL manifest walk but returns
`items` sliced to one page. The gallery fetched once, with no page_size,
and filtered client-side over that slice — its own comment claimed "server
fetch always pulls the full list", which the server never honoured.

Field symptom: chips reading sunset 39 / sunrise 35 / Nebel 9 /
Starkregen 3 — 86 events against a page of 50. Selecting Starkregen
showed an empty grid, because all three sat below the newest 50.
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask")

from app import app_state  # noqa: E402
from app.routes import weather as weather_routes  # noqa: E402


class _WS:
    """Stands in for WeatherService with the real paging arithmetic."""

    def __init__(self, n_recent=83, n_old=3):
        self.calls = []
        self.items = [
            {
                "sighting_id": f"s{i}",
                "event_type": "fog",
                "started_at": f"2026-08-{30 - i // 24:02d}",
            }
            for i in range(n_recent)
        ] + [
            {"sighting_id": f"rain{i}", "event_type": "heavy_rain", "started_at": "2026-07-01"}
            for i in range(n_old)
        ]

    def list_sightings(self, *, page=0, page_size=50, **kw):
        self.calls.append({"page": page, "page_size": page_size})
        counts: dict[str, int] = {}
        for it in self.items:
            counts[it["event_type"]] = counts.get(it["event_type"], 0) + 1
        start = max(0, page) * page_size
        return {
            "items": self.items[start : start + page_size],
            "counts": counts,
            "total": len(self.items),
            "page": page,
            "page_size": page_size,
        }


@pytest.fixture
def client(monkeypatch):
    ws = _WS()
    monkeypatch.setattr(app_state, "weather_service", ws, raising=False)
    monkeypatch.setattr(weather_routes, "_attach_clip_size", lambda _it: None, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(weather_routes.bp)
    c = app.test_client()
    c._ws = ws
    return c


def test_the_default_page_is_unchanged_for_callers_that_do_not_ask():
    """No behaviour change for anything that was happy with 50."""
    assert True  # asserted through the route below


def test_asking_for_the_full_list_returns_every_event(client):
    r = client.get("/api/weather/sightings?page_size=500")
    body = r.get_json()
    assert body["total"] == 86
    assert len(body["items"]) == 86, "the grid still cannot see what the chips count"


def test_the_rare_event_is_reachable(client):
    """THE regression: heavy_rain is the oldest, so it fell off page 0."""
    body = client.get("/api/weather/sightings?page_size=500").get_json()
    kinds = {it["event_type"] for it in body["items"]}
    assert "heavy_rain" in kinds
    assert body["counts"]["heavy_rain"] == 3
    shown = sum(1 for it in body["items"] if it["event_type"] == "heavy_rain")
    assert shown == body["counts"]["heavy_rain"], "chip count and grid content still disagree"


def test_without_page_size_the_old_page_is_kept(client):
    body = client.get("/api/weather/sightings").get_json()
    assert body["page_size"] == 50
    assert len(body["items"]) == 50


def test_the_page_size_is_capped(client):
    """ "Everything" must stay bounded — a huge library must not become
    one enormous response."""
    client.get("/api/weather/sightings?page_size=100000")
    assert client._ws.calls[-1]["page_size"] == weather_routes.MAX_SIGHTINGS_PAGE_SIZE


def test_a_nonsense_page_size_does_not_crash(client):
    for bad in ("abc", "-5", "0"):
        r = client.get(f"/api/weather/sightings?page_size={bad}")
        assert r.status_code == 200
