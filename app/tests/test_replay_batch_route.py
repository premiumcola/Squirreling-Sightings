"""The batch replay endpoints and worker loop, with no decoder and no TPU.

`replay_clip` is stubbed at the seam `_run.py` imports it through, so
everything this package owns runs for real — selection, the job state
machine, cancellation, aggregation, persistence and the route contract —
while the one function that needs OpenCV and a model does not.

The load-bearing guarantees held here:
  * one clip that cannot be read never ends a run over hundreds;
  * a cancelled run still persists the rows it did collect;
  * the batch writes nothing onto an event except the `replays` list.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from app import app_state
from app.replay_batch import _run as batch_run
from app.replay_batch import load_report, reset_for_tests, snapshot
from app.routes import replay_batch as batch_routes
from app.storage import EventStore

CAM = "cam_a"
CAM_CFG = {
    "roi_mode": "off",
    "alarm_profile": "medium",
    "track_spawn_min_score": 0.5,
    "track_continue_min_score": 0.2,
    "detection_min_score": 0.55,
}


def _bird_event(event_id, **kw):
    rel = f"motion_detection/{CAM}/2026-05-22/{event_id}.mp4"
    base = {
        "event_id": event_id,
        "camera_id": CAM,
        "labels": ["bird"],
        "video_relpath": rel,
        "detections": [
            {"label": "bird", "score": 0.8, "bbox": {"x1": 0, "y1": 0, "x2": 9, "y2": 9}}
        ],
    }
    base.update(kw)
    return base


class _Worker:
    def detector(self):
        return object()


@pytest.fixture(autouse=True)
def _clean_state():
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.fixture
def store(tmp_storage_root: Path) -> EventStore:
    """Two bird clips, each with a one-bird tracks.json sidecar — so the
    run has a real whole-clip baseline and `birds_gained_strict` is
    exercised end to end rather than falling back to the frozen
    detections."""
    import json

    from app.tracking_worker import tracks_path_for

    st = EventStore(str(tmp_storage_root))
    for eid in ("20260522-120000-1", "20260522-130000-2"):
        st.add_event(CAM, _bird_event(eid))
        vid = tmp_storage_root / f"motion_detection/{CAM}/2026-05-22/{eid}.mp4"
        vid.parent.mkdir(parents=True, exist_ok=True)
        vid.write_bytes(b"not really an mp4")
        tracks_path_for(vid).write_text(
            json.dumps({"tracks": [{"track_id": "s1", "label": "bird", "best_score": 0.8}]}),
            encoding="utf-8",
        )
    st.add_event(CAM, _bird_event("20260522-140000-3", labels=["person"], detections=[]))
    return st


@pytest.fixture
def replayed() -> list:
    """Every camera_id the stubbed replay was asked to run."""
    return []


@pytest.fixture
def fake_replay(monkeypatch, replayed):
    """Two bird tracks out of every clip — one more than the single bird
    each event recorded, which is the operator's two-bird case."""

    def _replay(*, worker, camera_id, video_path, storage_root, cfg, **kw):
        replayed.append(camera_id)
        return {
            "tracks": [
                {"track_id": "t1", "label": "bird", "best_score": 0.9},
                {"track_id": "t2", "label": "bird", "best_score": 0.7},
            ],
            "detections": [
                {"label": "bird", "score": 0.9, "bbox": None},
                {"label": "bird", "score": 0.7, "bbox": None},
            ],
            "gates": {},
            "filter_applied": None,
            "frames_analysed": 10,
            "frames_available": 10,
            "truncated": False,
            "duration_ms": 5,
            "detector": {"available": True, "mode": "cpu", "model": "m.tflite", "reason": None},
        }

    monkeypatch.setattr(batch_run, "replay_clip", _replay)
    return _replay


@pytest.fixture
def ctx(store, tmp_storage_root: Path):
    return {
        "store": store,
        "storage_root": tmp_storage_root,
        "worker": _Worker(),
        "cam_cfg_for": lambda _cid: dict(CAM_CFG),
        "resolve_video": lambda eid, cid: tmp_storage_root
        / f"motion_detection/{cid}/2026-05-22/{eid}.mp4",
        "sidecar_tracks_for": lambda _v: [{"track_id": "s1", "label": "bird", "best_score": 0.8}],
    }


# ── the worker loop ───────────────────────────────────────────────────


class TestRunBatch:
    def test_only_bird_clips_are_replayed(self, ctx, fake_replay, replayed):
        report = batch_run.run_batch(ctx, {})
        assert report["selected"] == 2
        assert report["examined"] == 2
        assert len(replayed) == 2

    def test_the_second_bird_shows_up_as_a_strict_gain(self, ctx, fake_replay):
        """Sidecar baseline says one bird, the replay finds two."""
        report = batch_run.run_batch(ctx, {})
        assert report["birds_gained_strict"] == 2
        assert report["birds_lost_events"] == 0

    def test_an_unreadable_clip_is_an_error_not_the_end_of_the_run(
        self, ctx, fake_replay, monkeypatch
    ):
        calls = {"n": 0}
        real = batch_run.replay_clip

        def _boom(**kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("Clip nicht lesbar")
            return real(**kw)

        monkeypatch.setattr(batch_run, "replay_clip", _boom)
        report = batch_run.run_batch(ctx, {})
        assert report["errors"] == 1
        assert report["examined"] == 1, "the second clip still ran"

    def test_a_missing_video_is_an_error_not_a_crash(self, ctx, fake_replay):
        ctx["resolve_video"] = lambda _e, _c: None
        report = batch_run.run_batch(ctx, {})
        assert report["errors"] == 2
        assert report["examined"] == 0

    def test_the_report_is_persisted(self, ctx, fake_replay, tmp_storage_root: Path):
        batch_run.run_batch(ctx, {})
        assert load_report(tmp_storage_root)["examined"] == 2

    def test_the_camera_scope_narrows_the_run(self, ctx, fake_replay, replayed):
        batch_run.run_batch(ctx, {"cameras": ["cam_zzz"]})
        assert replayed == []

    def test_the_batch_writes_only_the_replays_list_onto_an_event(self, ctx, fake_replay, store):
        before = store.get_event(CAM, "20260522-120000-1")
        before_dets = list(before["detections"])
        batch_run.run_batch(ctx, {})
        after = store.get_event(CAM, "20260522-120000-1")
        assert after["detections"] == before_dets, "the event's own findings must survive"
        assert after.get("bird_species") == before.get("bird_species")
        assert len(after["replays"]) == 1

    def test_a_cancelled_run_still_persists_what_it_collected(
        self, ctx, fake_replay, monkeypatch, tmp_storage_root: Path
    ):
        from app.replay_batch import _state

        monkeypatch.setattr(_state, "cancel_requested", lambda: True)
        report = batch_run.run_batch(ctx, {})
        assert report["cancelled"] is True
        assert report["examined"] == 0
        assert load_report(tmp_storage_root) is not None


# ── the endpoints ─────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch, store, tmp_storage_root: Path, fake_replay):
    monkeypatch.setattr(batch_routes, "singleton", lambda: _Worker())
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(app_state, "get_camera_cfg", lambda _cid: dict(CAM_CFG), raising=False)
    # The real helper returns (camera_id, path); `_video_for` unpacks it.
    monkeypatch.setattr(
        batch_routes,
        "_resolve_event_video",
        lambda eid, cid=None: (
            CAM,
            tmp_storage_root / f"motion_detection/{CAM}/2026-05-22/{eid}.mp4",
        ),
    )
    app = Flask(__name__)
    app.register_blueprint(batch_routes.bp)
    return app.test_client()


def _await_idle(client, tries=200):
    """The run is a daemon thread; poll the endpoint until it settles."""
    import time

    for _ in range(tries):
        body = client.get("/api/replay/batch").get_json()
        if not body["running"] and body["phase"]:
            return body
        time.sleep(0.02)
    raise AssertionError("batch never finished")


class TestEndpoints:
    def test_a_run_starts_and_reports_its_aggregate(self, client):
        assert client.post("/api/replay/batch", json={}).status_code == 200
        body = _await_idle(client)
        assert body["phase"] == "fertig"
        assert body["report"]["examined"] == 2
        assert body["report"]["birds_gained_strict"] == 2

    def test_a_second_start_while_running_does_not_start_a_second_walk(self, client, monkeypatch):
        import threading

        gate = threading.Event()
        real = batch_run.replay_clip
        monkeypatch.setattr(batch_run, "replay_clip", lambda **kw: (gate.wait(2), real(**kw))[1])
        client.post("/api/replay/batch", json={})
        second = client.post("/api/replay/batch", json={})
        assert second.get_json()["already_running"] is True
        gate.set()
        _await_idle(client)

    def test_progress_is_observable(self, client):
        client.post("/api/replay/batch", json={})
        body = _await_idle(client)
        assert body["total"] == 2
        assert body["done"] == 2

    def test_no_worker_is_a_503(self, client, monkeypatch):
        monkeypatch.setattr(batch_routes, "singleton", lambda: None)
        assert client.post("/api/replay/batch", json={}).status_code == 503

    def test_cancelling_nothing_is_a_409(self, client):
        assert client.post("/api/replay/batch/cancel").status_code == 409

    def test_a_running_batch_can_be_cancelled(self, client, monkeypatch):
        import threading

        gate = threading.Event()
        real = batch_run.replay_clip
        monkeypatch.setattr(batch_run, "replay_clip", lambda **kw: (gate.wait(2), real(**kw))[1])
        client.post("/api/replay/batch", json={})
        assert client.post("/api/replay/batch/cancel").status_code == 200
        gate.set()
        assert _await_idle(client)["phase"] == "abgebrochen"

    def test_the_status_survives_a_restart_via_the_persisted_report(self, client):
        client.post("/api/replay/batch", json={})
        _await_idle(client)
        reset_for_tests()  # as if the process had just come up
        body = client.get("/api/replay/batch").get_json()
        assert body["running"] is False
        assert body["report"]["examined"] == 2, "read back from disk, not memory"

    def test_a_malformed_date_narrows_nothing(self, client):
        client.post("/api/replay/batch", json={"since": "not-a-date"})
        assert _await_idle(client)["report"]["scope"]["since"] is None

    def test_a_dashed_date_is_accepted(self, client):
        client.post("/api/replay/batch", json={"since": "2026-05-22"})
        assert _await_idle(client)["report"]["scope"]["since"] == "20260522"

    def test_the_idle_state_reports_no_run(self, client):
        body = client.get("/api/replay/batch").get_json()
        assert body["running"] is False
        assert snapshot()["phase"] == ""
