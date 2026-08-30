"""The cam-edit "eye" — revealing a stored RTSP password on demand.

`redact_camera` deliberately strips the password from every camera dict
that leaves the process, because `/api/cameras` is polled every few
seconds by every open dashboard: a secret in that payload lands in every
response body, every browser cache, and — sitting beside a username
field — in the browser's password manager.

That is still true, and this endpoint does not change it. It hands the
password out ONCE, on an explicit click, so the eye can work without the
value riding along hundreds of times an hour. These tests pin both halves
of that bargain: the reveal works, AND the bulk payload stays clean.
"""

from __future__ import annotations

import pytest

from app import app_state
from app.routes import cameras as camera_routes
from app.routes import camera_device

flask = pytest.importorskip("flask")

CAM = "reolink_cx810_werkstatt_172"
PW = "hunter2secret"


class _Settings:
    def __init__(self, cam):
        self.cam = cam
        self.data = {"cameras": [cam]}

    def get_camera(self, cam_id):
        return self.cam if cam_id == self.cam["id"] else None


@pytest.fixture
def client(monkeypatch):
    cam = {
        "id": CAM,
        "name": "Werkstatt",
        "password": PW,
        "rtsp_url": f"rtsp://admin:{PW}@cam.lan:554/h265Preview_01_main",
        "snapshot_url": f"http://admin:{PW}@cam.lan/cgi-bin/snapshot.cgi",
    }
    monkeypatch.setattr(app_state, "settings", _Settings(cam), raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(camera_device.bp)
    app.register_blueprint(camera_routes.bp)
    return app.test_client()


def test_the_eye_can_get_the_stored_password(client):
    r = client.post(f"/api/cameras/{CAM}/reveal-secret")
    assert r.status_code == 200
    body = r.get_json()
    assert body["password"] == PW
    assert body["password_set"] is True


def test_the_reveal_is_never_cached(client):
    """A cached reveal would put the secret exactly where redaction was
    trying to keep it out of."""
    r = client.post(f"/api/cameras/{CAM}/reveal-secret")
    cc = r.headers.get("Cache-Control", "")
    assert "no-store" in cc
    assert "private" in cc


def test_an_unknown_camera_reveals_nothing(client):
    r = client.post("/api/cameras/does-not-exist/reveal-secret")
    assert r.status_code == 404
    assert PW not in r.get_data(as_text=True)


def test_the_polled_camera_list_still_carries_no_secret(client):
    """THE guard on the bargain. If this ever fails, the reveal endpoint
    has stopped being the only way out and the leak is back."""
    r = client.get("/api/settings/cameras")
    text = r.get_data(as_text=True)
    assert PW not in text, "the polled camera list leaked the RTSP password again"
    cam = r.get_json()["cameras"][0]
    assert "password" not in cam
    assert cam["password_set"] is True
    # The URLs go out with the userinfo password stripped, username kept.
    assert cam["rtsp_url"] == "rtsp://admin@cam.lan:554/h265Preview_01_main"
    assert PW not in cam["snapshot_url"]
