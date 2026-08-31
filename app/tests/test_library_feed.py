"""``library._feed.list_library_items`` + ``GET /api/library``.

Four things pinned here:

* the recap/manual-event overlap boundary (``_weather_readers._overlaps``)
  — an item touching the window edge is in, one that ends a second
  before it starts is out;
* a merge across motion + recap + manual + episode sorts newest-first
  and pages through a cursor without gaps or repeats, including a
  cross-source timestamp TIE;
* the ``label`` filter reaches ``/api/library``'s motion items and
  returns exactly the set ``/api/camera/<cam>/media`` returns for the
  same camera + window + label — not just "some events";
* the five pre-existing list endpoints keep working once the new
  ``library`` blueprint sits alongside them in the same app.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import app_state
from app.library._feed import list_library_items
from app.library._weather_readers import manual_event_candidates, recap_candidates
from app.routes import library as library_routes
from app.routes import media as media_routes
from app.routes import weather as weather_routes
from app.routes import weather_episodes as weather_episodes_routes
from app.routes import weather_manual_events as weather_manual_events_routes
from app.storage import EventStore
from app.weather_episodes._store import append_episode

CAM = "reolink_cx810_squirreltownnutbar_181"
_REAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096
_JPG = b"\xff\xd8\xff\xdb" + b"\x00" * 512


class _Store:
    def __init__(self, root):
        self.events_dir = root / "motion_detection"


def _write_event(root, cam, dt: datetime, event_id: str, **extra):
    day = dt.strftime("%Y-%m-%d")
    payload = {
        "event_id": event_id,
        "time": dt.isoformat(timespec="seconds"),
        "snapshot_relpath": "motion_detection/{}/{}/{}.jpg".format(cam, day, event_id),
    }
    payload.update(extra)
    d = root / "motion_detection" / cam / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "{}.json".format(event_id)).write_text(json.dumps(payload), encoding="utf-8")
    return payload


class _FakeWeatherService:
    def __init__(self, recaps=None, manuals=None, sightings=None):
        self._recaps = list(recaps or [])
        self._manuals = list(manuals or [])
        self._sightings = list(sightings or [])

    def list_recaps(self):
        return list(self._recaps)

    def list_manual_events(self):
        return list(self._manuals)

    def list_sightings(
        self, cam_id=None, event_type=None, since_iso=None, until_iso=None, page=0, page_size=50
    ):
        return {
            "items": list(self._sightings),
            "counts": {},
            "total": len(self._sightings),
            "page": page,
            "page_size": page_size,
        }


# ── sighting kind normalisation ──────────────────────────────────────────
#
# `weather_candidates` (weather_episodes/_footage_sources.py) is shared
# with the episode-footage index, where `kind` intentionally carries the
# specific weather type (thunder / heavy_rain / ...) for grouping. Pinned
# here: the library feed must NOT leak that raw type into `item["kind"]`
# — every weather sighting is the ONE library kind "sighting" (per this
# route's own documented KINDS vocabulary), with the specific type still
# reachable via `extra.event_type`. Regression for a bug caught while
# building the Stage-4 frontend card dispatcher: without the
# normalisation in `_windowed_candidates`, `item["kind"]` was the raw
# event_type (e.g. "thunder"), which silently broke BOTH the documented
# `/api/library` response contract AND `_category_of`'s own categories
# filter for sightings (it only ever checks `kind == "sighting"`).


def test_sighting_items_carry_the_library_kind_not_the_raw_event_type():
    ws = _FakeWeatherService(
        sightings=[
            {
                "id": "sight_1",
                "event_type": "thunder",
                "cam_id": "cam1",
                "cam_name": "Cam 1",
                "started_at": datetime(2026, 8, 30, 12, 0, 0).isoformat(timespec="seconds"),
                "duration_s": 30,
                "clip_path": "weather/cam1/thunder/sight_1.mp4",
            }
        ]
    )
    result = list_library_items(
        weather_service=ws,
        cameras=[{"id": "cam1", "name": "Cam 1"}],
        kinds=["sighting"],
        limit=10,
    )
    assert [it["kind"] for it in result["items"]] == ["sighting"]
    assert result["items"][0]["extra"]["event_type"] == "thunder"


def test_sighting_categories_filter_matches_the_items_own_event_type():
    ws = _FakeWeatherService(
        sightings=[
            {
                "id": "sight_thunder",
                "event_type": "thunder",
                "cam_id": "cam1",
                "cam_name": "Cam 1",
                "started_at": datetime(2026, 8, 30, 12, 0, 0).isoformat(timespec="seconds"),
                "duration_s": 30,
                "clip_path": "weather/cam1/thunder/sight_thunder.mp4",
            }
        ]
    )
    kept = list_library_items(
        weather_service=ws,
        cameras=[{"id": "cam1", "name": "Cam 1"}],
        kinds=["sighting"],
        categories=["thunder"],
        limit=10,
    )
    dropped = list_library_items(
        weather_service=ws,
        cameras=[{"id": "cam1", "name": "Cam 1"}],
        kinds=["sighting"],
        categories=["snow"],
        limit=10,
    )
    assert [it["id"] for it in kept["items"]] == ["sighting:sight_thunder"]
    assert dropped["items"] == []


# ── recap / manual-event overlap boundary ───────────────────────────────


def test_a_manual_event_touching_the_window_edge_is_included():
    since = datetime(2026, 8, 20, 12, 0, 0)
    until = datetime(2026, 8, 20, 13, 0, 0)
    manuals = [
        {
            "id": "m_touch_start",
            "name": "x",
            "range_start": (since - timedelta(minutes=30)).isoformat(timespec="seconds"),
            "range_end": since.isoformat(timespec="seconds"),  # ends exactly at `since`
        },
        {
            "id": "m_before",
            "name": "x",
            "range_start": (since - timedelta(hours=2)).isoformat(timespec="seconds"),
            "range_end": (since - timedelta(seconds=1)).isoformat(timespec="seconds"),
        },
    ]
    ws = _FakeWeatherService(manuals=manuals)
    ids = {c["extra"]["manual_event_id"] for c in manual_event_candidates(ws, since, until)}
    assert ids == {"m_touch_start"}


def test_a_recap_period_end_is_stretched_to_the_whole_calendar_day():
    ws = _FakeWeatherService(
        recaps=[
            {
                "id": "q2_2026",
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "clip_path": "weather/recaps/q2_2026.mp4",
            }
        ]
    )
    # 2026-06-30T23:00 is inside the stretched end-of-day, 2026-07-01T00:01 is not.
    inside = recap_candidates(ws, datetime(2026, 6, 30, 23, 0), datetime(2026, 7, 1, 0, 0))
    outside = recap_candidates(ws, datetime(2026, 7, 1, 0, 1), datetime(2026, 7, 2, 0, 0))
    assert [c["extra"]["recap_id"] for c in inside] == ["q2_2026"]
    assert outside == []


# ── cross-source merge + pagination ──────────────────────────────────────


def test_cross_source_merge_sorts_newest_first_and_pages_without_gaps_or_repeats(tmp_path):
    now = datetime.now().replace(microsecond=0)
    store = _Store(tmp_path)

    m_newest = _write_event(tmp_path, "cam1", now, "m_newest")
    m_mid = _write_event(tmp_path, "cam1", now - timedelta(minutes=30), "m_mid")
    tie_time = now - timedelta(minutes=10)
    m_tie = _write_event(tmp_path, "cam1", tie_time, "m_tie")

    ws = _FakeWeatherService(
        recaps=[
            {
                "id": "recap_1",
                "period_start": (now - timedelta(days=2)).date().isoformat(),
                "period_end": (now - timedelta(days=1)).date().isoformat(),
                "clip_path": "weather/recaps/recap_1.mp4",
            }
        ],
        manuals=[
            {
                "id": "manual_1",
                "name": "Regenguss",
                "categories": ["heavy_rain"],
                # Deliberately ties `m_tie`'s timestamp exactly.
                "range_start": tie_time.isoformat(timespec="seconds"),
                "range_end": (tie_time + timedelta(minutes=5)).isoformat(timespec="seconds"),
            }
        ],
    )
    append_episode(
        tmp_path,
        {
            "id": "ep_1",
            "started_at": (now - timedelta(minutes=20)).isoformat(timespec="seconds"),
            "ended_at": (now - timedelta(minutes=15)).isoformat(timespec="seconds"),
            "duration_min": 5,
        },
    )

    all_items: list = []
    seen_ids: set = set()
    before = None
    for _ in range(20):  # guards against a pagination bug looping forever
        page = list_library_items(
            store=store,
            weather_service=ws,
            storage_root=tmp_path,
            cameras=[{"id": "cam1", "name": "cam1"}],
            kinds=["motion", "recap", "manual", "episode"],
            before=before,
            limit=2,
        )
        for it in page["items"]:
            assert it["id"] not in seen_ids, "item repeated across pages: {}".format(it["id"])
            seen_ids.add(it["id"])
        all_items.extend(page["items"])
        before = page["next_cursor"]
        if before is None:
            break
    else:
        raise AssertionError("pagination did not terminate within 20 pages")

    expected_ids = {
        "motion:{}".format(m_newest["event_id"]),
        "motion:{}".format(m_mid["event_id"]),
        "motion:{}".format(m_tie["event_id"]),
        "recap:recap_1",
        "manual:manual_1",
        "episode:ep_1",
    }
    assert {it["id"] for it in all_items} == expected_ids
    starts = [it["start"] for it in all_items]
    assert starts == sorted(starts, reverse=True), "merged feed is not newest-first"
    assert all_items[0]["id"] == "motion:{}".format(m_newest["event_id"])


# ── label filter parity with /api/camera/<cam>/media ────────────────────


@pytest.fixture
def combined_client(monkeypatch, tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    app = Flask(__name__)
    app.register_blueprint(media_routes.bp)
    app.register_blueprint(library_routes.bp)
    app.register_blueprint(weather_routes.bp)
    app.register_blueprint(weather_episodes_routes.bp)
    app.register_blueprint(weather_manual_events_routes.bp)
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(get_review=lambda _k: None), raising=False
    )
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(app_state, "weather_service", None, raising=False)
    monkeypatch.setattr(
        app_state,
        "get_effective_config",
        lambda *a, **k: {
            "cameras": [{"id": CAM, "name": "Squirrel Town"}],
            "storage": {"media_limit_default": 500},
            "processing": {"clip_max_duration_s": 120},
        },
        raising=False,
    )
    return app.test_client()


def _clip(root: Path, event_id: str, labels: list, dt: datetime, *, cam: str = CAM) -> dict:
    """A motion event whose clip + thumbnail really are on disk, so both
    `/api/camera/<id>/media` (which additionally checks the file is
    real) and `/api/library` see the same event."""
    day = dt.strftime("%Y-%m-%d")
    media_dir = root / "motion_detection" / cam / day
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "{}.mp4".format(event_id)).write_bytes(_REAL_MP4)
    (media_dir / "{}.jpg".format(event_id)).write_bytes(_JPG)
    payload = {
        "event_id": event_id,
        "camera_id": cam,
        "time": dt.isoformat(timespec="seconds"),
        "labels": labels,
        "video_relpath": "motion_detection/{}/{}/{}.mp4".format(cam, day, event_id),
        "snapshot_relpath": "motion_detection/{}/{}/{}.jpg".format(cam, day, event_id),
    }
    (media_dir / "{}.json".format(event_id)).write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_label_filter_matches_the_camera_media_route_exactly(combined_client, tmp_storage_root):
    now = datetime.now().replace(microsecond=0)
    _clip(tmp_storage_root, "e_fox_1", ["fox"], now - timedelta(hours=4))
    _clip(tmp_storage_root, "e_fox_2", ["fox"], now - timedelta(hours=3))
    _clip(tmp_storage_root, "e_person", ["person"], now - timedelta(hours=2))
    _clip(tmp_storage_root, "e_other", ["motion"], now - timedelta(hours=1))

    window_start = (now - timedelta(hours=6)).isoformat(timespec="seconds")
    window_end = (now + timedelta(minutes=1)).isoformat(timespec="seconds")
    media_resp = combined_client.get(
        "/api/camera/{}/media?label=fox&start={}&end={}&limit=50".format(
            CAM, window_start, window_end
        )
    ).get_json()
    media_ids = {it["event_id"] for it in media_resp["items"]}

    lib_resp = combined_client.get(
        "/api/library?kinds=motion&camera_ids={}&label=fox&limit=50".format(CAM)
    ).get_json()
    lib_ids = {it["extra"]["event_id"] for it in lib_resp["items"] if it["kind"] == "motion"}

    assert media_ids == {"e_fox_1", "e_fox_2"}
    assert lib_ids == media_ids


# ── the five pre-existing endpoints are unaffected ───────────────────────


def test_existing_endpoints_still_respond_with_the_library_blueprint_registered(
    combined_client, tmp_storage_root
):
    """Not a re-test of each route's own logic (their own test files
    already cover that, unmodified, and pass — see test_media_badge_vs_
    grid.py, test_weather_episode_footage.py, test_weather_manual_
    events.py). This proves registering `library.bp` alongside them
    causes no route collision and no import-order regression."""
    now = datetime.now().replace(microsecond=0)
    _clip(tmp_storage_root, "e_smoke", ["fox"], now)

    assert combined_client.get("/api/camera/{}/media".format(CAM)).status_code == 200
    assert combined_client.get("/api/weather/sightings").status_code == 200
    assert combined_client.get("/api/weather/recaps").status_code == 200
    assert combined_client.get("/api/weather/manual-events").status_code == 200
    assert combined_client.get("/api/weather/episodes").status_code == 200
    # And the new route itself.
    assert combined_client.get("/api/library").status_code == 200
