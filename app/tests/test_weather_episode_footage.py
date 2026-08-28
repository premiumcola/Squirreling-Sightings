"""Episode record contract + the footage endpoint behind the detail page.

Everything here exercises behaviour, not source text: a synthetic
history buffer goes in, a record or a footage payload comes out, and the
assertions are on the numbers. Stub-based — no Open-Meteo call, no
camera, no scheduler, and the only weather service in sight is a
two-method fake.

The five things pinned here all had a defect:

* ``visibility`` is a peak metric, and its peak is the episode MINIMUM.
  Fog is configured as a ceiling (``vis_max_m``), so a LOW reading is
  the alarm and a plain max would store the clearest moment of the fog.
* every record carries the ``thresholds`` snapshot it was measured
  against — the archive outlives the settings that produced it.
* the footage endpoint exists at all, distinguishes "nothing to show"
  (200, empty groups) from "could not look" (a ``degraded`` marker),
  and returns the item shape the client already consumes.
* ``footage_count`` reaches a list row from the LEDGER. The list route
  must not touch a media store to produce it — it used to build a
  footage index per request, which meant reading and parsing every
  motion event JSON on disk for a number that cannot change once an
  episode's window has closed.
* the motion scan is bounded by the date FOLDER, so a two-hour window
  never opens a file belonging to another day.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import app_state
from app.routes import weather_episodes as episode_routes
from app.weather_episodes import (
    append_footage_count,
    build_footage_index,
    detect_episodes,
    episode_footage,
    episode_window,
    list_episodes,
    sweep,
)
from app.weather_episodes._motion_scan import motion_events_between

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
    # Gusts DID have no event when this test was written, and the
    # assertion here was `"wind_gusts_10m" not in thr`. That changed on
    # purpose: a 65 km/h squall could not be archived at all because the
    # only remarkable value in its window had no threshold behind it, so
    # `storm` was added at 60 km/h (just under Beaufort 8). The fixture
    # above does not configure it, so this also pins that the DEFAULT
    # carries through when the caller omits the event.
    assert thr["wind_gusts_10m"] == 60.0
    # The invariant the old assertion was really protecting, moved to a
    # field that still has no event: absent, never 0. A zero would draw a
    # "Schwelle" line along the chart's axis floor and read as a real bar
    # the value is permanently above.
    assert "cloud_cover" not in thr
    assert "sun_altitude" not in thr


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


class _CountingStore:
    """Counts media reads. The list route must make none.

    Counting, not raising: `motion_candidates` catches every exception
    from the store and logs a warning, so an exploding stub would have
    been swallowed and the test would have passed against the very code
    it is meant to fail on.
    """

    events_dir = "/nonexistent"

    def __init__(self):
        self.calls = 0

    def list_events(self, *_a, **_kw):
        self.calls += 1
        return []


class _CountingWeather(_FakeWeather):
    def __init__(self, items):
        super().__init__(items)
        self.scans = 0

    def list_sightings(self, **kw):
        self.scans += 1
        return super().list_sightings(**kw)


def test_the_list_route_reads_no_media_store(client, monkeypatch):
    """B5 turned this route into a full media-tree walk: a footage index
    per request, `EventStore.list_events` parsing EVERY event JSON before
    the `start` filter, and `since` pinned to the OLDEST archived storm
    so the window only ever widened. The operator opens this route
    constantly; it has to stay one append-only file read."""
    http, ep_id = client
    store = _CountingStore()
    weather = _CountingWeather([])
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(app_state, "weather_service", weather, raising=False)
    r = http.get("/api/weather/episodes")
    assert r.status_code == 200
    assert any(it["id"] == ep_id for it in r.get_json()["items"])
    assert store.calls == 0, "the list route walked the motion tree"
    assert weather.scans == 0, "the list route walked the sighting tree"


def test_an_unstamped_episode_has_no_count_rather_than_zero(client):
    """Absent, never 0 — the row chip stays hidden instead of claiming
    the storm was never filmed."""
    http, ep_id = client
    row = next(
        it for it in http.get("/api/weather/episodes").get_json()["items"] if it["id"] == ep_id
    )
    assert "footage_count" not in row


def test_a_stamped_count_rides_along_on_the_list_row(client, tmp_path):
    http, ep_id = client
    assert append_footage_count(tmp_path, ep_id, 7)
    row = next(
        it for it in http.get("/api/weather/episodes").get_json()["items"] if it["id"] == ep_id
    )
    assert row["footage_count"] == 7
    # Append-only: a re-stamp wins over the older one.
    assert append_footage_count(tmp_path, ep_id, 2)
    row = next(
        it for it in http.get("/api/weather/episodes").get_json()["items"] if it["id"] == ep_id
    )
    assert row["footage_count"] == 2


def test_the_footage_route_stamps_the_count_it_just_computed(client, tmp_path):
    """The scan the operator already paid for is what corrects the chip —
    and what gives an episode archived before the count existed one."""
    http, ep_id = client
    assert http.get("/api/weather/episodes/{}/footage".format(ep_id)).get_json()["total"] == 1
    row = next(
        it for it in http.get("/api/weather/episodes").get_json()["items"] if it["id"] == ep_id
    )
    assert row["footage_count"] == 1


def test_the_sweep_stamps_the_count_on_the_poll_thread(tmp_path):
    """Where the number is supposed to come from in production: once per
    episode, on the weather poll's own thread, never on a request."""
    seen = []

    def _counter(rec):
        seen.append(rec["id"])
        return 4

    result = sweep(
        tmp_path, _one_storm(), events_cfg=EVENTS, episode_cfg=TIGHT, footage_counter=_counter
    )
    assert result["stamped"] == 1
    assert len(seen) == 1
    assert list_episodes(tmp_path)[0]["footage_count"] == 4
    # Idempotent: a second sweep re-counts nothing already stamped.
    again = sweep(
        tmp_path, _one_storm(), events_cfg=EVENTS, episode_cfg=TIGHT, footage_counter=_counter
    )
    assert again["stamped"] == 0
    assert len(seen) == 1


# ── the motion scan is bounded by the date folder ──────────────────────


def _write_event(root, cam, day, hhmmss, **extra):
    payload = {
        "event_id": "{}-{}-000000".format(day.replace("-", ""), hhmmss),
        "time": "{}T{}:{}:{}".format(day, hhmmss[:2], hhmmss[2:4], hhmmss[4:6]),
        "snapshot_relpath": "motion_detection/{}/{}/x.jpg".format(cam, day),
    }
    payload.update(extra)
    d = root / "motion_detection" / cam / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "{}.json".format(payload["event_id"])).write_text(json.dumps(payload), encoding="utf-8")
    return d / "{}.json".format(payload["event_id"])


class _Store:
    def __init__(self, root):
        self.events_dir = root / "motion_detection"


def test_the_motion_scan_never_opens_a_day_outside_the_window(tmp_path, monkeypatch):
    """`EventStore.list_events` rglobs the camera tree and json-parses
    EVERY file before applying `start`, so `since_iso` pruned nothing at
    the I/O layer. The date folder is the prune."""
    for day in ("2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"):
        _write_event(tmp_path, "cam1", day, "120000")
    opened: list = []
    real_read = Path.read_text

    def _spy(self, *a, **kw):
        opened.append(self.name)
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _spy)
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-08-19T23:00:00", "2026-08-20T23:00:00"
    )
    assert [e["time"] for e in events] == ["2026-08-20T12:00:00"]
    # Two days can hold a sample in that window; the other two are never
    # opened at all — that is the whole saving.
    assert len(opened) == 2


def test_the_motion_scan_skips_events_without_media(tmp_path):
    _write_event(tmp_path, "cam1", "2026-08-20", "120000")
    _write_event(tmp_path, "cam1", "2026-08-20", "130000", snapshot_relpath=None)
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-08-20T00:00:00", "2026-08-20T23:59:59"
    )
    assert [e["time"] for e in events] == ["2026-08-20T12:00:00"]


def test_a_store_without_an_event_tree_yields_nothing(tmp_path):
    assert motion_events_between(_Store(tmp_path), "cam1", "", "") == []
    assert motion_events_between(object(), "cam1", "", "") == []
