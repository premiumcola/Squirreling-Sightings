"""`PATCH /api/cameras/<id>/detection-tuning` is the one route that
changes detection config WITHOUT restarting the runtime.

That matters because `DetectionSetup` is resolved once, in
`CameraRuntime.__init__`, beside `self._tracker`. Resolving it per frame
allocated a frozen dataclass, two dict copies and a frozenset ~20x/s per
camera for values that normally cannot change — the premise being that
every camera-config change restarts the runtime
(`server._compute_camera_diff` -> `restart_single_camera`).

This endpoint is the exception, deliberately: its whole purpose is to
live-apply a slider without dropping the RTSP connection. It already
re-pushed the tracker thresholds. It did not rebuild the setup, so the
alarm loop kept the OLD `object_filter`, `label_thresholds`,
`bottom_crop_px` and `roi_mode` while the same response reported the new
ones under `"effective"`. The panel said applied; the detector never saw
it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import app_state
from app.detect_setup import build_detection_setup
from app.routes import cameras as camera_routes

flask = pytest.importorskip("flask")

CAM = "reolink_cx810_gartendachterrasse_181"


class _Tracker:
    def configure(self, **kw):
        self.last = kw


class _Runtime:
    """Only what the live-apply block touches."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.global_cfg = {"processing": {}}
        self._tracker = _Tracker()
        self.detect_setup = build_detection_setup(
            CAM, cfg, roi_mode="off", global_cfg=self.global_cfg
        )

    def _effective_roi_mode(self):
        return self.cfg.get("roi_mode") or "off"


class _Settings:
    def __init__(self, cam):
        self.cam = cam

    def get_camera(self, _cam_id):
        return self.cam

    def upsert_camera(self, cam):
        self.cam = cam


@pytest.fixture
def wired(monkeypatch):
    cam = {
        "id": CAM,
        "name": "Garten",
        "object_filter": ["person", "cat"],
        "label_thresholds": {"person": 0.45},
    }
    runtime = _Runtime(dict(cam))
    monkeypatch.setattr(app_state, "settings", _Settings(cam), raising=False)
    monkeypatch.setattr(app_state, "runtimes", {CAM: runtime}, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(camera_routes.bp)
    return SimpleNamespace(client=app.test_client(), runtime=runtime)


def test_a_narrowed_object_filter_reaches_the_alarm_loop(wired):
    """THE regression test — the loop kept ['person', 'cat']."""
    before = set(wired.runtime.detect_setup.object_filter)
    assert "cat" in before

    r = wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning", json={"object_filter": ["person"]}
    )
    assert r.status_code == 200, r.get_data(as_text=True)

    after = set(wired.runtime.detect_setup.object_filter)
    assert after == {"person"}, (
        "the loop reads runtime.detect_setup; if this route does not rebuild it, the "
        f"detector keeps the old filter while the response reports the new one — got {after}"
    )


def test_a_changed_label_threshold_reaches_the_alarm_loop(wired):
    """`cat`, not `person` — see the next test for why."""
    wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning",
        json={"label_thresholds": {"cat": 0.8}},
    )
    assert wired.runtime.detect_setup.spawn_for("cat") == pytest.approx(0.8)


def test_the_person_floor_still_wins_on_this_route(wired):
    """The two rails compose, and the safety one is the outer.

    This route rebuilds DetectionSetup so a tuning change reaches the
    alarm loop without a restart. It also runs the person clamp, because
    it shows no confirmation dialog. So a request for 0.8 arrives at the
    detector as 0.54 — propagated, and capped. Neither guarantee may
    swallow the other, which is what this pins.
    """
    wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning",
        json={"label_thresholds": {"person": 0.8}},
    )
    from app.thresholds._apply import AUTO_E_FLOOR_PERSON_SECURITY, spawn_for

    ceiling = spawn_for("person", AUTO_E_FLOOR_PERSON_SECURITY)
    assert wired.runtime.detect_setup.spawn_for("person") == pytest.approx(ceiling)


def test_the_tracker_is_still_reconfigured(wired):
    """The pre-existing half of the live-apply must not regress."""
    wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning", json={"track_iou_match_threshold": 0.35}
    )
    assert wired.runtime._tracker.last["iou_threshold"] == pytest.approx(0.35)


def test_miss_grace_zero_is_the_sentinel_not_out_of_range(wired):
    """0.0 means "use the system default" everywhere else that reads
    this field (hydrateErkennungFields, discovery.js's collector, the
    Netz tuning panel) — this route used to reject it as below its
    old 1.0 floor."""
    r = wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning", json={"track_miss_grace_seconds": 0.0}
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["effective"]["track_miss_grace_seconds"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("motion_sensitivity", 0.7),
        ("wildlife_motion_sensitivity", 1.5),
        ("roi_min_net_disp_frac", 0.08),
        ("post_motion_tail_s", 8.0),
    ],
)
def test_the_moved_camera_loop_fields_save_and_report(wired, field, value):
    """The Netz-hosted Kamera-Feinschliff fields — same route, same
    validate-then-store-then-echo shape as the pre-existing four."""
    r = wired.client.patch(f"/api/cameras/{CAM}/detection-tuning", json={field: value})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["effective"][field] == pytest.approx(value)


def test_frame_interval_ms_is_stored_as_an_int(wired):
    r = wired.client.patch(f"/api/cameras/{CAM}/detection-tuning", json={"frame_interval_ms": 500})
    assert r.status_code == 200, r.get_data(as_text=True)
    stored = r.get_json()["effective"]["frame_interval_ms"]
    assert stored == 500
    assert isinstance(stored, int)


def test_roi_mode_accepts_a_known_value(wired):
    r = wired.client.patch(f"/api/cameras/{CAM}/detection-tuning", json={"roi_mode": "2x2"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["effective"]["roi_mode"] == "2x2"


def test_roi_mode_rejects_an_unknown_value(wired):
    r = wired.client.patch(f"/api/cameras/{CAM}/detection-tuning", json={"roi_mode": "4x4"})
    assert r.status_code == 400, r.get_data(as_text=True)


def test_track_filter_ghosts_saves_as_a_bool(wired):
    r = wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning", json={"track_filter_ghosts": False}
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["effective"]["track_filter_ghosts"] is False
