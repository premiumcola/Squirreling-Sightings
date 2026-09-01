"""``library._facets.count_library_facets`` + ``GET /api/library/facets``.

Four things pinned here:

* each dimension's counts are correct against hand-built fixtures;
* toggling a filter in one dimension changes ANOTHER dimension's
  counts but leaves its own value the honest "as if I weren't
  selected" number, not a collapsed self-count;
* ``total`` matches an unpaginated ``list_library_items`` call's full
  eligible-count for the same filters;
* the ``labels``-narrows-non-motion-kinds bug fix (see
  ``test_library_feed.py``) holds for the facets path too — a
  ``labels`` filter with no explicit ``kinds`` must not tally an
  unrelated episode/sighting into ``categories``/``cameras`` either.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from flask import Flask

from app import app_state
from app.library._facets import count_library_facets
from app.library._feed import list_library_items
from app.routes import library as library_routes
from app.weather_episodes._store import append_episode

from .test_library_feed import CAM, _FakeWeatherService, _Store, _write_event

_CAMERAS = [
    {"id": "cam1", "name": "Cam 1"},
    {"id": "cam2", "name": "Cam 2"},
]


def _episode(tmp_path, eid: str, start: datetime, minutes: int = 5, **extra):
    rec = {
        "id": eid,
        "started_at": start.isoformat(timespec="seconds"),
        "ended_at": (start + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
        "duration_min": minutes,
    }
    rec.update(extra)
    append_episode(tmp_path, rec)


def _sighting(sid: str, event_type: str, cam_id: str, start: datetime, duration_s: int = 30):
    return {
        "id": sid,
        "event_type": event_type,
        "cam_id": cam_id,
        "cam_name": cam_id,
        "started_at": start.isoformat(timespec="seconds"),
        "duration_s": duration_s,
        "clip_path": "weather/{}/{}/{}.mp4".format(cam_id, event_type, sid),
    }


# ── per-dimension counts against hand-built fixtures ─────────────────────


def test_cameras_dimension_counts_motion_and_sighting_items_per_camera(tmp_path):
    now = datetime.now().replace(microsecond=0)
    store = _Store(tmp_path)
    _write_event(tmp_path, "cam1", now, "e1", labels=["cat"])
    _write_event(tmp_path, "cam1", now - timedelta(minutes=1), "e2", labels=["bird"])
    _write_event(tmp_path, "cam2", now - timedelta(minutes=2), "e3", labels=["cat"])
    ws = _FakeWeatherService(
        sightings=[_sighting("s1", "thunder", "cam2", now - timedelta(minutes=3))]
    )

    facets = count_library_facets(
        store=store, weather_service=ws, storage_root=tmp_path, cameras=_CAMERAS
    )
    assert facets["cameras"] == {"cam1": 2, "cam2": 2}


def test_labels_dimension_tallies_motion_items_only_from_labels_and_species_fields(tmp_path):
    now = datetime.now().replace(microsecond=0)
    store = _Store(tmp_path)
    _write_event(tmp_path, "cam1", now, "e_cat", labels=["cat"])
    _write_event(
        tmp_path,
        "cam1",
        now - timedelta(minutes=1),
        "e_bird_species",
        cat_name=None,
        bird_species="robin",
        labels=[],
    )
    _write_event(tmp_path, "cam1", now - timedelta(minutes=2), "e_multi", labels=["cat", "person"])
    append_episode(
        tmp_path,
        {
            "id": "ep_1",
            "started_at": (now - timedelta(minutes=4)).isoformat(timespec="seconds"),
            "ended_at": (now - timedelta(minutes=3)).isoformat(timespec="seconds"),
            "duration_min": 1,
        },
    )

    facets = count_library_facets(
        store=store, weather_service=None, storage_root=tmp_path, cameras=_CAMERAS
    )
    assert facets["labels"] == {"cat": 2, "person": 1, "robin": 1}


def test_categories_dimension_tallies_sighting_manual_episode_via_category_of(tmp_path):
    now = datetime.now().replace(microsecond=0)
    _episode(tmp_path, "ep_thunder", now - timedelta(minutes=1), auto_class="thunder")
    _episode(tmp_path, "ep_snow", now - timedelta(minutes=2), auto_class="snow")
    ws = _FakeWeatherService(
        sightings=[_sighting("s_thunder", "thunder", "cam1", now - timedelta(minutes=3))],
        manuals=[
            {
                "id": "m1",
                "name": "x",
                "categories": ["snow"],
                "range_start": (now - timedelta(minutes=5)).isoformat(timespec="seconds"),
                "range_end": (now - timedelta(minutes=4)).isoformat(timespec="seconds"),
            }
        ],
    )

    facets = count_library_facets(
        store=None, weather_service=ws, storage_root=tmp_path, cameras=_CAMERAS
    )
    assert facets["categories"] == {"thunder": 2, "snow": 2}


# ── faceted semantics: other dimensions adjust, own dimension doesn't ────


def test_selecting_a_camera_narrows_the_labels_facet_but_not_the_cameras_facet(tmp_path):
    now = datetime.now().replace(microsecond=0)
    store = _Store(tmp_path)
    _write_event(tmp_path, "cam1", now, "e1", labels=["cat"])
    _write_event(tmp_path, "cam2", now - timedelta(minutes=1), "e2", labels=["bird"])

    no_filter = count_library_facets(
        store=store, weather_service=None, storage_root=tmp_path, cameras=_CAMERAS
    )
    cam1_only = count_library_facets(
        store=store,
        weather_service=None,
        storage_root=tmp_path,
        cameras=_CAMERAS,
        camera_ids=["cam1"],
    )
    # Labels facet narrows to what THIS camera actually has...
    assert no_filter["labels"] == {"cat": 1, "bird": 1}
    assert cam1_only["labels"] == {"cat": 1}
    # ...but the cameras facet itself stays the full picture — a chip
    # already toggled on (cam1) must not collapse to a self-count that
    # hides its sibling camera's chip.
    assert cam1_only["cameras"] == {"cam1": 1, "cam2": 1}


def test_selecting_a_label_narrows_the_cameras_facet_but_not_the_labels_facet(tmp_path):
    now = datetime.now().replace(microsecond=0)
    store = _Store(tmp_path)
    _write_event(tmp_path, "cam1", now, "e1", labels=["cat"])
    _write_event(tmp_path, "cam2", now - timedelta(minutes=1), "e2", labels=["bird"])

    cat_only = count_library_facets(
        store=store,
        weather_service=None,
        storage_root=tmp_path,
        cameras=_CAMERAS,
        labels=["cat"],
    )
    assert cat_only["cameras"] == {"cam1": 1}
    assert cat_only["labels"] == {"cat": 1, "bird": 1}


# ── total matches an unpaginated list_library_items eligible-count ───────


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"camera_ids": ["cam1"]},
        {"labels": ["cat"]},
        {"camera_ids": ["cam1"], "labels": ["cat"]},
    ],
)
def test_total_matches_list_library_items_full_eligible_count(tmp_path, kwargs):
    now = datetime.now().replace(microsecond=0)
    store = _Store(tmp_path)
    _write_event(tmp_path, "cam1", now, "e1", labels=["cat"])
    _write_event(tmp_path, "cam1", now - timedelta(minutes=1), "e2", labels=["bird"])
    _write_event(tmp_path, "cam2", now - timedelta(minutes=2), "e3", labels=["cat"])

    facets = count_library_facets(
        store=store, weather_service=None, storage_root=tmp_path, cameras=_CAMERAS, **kwargs
    )
    full = list_library_items(
        store=store,
        weather_service=None,
        storage_root=tmp_path,
        cameras=_CAMERAS,
        limit=1000,
        **kwargs,
    )
    assert facets["total"] == len(full["items"])


# ── labels-narrows-non-motion-kinds bug fix, via the facets path ─────────


def test_labels_filter_excludes_unrelated_categories_and_non_motion_cameras(tmp_path):
    now = datetime.now().replace(microsecond=0)
    store = _Store(tmp_path)
    _write_event(tmp_path, "cam1", now, "e_cat", labels=["cat"])
    append_episode(
        tmp_path,
        {
            "id": "ep_storm",
            "started_at": (now - timedelta(minutes=1)).isoformat(timespec="seconds"),
            "ended_at": now.isoformat(timespec="seconds"),
            "duration_min": 1,
            "auto_class": "thunder",
        },
    )
    ws = _FakeWeatherService(
        sightings=[_sighting("s1", "thunder", "cam2", now - timedelta(minutes=2))]
    )

    facets = count_library_facets(
        store=store,
        weather_service=ws,
        storage_root=tmp_path,
        cameras=_CAMERAS,
        labels=["cat"],
    )
    # No `kinds` given + a `labels` filter narrows scope to motion —
    # the storm episode and the cam2 sighting must not surface anywhere.
    assert facets["categories"] == {}
    assert facets["cameras"] == {"cam1": 1}
    assert facets["total"] == 1


# ── outdoor-scope rule (indoor camera ⇒ weather facets suppressed) ───────
#
# Regression for the operator report: scoping the Mediathek down to a
# single indoor camera ("Werkstatt") still showed non-zero counts for
# weather category chips ("Gewitter"/"Starkregen") the view could never
# actually produce a result for. `_cam_scoped_ok`'s outdoor-aware
# behaviour must reach the facets path too, not just `/api/library`
# itself — pinned via both the `categories` dimension AND `total`.

_INDOOR_CAM = {"id": "werkstatt", "name": "Werkstatt", "outdoor": False}
_OUTDOOR_CAM = {"id": "garten", "name": "Garten", "outdoor": True}


def test_categories_facet_is_empty_for_an_indoor_only_camera_scope(tmp_path):
    now = datetime.now().replace(microsecond=0)
    ws = _FakeWeatherService(
        manuals=[
            {
                "id": "m_storm",
                "name": "Starker Regen mit vielen Blitzen",
                "categories": ["heavy_rain"],
                "range_start": (now - timedelta(minutes=5)).isoformat(timespec="seconds"),
                "range_end": now.isoformat(timespec="seconds"),
            }
        ]
    )
    facets = count_library_facets(
        weather_service=ws,
        cameras=[_INDOOR_CAM, _OUTDOOR_CAM],
        camera_ids=["werkstatt"],
    )
    assert facets["categories"] == {}
    assert facets["total"] == 0


def test_categories_facet_is_populated_once_scope_includes_an_outdoor_camera(tmp_path):
    now = datetime.now().replace(microsecond=0)
    ws = _FakeWeatherService(
        manuals=[
            {
                "id": "m_storm",
                "name": "Starker Regen mit vielen Blitzen",
                "categories": ["heavy_rain"],
                "range_start": (now - timedelta(minutes=5)).isoformat(timespec="seconds"),
                "range_end": now.isoformat(timespec="seconds"),
            }
        ]
    )
    facets = count_library_facets(
        weather_service=ws,
        cameras=[_INDOOR_CAM, _OUTDOOR_CAM],
        camera_ids=["werkstatt", "garten"],
    )
    assert facets["categories"] == {"heavy_rain": 1}
    assert facets["total"] == 1


def test_categories_facet_unaffected_when_no_camera_filter_is_active(tmp_path):
    """'Alles gemischt' — the outdoor rule only applies once a real
    camera_ids filter is active."""
    now = datetime.now().replace(microsecond=0)
    ws = _FakeWeatherService(
        manuals=[
            {
                "id": "m_storm",
                "name": "x",
                "categories": ["heavy_rain"],
                "range_start": (now - timedelta(minutes=5)).isoformat(timespec="seconds"),
                "range_end": now.isoformat(timespec="seconds"),
            }
        ]
    )
    facets = count_library_facets(weather_service=ws, cameras=[_INDOOR_CAM])
    assert facets["categories"] == {"heavy_rain": 1}
    assert facets["total"] == 1


# ── GET /api/library/facets route ─────────────────────────────────────────


@pytest.fixture
def facets_client(monkeypatch, tmp_storage_root):
    from app.storage import EventStore

    store = EventStore(str(tmp_storage_root))
    app = Flask(__name__)
    app.register_blueprint(library_routes.bp)
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(app_state, "weather_service", None, raising=False)
    monkeypatch.setattr(
        app_state,
        "get_effective_config",
        lambda *a, **k: {"cameras": [{"id": CAM, "name": "Squirrel Town"}]},
        raising=False,
    )
    return app.test_client()


def test_facets_route_responds_with_the_documented_shape(facets_client, tmp_storage_root):
    now = datetime.now().replace(microsecond=0)
    day = now.strftime("%Y-%m-%d")
    media_dir = tmp_storage_root / "motion_detection" / CAM / day
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "e1.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
    (media_dir / "e1.jpg").write_bytes(b"\xff\xd8\xff\xdb" + b"\x00" * 512)
    (media_dir / "e1.json").write_text(
        __import__("json").dumps(
            {
                "event_id": "e1",
                "camera_id": CAM,
                "time": now.isoformat(timespec="seconds"),
                "labels": ["fox"],
                "video_relpath": "motion_detection/{}/{}/e1.mp4".format(CAM, day),
                "snapshot_relpath": "motion_detection/{}/{}/e1.jpg".format(CAM, day),
            }
        ),
        encoding="utf-8",
    )

    resp = facets_client.get("/api/library/facets?labels=fox")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"cameras", "labels", "categories", "total"}
    assert body["labels"] == {"fox": 1}
    assert body["cameras"] == {CAM: 1}
    assert body["total"] == 1


def test_facets_route_singular_label_param_matches_labels_param(facets_client):
    a = facets_client.get("/api/library/facets?label=fox").get_json()
    b = facets_client.get("/api/library/facets?labels=fox").get_json()
    assert a == b
