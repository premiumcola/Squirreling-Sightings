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
    wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning",
        json={"label_thresholds": {"person": 0.8}},
    )
    spawn_for = wired.runtime.detect_setup.spawn_for
    assert spawn_for("person") == pytest.approx(0.8)


def test_the_tracker_is_still_reconfigured(wired):
    """The pre-existing half of the live-apply must not regress."""
    wired.client.patch(
        f"/api/cameras/{CAM}/detection-tuning", json={"track_iou_match_threshold": 0.35}
    )
    assert wired.runtime._tracker.last["iou_threshold"] == pytest.approx(0.35)
