"""The replay endpoint, end to end, with no video decoder and no TPU.

`open_video` and `sample_clip` are the only two OpenCV callers in the
post-clip package, so stubbing exactly those two gives a full-fidelity
run of everything else — the real threshold resolution, the real
cleanup sweeps, the real payload serialisation, the real diff and the
real persistence. What is left untested here is cv2 itself, which is
the correct thing to leave out of a stub-based suite.

The load-bearing guarantee this file exists to hold: a replay never
rewrites the event's own findings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

from app import app_state
from app.routes import replay as replay_routes
from app.storage import EventStore
from app.tracker_core import Track, TrackerState
from app.tracking_worker import tracks_path_for

CAM = "cam_test"
EVENT_ID = "20260522T120000_cam_test"
REL = f"motion_detection/{CAM}/2026-05-22/{EVENT_ID}.mp4"

CAM_CFG = {
    "roi_mode": "off",
    "alarm_profile": "medium",
    "track_spawn_min_score": 0.5,
    "track_continue_min_score": 0.2,
    "detection_min_score": 0.55,
}

STORED_TUNING = dict(CAM_CFG, track_spawn_min_score=0.25, detection_min_score=0.3)


# ── stubs ─────────────────────────────────────────────────────────────


class _Detector:
    available = True
    mode = "cpu"
    reason = "prefer_cpu"
    active_model_path = "/models/coco_ssd_mobilenet_v2.tflite"


class _Cap:
    """The handle `open_video` hands back. Only `release()` is reached
    once `sample_clip` is stubbed out."""

    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


class _Worker:
    """Stands in for the TrackingWorker singleton. Only `detector()` is
    reached — the replay borrows the worker's CPU-pinned instance and
    never enqueues anything."""

    def __init__(self):
        self.detector_calls = 0

    def detector(self):
        self.detector_calls += 1
        return _Detector()


def _samples(n, *, x=100, score=0.8):
    return [
        {
            "f": i * 25,
            "t": float(i),
            "bbox": {"x1": x + i * 30, "y1": 300, "x2": x + i * 30 + 60, "y2": 440},
            "score": score,
            "source": "detect",
            "label": "person",
        }
        for i in range(n)
    ]


def _state(tracks):
    st = TrackerState()
    st.closed = list(tracks)
    st.active = []
    return st


def _track(label, samples, track_id="t1"):
    tr = Track(track_id, label, samples[0]["f"])
    tr.samples = list(samples)
    tr.first_frame = samples[0]["f"]
    tr.last_frame = samples[-1]["f"]
    tr.best_score = max(float(s["score"]) for s in samples)
    tr.best_frame_idx = max(samples, key=lambda s: s["score"])["f"]
    return tr


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def event_doc() -> dict:
    return {
        "event_id": EVENT_ID,
        "id": EVENT_ID,
        "camera_id": CAM,
        "ts_iso": "2026-05-22T12:00:00",
        "labels": ["person"],
        "video_relpath": REL,
        "detections": [
            {"label": "person", "score": 0.9, "bbox": {"x1": 100, "y1": 300, "x2": 160, "y2": 440}}
        ],
        "provenance": {
            "schema": 1,
            "camera": {"id": CAM, "alarm_profile": "hard"},
            "tuning": STORED_TUNING,
        },
    }


@pytest.fixture
def store(tmp_storage_root: Path, event_doc: dict) -> EventStore:
    st = EventStore(str(tmp_storage_root))
    st.add_event(CAM, event_doc)
    vid = tmp_storage_root / REL
    vid.parent.mkdir(parents=True, exist_ok=True)
    vid.write_bytes(b"not really an mp4")
    return st


@pytest.fixture
def worker() -> _Worker:
    return _Worker()


@pytest.fixture
def walked() -> dict:
    """Records what the stubbed frame walk was asked to do, so a test
    can assert the bound was applied and the settings arrived."""
    return {}


@pytest.fixture
def client(monkeypatch, store, tmp_storage_root: Path, worker, walked):
    from app.replay import _run

    def fake_open_video(_path, *, precision="standard"):
        walked["precision"] = precision
        return _Cap(), {
            "fps": 25.0,
            "frame_count": 25_000,  # a very long clip — the cap must bite
            "duration_s": 1000.0,
            "sample_interval": 25,
            "frame_w": 1920,
            "frame_h": 1080,
        }

    def fake_sample_clip(_cap, _meta, _det, allowed, **kw):
        walked.update(kw)
        walked["allowed"] = allowed
        tracks = walked.get("tracks")
        if tracks is None:
            tracks = [_track("person", _samples(6))]
        return _state(tracks)

    monkeypatch.setattr(_run, "open_video", fake_open_video)
    monkeypatch.setattr(_run, "sample_clip", fake_sample_clip)
    monkeypatch.setattr(replay_routes, "singleton", lambda: worker)
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(app_state, "get_camera_cfg", lambda _cid: dict(CAM_CFG), raising=False)

    app = Flask(__name__)
    app.register_blueprint(replay_routes.bp)
    return app.test_client()


def _post(client, settings="stored"):
    return client.post(f"/api/event/{EVENT_ID}/replay", json={"settings": settings})


# ── preflight ─────────────────────────────────────────────────────────


def test_preflight_reports_both_candidate_sets_without_running_anything(client, worker):
    r = client.get(f"/api/event/{EVENT_ID}/replay")
    assert r.status_code == 200
    body = r.get_json()
    assert body["stored"]["basis"] == "provenance"
    assert body["current"]["basis"] == "current"
    assert body["identical"] is False
    assert worker.detector_calls == 0, "a preflight must not touch the detector"


def test_preflight_reports_identical_when_the_camera_never_changed(client, store, event_doc):
    ev = store.get_event(CAM, EVENT_ID)
    ev["provenance"]["tuning"] = dict(CAM_CFG)
    store.update_event(CAM, EVENT_ID, ev)
    assert client.get(f"/api/event/{EVENT_ID}/replay").get_json()["identical"] is True


def test_preflight_on_an_unknown_event_is_a_404(client):
    assert client.get("/api/event/nope/replay").status_code == 404


# ── running ───────────────────────────────────────────────────────────


def test_stored_replay_uses_the_thresholds_on_record(client, walked):
    assert _post(client, "stored").status_code == 200
    # track_continue_min_score 0.2 is the floor; the worker's convention
    # of spawning at the floor is preserved.
    assert walked["floor_score"] == 0.2
    assert walked["spawn_score"] == 0.2


def test_current_replay_uses_the_live_profile_not_the_stored_one(client, store, walked):
    ev = store.get_event(CAM, EVENT_ID)
    ev["provenance"]["tuning"] = dict(CAM_CFG, track_continue_min_score=0.05)
    store.update_event(CAM, EVENT_ID, ev)
    r = _post(client, "current")
    assert r.status_code == 200
    assert walked["floor_score"] == 0.2, "the live 0.2, not the stored 0.05"
    assert r.get_json()["settings"]["source"] == "current"


def test_explicit_overrides_reach_the_pipeline(client, walked):
    r = client.post(
        f"/api/event/{EVENT_ID}/replay",
        json={"settings": {"tuning": {"track_continue_min_score": 0.05}}},
    )
    assert r.status_code == 200
    assert walked["floor_score"] == 0.05
    assert r.get_json()["settings"]["source"] == "custom"
    assert r.get_json()["settings"]["overridden"] == ["track_continue_min_score"]


def test_the_object_filter_on_record_is_applied(client, store, walked):
    ev = store.get_event(CAM, EVENT_ID)
    ev["provenance"]["tuning"] = dict(STORED_TUNING, object_filter=["bird"])
    store.update_event(CAM, EVENT_ID, ev)
    _post(client, "stored")
    assert walked["allowed"] == {"bird"}


def test_the_work_is_bounded_and_the_response_says_by_how_much(client):
    body = _post(client).get_json()
    assert body["frames_available"] == 1000, "25000 frames at a 25-frame stride"
    assert body["frames_analysed"] == 240, "the cap, not the whole clip"
    assert body["truncated"] is True


def test_the_cap_is_passed_down_to_the_frame_walker(client, walked):
    _post(client)
    assert walked["max_samples"] == 240


def test_a_short_clip_is_not_reported_as_truncated(client, monkeypatch):
    from app.replay import _run

    monkeypatch.setattr(
        _run,
        "open_video",
        lambda _p, *, precision="standard": (
            _Cap(),
            {
                "fps": 25.0,
                "frame_count": 250,
                "duration_s": 10.0,
                "sample_interval": 25,
                "frame_w": 1920,
                "frame_h": 1080,
            },
        ),
    )
    body = _post(client).get_json()
    assert (body["frames_available"], body["frames_analysed"]) == (10, 10)
    assert body["truncated"] is False


def test_an_unreadable_clip_is_a_422_not_a_500(client, monkeypatch):
    from app.replay import _run

    monkeypatch.setattr(
        _run,
        "open_video",
        lambda _p, *, precision="standard": (None, {"fps": 0.0, "frame_count": 0}),
    )
    r = _post(client)
    assert r.status_code == 422 and r.get_json()["ok"] is False


def test_no_worker_means_503_rather_than_building_a_second_detector(client, monkeypatch):
    monkeypatch.setattr(replay_routes, "singleton", lambda: None)
    assert _post(client).status_code == 503


def test_a_nonsense_settings_value_is_rejected(client):
    r = client.post(f"/api/event/{EVENT_ID}/replay", json={"settings": "yesterday"})
    assert r.status_code == 400


def test_the_replay_borrows_the_workers_detector(client, worker):
    _post(client)
    assert worker.detector_calls == 1


# ── the comparison ────────────────────────────────────────────────────


def test_the_response_carries_both_sides_and_the_diff(client):
    body = _post(client).get_json()["comparison"]
    assert body["before"]["detection_count"] == 1
    assert body["after"]["detection_count"] == 1
    assert set(body["diff"]) == {"detections", "tracks"}
    assert "counts" in body["diff"]["detections"]


def test_a_replay_that_finds_a_different_animal_reports_a_class_change(client, walked):
    walked["tracks"] = [_track("squirrel", _samples(6))]
    diff = _post(client).get_json()["comparison"]["diff"]["detections"]
    assert diff["counts"]["class_changed"] == 1
    assert diff["class_changed"][0]["before"]["label"] == "person"
    assert diff["class_changed"][0]["after"]["label"] == "squirrel"


def test_a_replay_that_finds_nothing_reports_the_original_as_disappeared(client, walked):
    walked["tracks"] = []
    comparison = _post(client).get_json()["comparison"]
    assert comparison["diff"]["detections"]["counts"]["disappeared"] == 1
    assert comparison["after"]["detection_count"] == 0
    assert comparison["changed"] is True


def test_the_report_says_whether_an_alert_would_have_fired(client, walked):
    walked["tracks"] = []
    comparison = _post(client).get_json()["comparison"]
    # Under the "hard" profile on record, the person the camera reported
    # is an alarm. A replay that finds nothing leaves a bare motion
    # event, which still notifies under hard — at info, not alarm.
    assert comparison["before"]["alert"]["level"] == "alarm"
    assert comparison["after"]["alert"]["level"] == "info"
    assert comparison["alert_changed"] is True, "a downgrade is a change even when both notify"


def test_the_stored_alarm_profile_is_used_not_the_current_one(client, store, walked):
    # provenance says "hard", the live camera says "medium". A person
    # detection is an alarm under hard, only info under medium — the
    # replay must judge by what was on record.
    walked["tracks"] = [_track("person", _samples(6))]
    comparison = _post(client, "stored").get_json()["comparison"]
    assert comparison["after"]["alert"]["level"] == "alarm"
    comparison = _post(client, "current").get_json()["comparison"]
    assert comparison["after"]["alert"]["level"] == "info"


def test_an_unchanged_result_is_reported_as_unchanged(client, walked):
    walked["tracks"] = [_track("person", _samples(6, score=0.9))]
    assert _post(client).get_json()["comparison"]["changed"] is False


def test_a_clip_that_was_never_indexed_has_no_track_baseline(client, walked):
    # No tracks.json on disk. Reporting the replay's tracks as "appeared"
    # would be an artefact of the missing baseline, not a finding.
    walked["tracks"] = [_track("person", _samples(6, score=0.9))]
    comparison = _post(client).get_json()["comparison"]
    assert comparison["tracks_comparable"] is False
    assert comparison["diff"]["tracks"] is None
    assert comparison["before"]["track_count"] is None
    assert comparison["changed"] is False, "a missing baseline cannot make the answer 'changed'"


def test_a_clip_indexed_to_zero_tracks_is_a_real_baseline(client, walked, tmp_storage_root: Path):
    sidecar = tracks_path_for(tmp_storage_root / REL)
    sidecar.write_text(json.dumps({"schema": 4, "tracks": []}), encoding="utf-8")
    walked["tracks"] = [_track("person", _samples(6, score=0.9))]
    comparison = _post(client).get_json()["comparison"]
    assert comparison["tracks_comparable"] is True
    assert comparison["diff"]["tracks"]["counts"]["appeared"] == 1
    assert comparison["changed"] is True, "finding a track where indexing found none is real"


def test_an_unreadable_sidecar_is_treated_as_no_baseline(client, tmp_storage_root: Path):
    sidecar = tracks_path_for(tmp_storage_root / REL)
    sidecar.write_text("{ truncated json", encoding="utf-8")
    assert _post(client).get_json()["comparison"]["tracks_comparable"] is False


# ── persistence ───────────────────────────────────────────────────────


def test_the_run_is_stored_under_the_event_stamped_with_its_settings(client, store):
    body = _post(client).get_json()
    ev = store.get_event(CAM, EVENT_ID)
    assert len(ev["replays"]) == 1
    entry = ev["replays"][0]
    assert entry["settings_source"] == "stored"
    assert entry["settings_hash"] == body["settings"]["hash"]
    assert entry["frames_analysed"] == 240
    assert entry["ran_at"]


def test_the_event_s_own_findings_are_never_rewritten(client, store, event_doc, walked):
    walked["tracks"] = [_track("squirrel", _samples(6))]
    _post(client)
    ev = store.get_event(CAM, EVENT_ID)
    assert ev["detections"] == event_doc["detections"], "a replay is a question, not a correction"
    assert ev["labels"] == ["person"]
    assert ev["provenance"]["tuning"] == STORED_TUNING


def test_the_tracks_sidecar_is_not_overwritten(client, tmp_storage_root: Path):
    sidecar = tracks_path_for(tmp_storage_root / REL)
    sidecar.write_text(json.dumps({"schema": 4, "tracks": []}), encoding="utf-8")
    _post(client)
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"schema": 4, "tracks": []}


def test_repeated_runs_accumulate_but_stay_capped(client, store):
    for _ in range(7):
        _post(client)
    assert len(store.get_event(CAM, EVENT_ID)["replays"]) == 5


def test_the_stored_entry_omits_the_track_sample_series(client, store):
    _post(client)
    entry = store.get_event(CAM, EVENT_ID)["replays"][0]
    assert entry["tracks"], "the tracks themselves are worth keeping"
    assert all("samples" not in t for t in entry["tracks"]), "…but not their sample series"


def test_the_preflight_hands_the_history_back_for_the_fold_to_render(client):
    _post(client)
    assert len(client.get(f"/api/event/{EVENT_ID}/replay").get_json()["replays"]) == 1
