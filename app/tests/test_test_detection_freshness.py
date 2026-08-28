"""The simulation endpoint's freshness check has to be falsifiable.

``/api/cameras/<id>/test-detection`` refuses a frame older than a second
so "Erkennung jetzt simulieren" shows the CURRENT scene. It used to read
that age off ``rt.frame_ts``, which the main loop stamps when it DECODES
a frame — so a frame pulled from a minutes-deep decoder backlog carried
a timestamp from a millisecond ago and passed a check that could not
fail. The reported symptom was a walk-past being simulated minutes later,
in order, one backlogged frame per click.

The endpoint now reads the arrival timestamp the capture reader records,
plus the decoder's lag against real time. Both tests below pass a frame
with a FRESH decode stamp and stale content; against the pre-fix handler
both reach inference instead of reporting a stuck stream.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from app import app_state
from app.routes import _sim_frame
from app.routes import coral_test_detection as ctd

flask = pytest.importorskip("flask")

CAM = "reolink_cx810_werkstatt_172"


class _RuntimeStub:
    """Enough of CameraRuntime for the frame-acquisition block.

    ``frame_ts`` is deliberately always fresh: it is the decode-time
    stamp, and the whole point is that it must no longer be what the
    handler trusts.
    """

    def __init__(self, capture_ts: float, lag_s: float | None = None, has_sub: bool = False):
        self.lock = threading.Lock()
        self.frame = np.zeros((360, 640, 3), dtype=np.uint8)
        self.frame_ts = time.time()
        self._capture_ts = capture_ts
        self._lag_s = lag_s
        self._preview_frame = self.frame if has_sub else None
        self._preview_frame_ts = capture_ts if has_sub else 0.0
        self.detector = None  # never reached while the frame gate holds

    def latest_main_frame(self):
        return self.frame, self._capture_ts

    def capture_lag_s(self):
        return self._lag_s


@pytest.fixture
def client(monkeypatch):
    """Flask test client with only the test-detection blueprint mounted.

    The real boot builds camera runtimes and a Telegram poller; a second
    poller against the live token is exactly what must not happen here.
    """
    # The handler polls 2.5 s before declaring a stream stuck; the tests
    # only care about the verdict, not about waiting for it.
    monkeypatch.setattr(_sim_frame, "FRESH_POLL_WINDOW_S", 0.2)

    class _Settings:
        def get_camera(self, cam_id):
            return {"id": cam_id, "name": cam_id} if cam_id == CAM else None

    runtimes: dict[str, object] = {}
    monkeypatch.setattr(app_state, "settings", _Settings(), raising=False)
    monkeypatch.setattr(app_state, "runtimes", runtimes, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(ctd.bp)
    return app.test_client(), runtimes


def _post(client, **query):
    c, _ = client
    qs = "&".join(f"{k}={v}" for k, v in query.items())
    return c.post(f"/api/cameras/{CAM}/test-detection" + (f"?{qs}" if qs else ""))


def test_old_content_with_a_fresh_decode_stamp_is_refused(client):
    """Two-minute-old pixels, timestamp from a millisecond ago."""
    _, runtimes = client
    runtimes[CAM] = _RuntimeStub(capture_ts=time.time() - 120.0)

    resp = _post(client)

    assert resp.status_code == 503
    body = resp.get_json()
    assert body["code"] == "stale"
    assert body["frame_age_ms"] > 100_000, "the reported age must be the real one"


def test_decoder_behind_live_is_refused_despite_fresh_arrival(client):
    """A CPU-starved decoder reads flat out and still falls behind: the
    frames arrive just now and carry old pixels. Arrival time alone
    cannot see that — media-vs-wall lag can."""
    _, runtimes = client
    runtimes[CAM] = _RuntimeStub(capture_ts=time.time(), lag_s=9.0)

    resp = _post(client)

    assert resp.status_code == 503
    body = resp.get_json()
    assert body["code"] == "stale"
    assert "capture_lag" in (body["validator_reason"] or "")


def test_fresh_frame_passes_the_gate(client):
    """Guard against a gate so strict nothing gets through: a current
    frame must reach inference (and fail there, on the absent Coral)."""
    _, runtimes = client
    runtimes[CAM] = _RuntimeStub(capture_ts=time.time(), lag_s=0.2)

    resp = _post(client)

    assert resp.status_code == 503
    assert "Coral" in resp.get_json()["error"], "frame gate rejected a current frame"


def test_stale_main_falls_back_to_a_fresh_sub_stream(client):
    """The sub-stream is drained by _preview_loop, so its timestamp is
    an arrival time too — a stalled main must not blind the simulation."""
    _, runtimes = client
    rt = _RuntimeStub(capture_ts=time.time(), has_sub=True)
    rt._capture_ts = time.time() - 120.0  # main is minutes behind
    runtimes[CAM] = rt

    resp = _post(client)

    assert "Coral" in resp.get_json()["error"], "fresh sub-stream frame was not used"
