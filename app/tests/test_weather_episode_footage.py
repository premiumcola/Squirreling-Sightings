"""Episode record contract + the footage endpoint behind the detail page.

Everything here exercises behaviour, not source text: a synthetic
history buffer goes in, a record or a footage payload comes out, and the
assertions are on the numbers. Stub-based — no Open-Meteo call, no
camera, no scheduler, and the only weather service in sight is a
two-method fake.

The four things pinned here all had a defect:

* ``visibility`` is a peak metric, and its peak is the episode MINIMUM.
  Fog is configured as a ceiling (``vis_max_m``), so a LOW reading is
  the alarm and a plain max would store the clearest moment of the fog.
* every record carries the ``thresholds`` snapshot it was measured
  against — the archive outlives the settings that produced it.
* the footage endpoint exists at all, distinguishes "nothing to show"
  (200, empty groups) from "could not look" (a ``degraded`` marker),
  and returns the item shape the client already consumes.
* list rows carry ``footage_count``, without which the row's footage
  chip can never appear.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import app_state
from app.routes import weather_episodes as episode_routes
from app.weather_episodes import (
    build_footage_index,
    detect_episodes,
    earliest_window_start,
    episode_footage,
    episode_footage_counts,
    list_episodes,
    sweep,
)
from app.weather_episodes._footage import episode_window

flask = pytest.importorskip("flask")

BASE = datetime(2026, 8, 20, 6, 0, 0)
STEP_MIN = 5

EVENTS = {
    "thunder": {"enabled": True, "threshold": 1000.0},
    "heavy_rain": {"enabled": True, "threshold": 5.0},
    "snow": {"enabled": True, "threshold": 0.5},
    "fog": {"enabled": True, "vis_max_m": 1000},
}
TIGHT = {"enabled": True, "pre_min": 10, "post_min": 10, "settle_min": 30}


def _rows(series, *, field="lightning_potential"):
    out = []
    for i, val in enumerate(series):
        values = {
            "precipitation": None,
            "snowfall": None,
            "lightning_potential": None,
            "visibility": None,
            "wind_gusts_10m": None,
        }
        if isinstance(val, dict):
            values.update(val)
        else:
            values[field] = val
        out.append(
            {
                "ts": (BASE + timedelta(minutes=i * STEP_MIN)).isoformat(timespec="seconds"),
                "values": values,
            }
        )
    return out


def _one_storm():
    """A six-slot thunderstorm with wind and a visibility dip inside it."""
    storm = [
        {"lightning_potential": 1500.0, "wind_gusts_10m": 40.0, "visibility": 20000.0},
        {"lightning_potential": 2400.0, "wind_gusts_10m": 95.0, "visibility": 4000.0},
        {"lightning_potential": 2000.0, "wind_gusts_10m": 70.0, "visibility": 800.0},
        {"lightning_potential": 1800.0, "wind_gusts_10m": 60.0, "visibility": 2500.0},
        {"lightning_potential": 1200.0, "wind_gusts_10m": 50.0, "visibility": 15000.0},
        {"lightning_potential": 1100.0, "wind_gusts_10m": 45.0, "visibility": 18000.0},
    ]
    return _rows([0.0] * 12 + storm + [0.0] * 60)


def _record():
    records, _pending = detect_episodes(_one_storm(), events_cfg=EVENTS, episode_cfg=TIGHT)
    assert len(records) == 1
    return records[0]


# ── the record's peaks + threshold snapshot ────────────────────────────


def test_visibility_peak_is_the_minimum_not_the_maximum():
    """Fog's alarm side is DOWNWARDS. A max would archive 20 km of
    perfect visibility as the episode's `visibility` peak and leave the
    800 m moment — the only interesting one — unrecorded."""
    peaks = _record()["peaks"]
    assert peaks["visibility"] == 800.0
    # …while every other metric still stores its maximum.
    assert peaks["lightning_potential"] == 2400.0
    assert peaks["wind_gusts_10m"] == 95.0


def test_visibility_is_carried_even_though_it_did_not_trigger():
    """The pill exists in the UI for every PEAK_FIELDS entry; a field
    absent from the record renders a control that can never light up."""
    assert "visibility" in _record()["peaks"]


def test_record_stamps_the_thresholds_it_was_measured_against():
    thr = _record()["thresholds"]
    assert thr["lightning_potential"] == 1000.0
    assert thr["precipitation"] == 5.0
    # Fog is configured as `vis_max_m`, not `threshold`; the live history
    # payload therefore emits null for it and only the snapshot knows.
    assert thr["visibility"] == 1000.0
    # Wind has no event at all, so it must be ABSENT rather than 0 — a
    # zero here draws a "Schwelle" line along the chart's axis floor.
    assert "wind_gusts_10m" not in thr


def test_threshold_snapshot_follows_the_configured_values():
    raised = dict(EVENTS, thunder={"enabled": True, "threshold": 2500.0})
    records, _ = detect_episodes(_one_storm(), events_cfg=raised, episode_cfg=TIGHT)
    assert records[0]["thresholds"]["lightning_potential"] == 2500.0


# ── footage: window maths ──────────────────────────────────────────────


def _cand(kind, start, minutes, cam="cam1"):
    return {
        "kind": kind,
        "cam_id": cam,
        "cam_name": cam,
        "start": start,
        "end": start + timedelta(minutes=minutes),
        "video_url": "/media/x.mp4",
        "thumb_url": "/media/x.jpg",
        "missing_media": False,
        "extra": {},
    }


def test_episode_window_includes_the_stored_margins():
    rec = _record()
    start, end = episode_window(rec)
    assert start == datetime.fromisoformat(rec["started_at"]) - timedelta(minutes=10)
    assert end == datetime.fromisoformat(rec["ended_at"]) + timedelta(minutes=10)


def test_only_overlapping_recordings_are_returned_and_grouped_by_purpose():
    rec = _record()
    win_start, win_end = episode_window(rec)
    candidates = [
        _cand("thunder_rising", win_start + timedelta(minutes=5), 20),
        _cand("thunder", win_start + timedelta(minutes=1), 1),
        _cand("sun_timelapse_set", win_start + timedelta(minutes=2), 5),
        _cand("motion", win_start + timedelta(minutes=3), 1),
        _cand("timelapse", win_end - timedelta(minutes=1), 30),
        # Two days later — must not appear anywhere.
        _cand("motion", win_end + timedelta(days=2), 1),
    ]
    payload = episode_footage(candidates, [], rec)
    assert payload["total"] == 5
    assert len(payload["groups"]["event_timelapse"]) == 1
    assert len(payload["groups"]["weather_clips"]) == 1
    assert len(payload["groups"]["sun_timelapse"]) == 1
    assert len(payload["groups"]["motion"]) == 1
    assert len(payload["groups"]["timelapse"]) == 1


def test_items_carry_the_shape_the_client_consumes():
    rec = _record()
    win_start, _ = episode_window(rec)
    payload = episode_footage([_cand("thunder", win_start + timedelta(minutes=5), 4)], [], rec)
    item = payload["groups"]["weather_clips"][0]
    for key in (
        "kind",
        "kind_label",
        "cam_id",
        "cam_name",
        "time_label",
        "thumb_url",
        "video_url",
        "missing_media",
        "overlap_s",
        "span",
    ):
        assert key in item, "the footage tile reads item.{}".format(key)
    assert item["kind_label"] == "Gewitter"
    assert item["overlap_s"] == 240.0
    assert set(item["span"]) == {"start", "end"}


def test_a_touching_but_non_overlapping_clip_is_excluded():
    """Zero-width overlap is not an overlap — otherwise every clip that
    merely ends when the episode begins is listed as storm footage."""
    rec = _record()
    win_start, _ = episode_window(rec)
    payload = episode_footage([_cand("motion", win_start - timedelta(minutes=1), 1)], [], rec)
    assert payload["total"] == 0


def test_counts_are_per_episode():
    rec = _record()
    win_start, _ = episode_window(rec)
    other = dict(rec, id="other", started_at="2020-01-01T00:00:00", ended_at="2020-01-01T01:00:00")
    counts = episode_footage_counts(
        [_cand("motion", win_start + timedelta(minutes=5), 1)], [rec, other]
    )
    assert counts[rec["id"]] == 1
    assert counts["other"] == 0


def test_earliest_window_start_bounds_the_motion_scan():
    rec = _record()
    older = dict(rec, id="older", started_at="2020-01-01T00:00:00", ended_at="2020-01-01T01:00:00")
    assert earliest_window_start([rec, older]) == datetime(2019, 12, 31, 23, 50)


# ── footage: degradation ───────────────────────────────────────────────


def test_no_weather_service_is_reported_not_hidden(tmp_path):
    _cands, degraded = build_footage_index(tmp_path, weather_service=None, store=None, cameras=[])
    assert "weather_service_unavailable" in degraded


def test_a_failing_sighting_scan_degrades_instead_of_raising(tmp_path):
    class Broken:
        def list_sightings(self, **_kw):
            raise OSError("storage gone")

    cands, degraded = build_footage_index(
        tmp_path, weather_service=Broken(), store=None, cameras=[]
    )
    assert cands == []
    assert "weather_service_unavailable" in degraded


def test_event_timelapse_opt_in_decides_the_activation_hint(tmp_path):
    off = [{"id": "cam1", "name": "Hof", "weather": {"enabled": True}}]
    on = [
        {
            "id": "cam1",
            "name": "Hof",
            "weather": {"enabled": True, "event_timelapse": {"enabled": True}},
        }
    ]
    _c, degraded_off = build_footage_index(tmp_path, cameras=off)
    _c, degraded_on = build_footage_index(tmp_path, cameras=on)
    assert "event_timelapse_disabled" in degraded_off
    assert "event_timelapse_disabled" not in degraded_on


# ── HTTP contract ──────────────────────────────────────────────────────


class _FakeWeather:
    """Just enough weather service to answer one sighting scan."""

    def __init__(self, items):
        self._items = items

    def list_sightings(self, **_kw):
        return {"items": list(self._items)}

    def episodes_pending(self):
        return None


@pytest.fixture
def client(tmp_path, monkeypatch):
    sweep(tmp_path, _one_storm(), events_cfg=EVENTS, episode_cfg=TIGHT)
    rec = list_episodes(tmp_path)[0]
    win_start, _ = episode_window(rec)
    sighting = {
        "id": "cam1__thunder__x",
        "cam_id": "cam1",
        "cam_name": "Hof",
        "event_type": "thunder",
        "started_at": (win_start + timedelta(minutes=5)).isoformat(timespec="seconds"),
        "duration_s": 12,
        "clip_path": "weather/cam1/thunder/x.mp4",
        "thumb_path": "weather/cam1/thunder/x.jpg",
    }
    monkeypatch.setattr(app_state, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(app_state, "weather_service", _FakeWeather([sighting]), raising=False)
    monkeypatch.setattr(app_state, "store", None, raising=False)
    monkeypatch.setattr(
        episode_routes, "_cameras", lambda: [{"id": "cam1", "name": "Hof"}], raising=True
    )
    flask_app = flask.Flask(__name__)
    flask_app.register_blueprint(episode_routes.bp)
    return flask_app.test_client(), rec["id"]


def test_footage_route_returns_the_overlapping_clip(client):
    http, ep_id = client
    r = http.get("/api/weather/episodes/{}/footage".format(ep_id))
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 1
    item = body["groups"]["weather_clips"][0]
    assert item["cam_name"] == "Hof"
    assert item["video_url"] == "/api/weather/sightings/cam1__thunder__x/clip"


def test_footage_route_404s_only_for_an_unknown_episode(client):
    http, _ep_id = client
    assert http.get("/api/weather/episodes/nope/footage").status_code == 404


def test_list_rows_carry_a_footage_count(client):
    http, ep_id = client
    items = http.get("/api/weather/episodes").get_json()["items"]
    row = next(it for it in items if it["id"] == ep_id)
    assert row["footage_count"] == 1
