"""Which settings a replay runs with, and how the history is kept.

The three sources (stored / current / explicit overrides) all have to
land on the same key set, or the "these two sets are identical" check
the player uses to avoid a pointless minute of CPU could never say yes.
And the history has to be append-only and capped, because the event JSON
it lives in is read on every Mediathek card render.
"""

from __future__ import annotations

from app.camera_runtime._recording._provenance import PROVENANCE_TUNING_KEYS
from app.replay import (
    REPLAY_HISTORY_CAP,
    append_replay,
    project_settings,
    resolve_replay_settings,
    settings_hash,
)

CURRENT = {
    "roi_mode": "zones",
    "track_spawn_min_score": 0.5,
    "track_continue_min_score": 0.2,
    "detection_min_score": 0.55,
    "object_filter": ["person", "cat"],
    "name": "Terrasse",  # not a tuning key — must not survive projection
    "rtsp_url": "rtsp://cam.lan/stream",  # ditto, and must never be hashed
}

STORED_TUNING = {
    "roi_mode": "off",
    "track_spawn_min_score": 0.35,
    "detection_min_score": 0.40,
    "object_filter": ["bird"],
    "label_thresholds": None,  # explicitly-null == absent
}


def _event(**over) -> dict:
    ev = {"event_id": "evt1", "camera_id": "cam1"}
    ev.update(over)
    return ev


# ── projection ────────────────────────────────────────────────────────


def test_projection_keeps_only_keys_the_snapshot_captures():
    out = project_settings(CURRENT)
    assert "name" not in out and "rtsp_url" not in out
    assert out["roi_mode"] == "zones"
    assert set(out).issubset(set(PROVENANCE_TUNING_KEYS))


def test_projection_drops_explicit_nulls_so_absent_and_null_hash_alike():
    assert project_settings({"roi_mode": None}) == {}
    assert settings_hash(project_settings({"roi_mode": None})) == settings_hash(
        project_settings({})
    )


def test_projection_of_nothing_is_empty_not_an_error():
    assert project_settings(None) == {}


# ── hashing ───────────────────────────────────────────────────────────


def test_hash_is_stable_across_key_order():
    assert settings_hash({"a": 1, "b": 2}) == settings_hash({"b": 2, "a": 1})


def test_hash_changes_when_a_value_changes():
    assert settings_hash({"track_spawn_min_score": 0.5}) != settings_hash(
        {"track_spawn_min_score": 0.6}
    )


def test_hash_is_short_enough_to_show_in_the_ui():
    assert len(settings_hash(CURRENT)) == 12


def test_hash_survives_a_value_json_cannot_encode():
    # An archived snapshot carrying a stray object must not blow up a
    # replay mid-run; the fingerprint degrades to its repr instead.
    assert len(settings_hash({"weird": object()})) == 12


# ── resolution ────────────────────────────────────────────────────────


def test_stored_replays_the_events_own_provenance():
    ev = _event(provenance={"schema": 1, "tuning": STORED_TUNING})
    out = resolve_replay_settings(ev, CURRENT, "stored")
    assert out["source"] == "stored" and out["basis"] == "provenance"
    assert out["cfg"]["track_spawn_min_score"] == 0.35
    assert out["cfg"]["object_filter"] == ["bird"]
    assert out["note"] is None


def test_current_replays_the_cameras_live_profile():
    ev = _event(provenance={"tuning": STORED_TUNING})
    out = resolve_replay_settings(ev, CURRENT, "current")
    assert out["source"] == "current"
    assert out["cfg"]["track_spawn_min_score"] == 0.5


def test_stored_and_current_hash_the_same_when_the_camera_never_changed():
    ev = _event(provenance={"tuning": dict(CURRENT)})
    stored = resolve_replay_settings(ev, CURRENT, "stored")
    current = resolve_replay_settings(ev, CURRENT, "current")
    assert stored["hash"] == current["hash"], "identical sets must be recognisable as identical"


def test_a_pre_provenance_event_falls_back_and_says_so():
    ev = _event(
        recording_settings={
            "conf_thresh_general": 0.42,
            "conf_thresh_per_class": {"bird": 0.3},
            "object_filter": ["bird"],
            "sample_interval_ms": 500,
            "confirm_n": 4,
            "confirm_seconds": 6,
        }
    )
    out = resolve_replay_settings(ev, CURRENT, "stored")
    assert out["basis"] == "recording_settings"
    assert out["note"], "the operator must be told the basis is partial"
    assert out["cfg"]["detection_min_score"] == 0.42
    assert out["cfg"]["label_thresholds"] == {"bird": 0.3}
    assert out["cfg"]["frame_interval_ms"] == 500
    assert out["cfg"]["confirmation_window"] == {"global": {"n": 4, "seconds": 6}}


def test_an_event_with_no_settings_at_all_falls_back_to_current_and_says_so():
    out = resolve_replay_settings(_event(), CURRENT, "stored")
    assert out["basis"] == "current" and out["note"]
    assert out["cfg"]["track_spawn_min_score"] == 0.5


def test_an_empty_provenance_block_is_treated_as_absent():
    out = resolve_replay_settings(_event(provenance={"tuning": {}}), CURRENT, "stored")
    assert out["basis"] == "current"


def test_explicit_overrides_land_on_top_of_the_current_profile():
    out = resolve_replay_settings(_event(), CURRENT, {"tuning": {"track_spawn_min_score": 0.9}})
    assert out["source"] == "custom" and out["basis"] == "current+overrides"
    assert out["cfg"]["track_spawn_min_score"] == 0.9
    assert out["cfg"]["roi_mode"] == "zones", "unmentioned knobs keep the current value"
    assert out["overridden"] == ["track_spawn_min_score"]


def test_a_bare_override_dict_works_without_the_tuning_wrapper():
    out = resolve_replay_settings(_event(), CURRENT, {"detection_min_score": 0.1})
    assert out["cfg"]["detection_min_score"] == 0.1
    assert out["overridden"] == ["detection_min_score"]


def test_overrides_outside_the_captured_key_set_are_ignored():
    # A sweep must not be able to smuggle an rtsp_url into a replay.
    out = resolve_replay_settings(_event(), CURRENT, {"rtsp_url": "rtsp://evil/"})
    assert "rtsp_url" not in out["cfg"]
    assert out["overridden"] == []


def test_two_different_sweeps_get_different_hashes():
    a = resolve_replay_settings(_event(), CURRENT, {"track_spawn_min_score": 0.3})
    b = resolve_replay_settings(_event(), CURRENT, {"track_spawn_min_score": 0.4})
    assert a["hash"] != b["hash"]


def test_resolution_does_not_mutate_the_cameras_live_config():
    before = dict(CURRENT)
    resolve_replay_settings(_event(), CURRENT, {"track_spawn_min_score": 0.9})
    assert CURRENT == before


# ── history ───────────────────────────────────────────────────────────


class _Store:
    """Minimal EventStore stand-in: get/update one document."""

    def __init__(self, event):
        self.event = event

    def get_event(self, _cam, _eid):
        return dict(self.event)

    def update_event(self, _cam, _eid, payload):
        self.event = payload
        return True


def test_history_is_capped_at_the_last_runs():
    store = _Store({"event_id": "e", "detections": [{"label": "bird"}]})
    for i in range(REPLAY_HISTORY_CAP + 3):
        history = append_replay(store, "cam1", "e", {"settings_hash": f"h{i}"})
    assert len(history) == REPLAY_HISTORY_CAP
    assert history[-1]["settings_hash"] == f"h{REPLAY_HISTORY_CAP + 2}"
    assert history[0]["settings_hash"] == "h3", "oldest runs drop off the front"


def test_storing_a_replay_leaves_the_events_own_findings_alone():
    original = {
        "event_id": "e",
        "detections": [{"label": "bird", "score": 0.6}],
        "labels": ["bird"],
    }
    store = _Store(dict(original))
    append_replay(store, "cam1", "e", {"settings_hash": "h"})
    assert store.event["detections"] == original["detections"]
    assert store.event["labels"] == original["labels"]
    assert len(store.event["replays"]) == 1


def test_a_store_failure_costs_the_archive_copy_not_the_answer():
    class _Broken(_Store):
        def update_event(self, *_a, **_k):
            raise OSError("disk full")

    assert append_replay(_Broken({"event_id": "e"}), "cam1", "e", {}) == []


def test_a_missing_event_yields_an_empty_history_rather_than_raising():
    class _Empty(_Store):
        def get_event(self, *_a):
            return None

    assert append_replay(_Empty({}), "cam1", "gone", {}) == []
