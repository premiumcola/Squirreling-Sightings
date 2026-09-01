"""``library._feed``'s outdoor-aware camera scoping.

The operator's bug report: an INDOOR camera ("Werkstatt") scoped down
to in the merged Mediathek grid still showed storm-episode / recap /
manual-event cards — camera-agnostic weather content (``cam_id=""``)
that ``_cam_scoped_ok`` used to wave through unconditionally past any
camera filter (see its old comment: "never hidden by a camera
filter"). The fix adds a per-camera ``outdoor`` flag
(``CAMERA_SCHEMA["outdoor"]``, default True) and gates those cam_id=""
items on whether the ACTIVE camera filter includes at least one
outdoor camera.

Four things pinned here:

* a recap/episode/manual item is excluded when every camera in the
  active filter is indoor;
* included when at least one camera in the filter is outdoor;
* included when no camera filter is active at all ("Alles gemischt");
* a real-``cam_id`` item (a sighting) is unaffected either way — its
  existing per-camera match is untouched by the outdoor rule.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.library._feed import _outdoor_scope_ok, list_library_items
from app.weather_episodes._store import append_episode

from .test_library_feed import _FakeWeatherService

_INDOOR = {"id": "werkstatt", "name": "Werkstatt", "outdoor": False}
_OUTDOOR = {"id": "garten", "name": "Garten", "outdoor": True}
_LEGACY_NO_FLAG = {"id": "legacy", "name": "Legacy Cam"}  # pre-migration: no key at all


def _weather_service_with_manual(start: datetime):
    return _FakeWeatherService(
        manuals=[
            {
                "id": "man_storm",
                "name": "Starker Regen mit vielen Blitzen",
                "categories": ["heavy_rain"],
                "range_start": start.isoformat(timespec="seconds"),
                "range_end": (start + timedelta(minutes=5)).isoformat(timespec="seconds"),
            }
        ]
    )


# ── _outdoor_scope_ok unit coverage ───────────────────────────────────────


def test_outdoor_scope_ok_true_when_no_camera_filter_active():
    assert _outdoor_scope_ok([_INDOOR], None) is True
    assert _outdoor_scope_ok([_INDOOR], []) is True


def test_outdoor_scope_ok_false_when_every_filtered_camera_is_indoor():
    assert _outdoor_scope_ok([_INDOOR, _OUTDOOR], ["werkstatt"]) is False


def test_outdoor_scope_ok_true_when_at_least_one_filtered_camera_is_outdoor():
    assert _outdoor_scope_ok([_INDOOR, _OUTDOOR], ["werkstatt", "garten"]) is True


def test_outdoor_scope_ok_defaults_unknown_or_unflagged_camera_to_outdoor():
    # An id in the filter that isn't in `cameras` at all (e.g. archived)
    # and a legacy camera missing the `outdoor` key both default to
    # outdoor — an unknown flag should never silently hide weather
    # content.
    assert _outdoor_scope_ok([_INDOOR], ["archived_cam_not_in_list"]) is True
    assert _outdoor_scope_ok([_LEGACY_NO_FLAG], ["legacy"]) is True


# ── end-to-end via list_library_items ─────────────────────────────────────


def test_manual_weather_event_excluded_when_scope_is_indoor_only():
    now = datetime.now().replace(microsecond=0)
    ws = _weather_service_with_manual(now)
    result = list_library_items(
        weather_service=ws,
        cameras=[_INDOOR, _OUTDOOR],
        camera_ids=["werkstatt"],
        kinds=["manual"],
        limit=10,
    )
    assert result["items"] == []


def test_manual_weather_event_included_when_scope_has_an_outdoor_camera():
    now = datetime.now().replace(microsecond=0)
    ws = _weather_service_with_manual(now)
    result = list_library_items(
        weather_service=ws,
        cameras=[_INDOOR, _OUTDOOR],
        camera_ids=["werkstatt", "garten"],
        kinds=["manual"],
        limit=10,
    )
    assert [it["id"] for it in result["items"]] == ["manual:man_storm"]


def test_manual_weather_event_included_when_no_camera_filter_at_all():
    """'Alles gemischt' — omitting camera_ids keeps showing everything,
    unchanged, even though every configured camera is indoor."""
    now = datetime.now().replace(microsecond=0)
    ws = _weather_service_with_manual(now)
    result = list_library_items(
        weather_service=ws,
        cameras=[_INDOOR],
        kinds=["manual"],
        limit=10,
    )
    assert [it["id"] for it in result["items"]] == ["manual:man_storm"]


def test_episode_and_recap_are_also_excluded_for_an_indoor_only_scope(tmp_path):
    now = datetime.now().replace(microsecond=0)
    append_episode(
        tmp_path,
        {
            "id": "ep_gewitter",
            "started_at": (now - timedelta(minutes=10)).isoformat(timespec="seconds"),
            "ended_at": (now - timedelta(minutes=5)).isoformat(timespec="seconds"),
            "duration_min": 5,
        },
    )
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
    result = list_library_items(
        weather_service=ws,
        storage_root=tmp_path,
        cameras=[_INDOOR],
        camera_ids=["werkstatt"],
        kinds=["recap", "episode"],
        limit=10,
    )
    assert result["items"] == []


def test_sighting_with_real_cam_id_is_unaffected_by_the_outdoor_rule(tmp_path):
    """A sighting always carries a real cam_id and is scoped by THAT —
    the outdoor rule must never touch this path. A thunder sighting
    recorded on the outdoor camera stays visible even when the active
    filter is indoor-only + outdoor-only mixed, and a sighting recorded
    on the INDOOR camera itself is included when that indoor camera is
    the one actually selected (unrelated to the weather-relevance
    rule — the operator explicitly asked to see ITS OWN footage)."""
    now = datetime.now().replace(microsecond=0)
    ws = _FakeWeatherService(
        sightings=[
            {
                "id": "s_outdoor",
                "event_type": "thunder",
                "cam_id": "garten",
                "cam_name": "Garten",
                "started_at": now.isoformat(timespec="seconds"),
                "duration_s": 30,
                "clip_path": "weather/garten/thunder/s_outdoor.mp4",
            },
            {
                "id": "s_indoor",
                "event_type": "thunder",
                "cam_id": "werkstatt",
                "cam_name": "Werkstatt",
                "started_at": now.isoformat(timespec="seconds"),
                "duration_s": 30,
                "clip_path": "weather/werkstatt/thunder/s_indoor.mp4",
            },
        ]
    )
    # Filter scoped to ONLY the indoor camera: its own sighting is in,
    # the outdoor camera's sighting is out — plain per-camera matching,
    # not the outdoor rule.
    result = list_library_items(
        weather_service=ws,
        cameras=[_INDOOR, _OUTDOOR],
        camera_ids=["werkstatt"],
        kinds=["sighting"],
        limit=10,
    )
    assert [it["id"] for it in result["items"]] == ["sighting:s_indoor"]
