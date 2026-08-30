"""Manual weather events — user-saved chart ranges.

Two layers, matching the house style (test_weather_sightings_paging.py):
the mixin's own persistence (one JSON file per record, mirroring
RecapsMixin) gets exercised directly against a tmp_path storage root,
and the Flask route's validation gets exercised through the test client
against a lightweight stand-in service.
"""

from __future__ import annotations

import json

import pytest

flask = pytest.importorskip("flask")

from app import app_state  # noqa: E402
from app.routes import weather_manual_events as routes  # noqa: E402
from app.weather_service._manual_events import (  # noqa: E402
    MANUAL_EVENT_CATEGORIES_MAX,
    ManualEventsMixin,
    manual_event_categories,
)

RANGE_A = ("2026-08-29T14:00:00", "2026-08-29T18:00:00")


class _FakeWS(ManualEventsMixin):
    """Just enough of WeatherService for ManualEventsMixin to run against
    a real tmp_path directory — proves list/get/create/delete round-trip
    through actual files, not mocks."""

    def __init__(self, root):
        self._root = root

    def _sightings_dir(self):
        return self._root


# ── mixin: persistence round-trip ───────────────────────────────────────


def test_create_then_list_round_trips(tmp_path):
    ws = _FakeWS(tmp_path)
    created = ws.create_manual_event(
        "Gewitter mit Blitzen",
        *RANGE_A,
        ["precipitation", "lightning_potential"],
        category="thunder",
        characteristic="Regen setzt ein, dann Blitze auf hohem Niveau — mittelgroßes Gewitter.",
    )
    assert created["name"] == "Gewitter mit Blitzen"
    assert created["category"] == "thunder"
    assert created["characteristic"].startswith("Regen setzt ein")
    assert created["id"].startswith("manual_")
    items = ws.list_manual_events()
    assert len(items) == 1
    assert items[0]["id"] == created["id"]
    assert items[0]["curves"] == ["precipitation", "lightning_potential"]


def test_characteristic_defaults_to_empty_string(tmp_path):
    ws = _FakeWS(tmp_path)
    created = ws.create_manual_event("A", *RANGE_A, ["snowfall"], category="snow")
    assert created["characteristic"] == ""


def test_list_sorts_newest_range_first(tmp_path):
    ws = _FakeWS(tmp_path)
    older = ws.create_manual_event(
        "Older", "2026-08-01T00:00:00", "2026-08-01T01:00:00", ["snowfall"], category="snow"
    )
    newer = ws.create_manual_event(
        "Newer", "2026-08-29T00:00:00", "2026-08-29T01:00:00", ["snowfall"], category="snow"
    )
    ids = [it["id"] for it in ws.list_manual_events()]
    assert ids == [newer["id"], older["id"]]


def test_get_missing_event_is_none(tmp_path):
    ws = _FakeWS(tmp_path)
    assert ws.get_manual_event("manual_does_not_exist") is None


def test_delete_removes_the_file_and_reports_it(tmp_path):
    ws = _FakeWS(tmp_path)
    created = ws.create_manual_event(
        "Temp", "2026-08-01T00:00:00", "2026-08-01T01:00:00", ["snowfall"], category="snow"
    )
    assert (tmp_path / "manual_events" / f"{created['id']}.json").exists()
    assert ws.delete_manual_event(created["id"]) is True
    assert ws.get_manual_event(created["id"]) is None
    # Deleting again is a clean False, not an exception.
    assert ws.delete_manual_event(created["id"]) is False


def test_two_events_saved_in_the_same_second_do_not_collide(tmp_path):
    """The id's random suffix must prevent an overwrite when the operator
    saves two ranges within the same wall-clock second."""
    ws = _FakeWS(tmp_path)
    a = ws.create_manual_event(
        "A", "2026-08-01T00:00:00", "2026-08-01T01:00:00", ["snowfall"], category="snow"
    )
    b = ws.create_manual_event(
        "B", "2026-08-02T00:00:00", "2026-08-02T01:00:00", ["snowfall"], category="snow"
    )
    assert a["id"] != b["id"]
    assert len(ws.list_manual_events()) == 2


# ── multi-category (one event is genuinely more than one thing) ──────────


def test_create_stores_every_picked_category_and_mirrors_the_first(tmp_path):
    ws = _FakeWS(tmp_path)
    created = ws.create_manual_event(
        "Gewitter mit Starkregen",
        *RANGE_A,
        ["precipitation", "lightning_potential"],
        categories=["thunder", "heavy_rain"],
    )
    assert created["categories"] == ["thunder", "heavy_rain"]
    # `category` stays populated so a reader that only knows the old
    # single field keeps working.
    assert created["category"] == "thunder"
    assert ws.list_manual_events()[0]["categories"] == ["thunder", "heavy_rain"]


def test_the_single_category_argument_still_works(tmp_path):
    """Any caller still passing `category=` gets a one-element list."""
    ws = _FakeWS(tmp_path)
    created = ws.create_manual_event("A", *RANGE_A, ["snowfall"], category="snow")
    assert created["categories"] == ["snow"]
    assert created["category"] == "snow"


def test_an_old_single_category_record_still_lists_and_gains_a_list(tmp_path):
    """Records the operator saved BEFORE multi-select carry only a
    `category` string. They must keep listing — and come back with a
    `categories` list — without any on-disk migration."""
    legacy = {
        "id": "manual_20260801T120000_abc123",
        "name": "Altes Gewitter",
        "category": "thunder",
        "characteristic": "",
        "range_start": RANGE_A[0],
        "range_end": RANGE_A[1],
        "curves": ["lightning_potential"],
        "created_at": "2026-08-01T12:00:00",
    }
    root = tmp_path / "manual_events"
    root.mkdir(parents=True)
    (root / f"{legacy['id']}.json").write_text(json.dumps(legacy), encoding="utf-8")
    ws = _FakeWS(tmp_path)
    items = ws.list_manual_events()
    assert len(items) == 1
    assert items[0]["categories"] == ["thunder"]
    assert items[0]["category"] == "thunder"
    assert ws.get_manual_event(legacy["id"])["categories"] == ["thunder"]


def test_manual_event_categories_normalises_both_shapes():
    assert manual_event_categories({"category": "fog"}) == ["fog"]
    assert manual_event_categories({"categories": ["fog", "snow"]}) == ["fog", "snow"]
    # A new-shape record's list wins over its own first-entry mirror.
    assert manual_event_categories({"categories": ["snow", "fog"], "category": "snow"}) == [
        "snow",
        "fog",
    ]
    # Duplicates and junk entries drop out; a record with neither field
    # yields an empty list rather than raising.
    assert manual_event_categories({"categories": ["fog", "fog", 7, ""]}) == ["fog"]
    assert manual_event_categories({}) == []


# ── route: validation + wiring ───────────────────────────────────────────


class _RouteWS(ManualEventsMixin):
    def __init__(self, root):
        self._root = root

    def _sightings_dir(self):
        return self._root


def _body(**overrides):
    body = {
        "name": "Gewitter mit Blitzen",
        "category": "thunder",
        "range_start": RANGE_A[0],
        "range_end": RANGE_A[1],
        "curves": ["precipitation", "lightning_potential"],
    }
    body.update(overrides)
    return body


@pytest.fixture
def client(tmp_path, monkeypatch):
    ws = _RouteWS(tmp_path)
    monkeypatch.setattr(app_state, "weather_service", ws, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(routes.bp)
    return app.test_client()


def test_missing_service_degrades_to_an_empty_list(monkeypatch):
    monkeypatch.setattr(app_state, "weather_service", None, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(routes.bp)
    r = app.test_client().get("/api/weather/manual-events")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}


def test_create_requires_a_name(client):
    body = _body()
    del body["name"]
    r = client.post("/api/weather/manual-events", json=body)
    assert r.status_code == 400
    assert "name" in r.get_json()["error"]


def test_create_requires_a_known_category(client):
    r = client.post("/api/weather/manual-events", json=_body(category="not_a_real_category"))
    assert r.status_code == 400
    assert "category" in r.get_json()["error"]


def test_create_rejects_an_unknown_curve_key(client):
    r = client.post("/api/weather/manual-events", json=_body(curves=["not_a_real_field"]))
    assert r.status_code == 400


def test_create_rejects_an_inverted_range(client):
    r = client.post(
        "/api/weather/manual-events",
        json=_body(range_start=RANGE_A[1], range_end=RANGE_A[0]),
    )
    assert r.status_code == 400
    assert "range_end" in r.get_json()["error"]


def test_create_rejects_an_oversized_characteristic(client):
    r = client.post("/api/weather/manual-events", json=_body(characteristic="x" * 2001))
    assert r.status_code == 400
    assert "characteristic" in r.get_json()["error"]


def test_create_then_list_then_delete_over_http(client):
    r = client.post(
        "/api/weather/manual-events",
        json=_body(
            characteristic="Regen setzt ein, dann Blitze auf hohem Niveau — mittelgroßes Gewitter."
        ),
    )
    assert r.status_code == 201
    item = r.get_json()["item"]
    assert item["category"] == "thunder"
    assert item["characteristic"].startswith("Regen setzt ein")
    event_id = item["id"]

    listed = client.get("/api/weather/manual-events").get_json()["items"]
    assert any(it["id"] == event_id for it in listed)

    deleted = client.delete(f"/api/weather/manual-events/{event_id}")
    assert deleted.status_code == 200

    listed_after = client.get("/api/weather/manual-events").get_json()["items"]
    assert not any(it["id"] == event_id for it in listed_after)


def test_delete_unknown_id_is_404(client):
    r = client.delete("/api/weather/manual-events/manual_does_not_exist")
    assert r.status_code == 404


def test_create_dedupes_repeated_curve_keys(client):
    r = client.post(
        "/api/weather/manual-events",
        json=_body(curves=["precipitation", "precipitation"]),
    )
    assert r.status_code == 201
    assert r.get_json()["item"]["curves"] == ["precipitation"]


def test_create_without_characteristic_defaults_to_empty_string_over_http(client):
    r = client.post("/api/weather/manual-events", json=_body())
    assert r.status_code == 201
    assert r.get_json()["item"]["characteristic"] == ""


def test_create_over_http_accepts_several_categories(client):
    body = _body(categories=["thunder", "heavy_rain"])
    del body["category"]
    r = client.post("/api/weather/manual-events", json=body)
    assert r.status_code == 201
    item = r.get_json()["item"]
    assert item["categories"] == ["thunder", "heavy_rain"]
    assert item["category"] == "thunder"


def test_create_over_http_still_accepts_the_original_single_category(client):
    """The pre-multi-select request shape must not start 400-ing."""
    r = client.post("/api/weather/manual-events", json=_body())
    assert r.status_code == 201
    assert r.get_json()["item"]["categories"] == ["thunder"]


def test_create_rejects_an_unknown_category_inside_the_list(client):
    body = _body(categories=["thunder", "not_a_real_category"])
    del body["category"]
    r = client.post("/api/weather/manual-events", json=body)
    assert r.status_code == 400
    assert "category" in r.get_json()["error"]


def test_create_rejects_an_empty_category_list(client):
    body = _body(categories=[])
    del body["category"]
    r = client.post("/api/weather/manual-events", json=body)
    assert r.status_code == 400
    assert "categories" in r.get_json()["error"]


def test_create_rejects_more_categories_than_the_card_can_show(client):
    body = _body(categories=list(routes.MANUAL_EVENT_CATEGORIES[: MANUAL_EVENT_CATEGORIES_MAX + 1]))
    del body["category"]
    r = client.post("/api/weather/manual-events", json=body)
    assert r.status_code == 400
    assert "categories" in r.get_json()["error"]


def test_create_dedupes_repeated_categories(client):
    body = _body(categories=["thunder", "thunder", "fog"])
    del body["category"]
    r = client.post("/api/weather/manual-events", json=body)
    assert r.status_code == 201
    assert r.get_json()["item"]["categories"] == ["thunder", "fog"]
