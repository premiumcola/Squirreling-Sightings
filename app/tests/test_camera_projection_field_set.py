"""``/api/cameras`` must carry every stored camera field, not a hand-list.

The endpoint built each row as a key-by-key positive list. That list has
been short three times already, and each repair left its own comment in
``routes/cameras.py`` instead of removing the failure mode:

* ``color``  — every saved identity colour was invisible
  (``test_camera_color_reaches_ui.py``)
* ``outdoor`` — the Mediathek outdoor scope
  (``test_camera_outdoor_toggle.py``)
* the four ``track_*`` overrides — the form showed 0 after every save

The fourth instance is worse than an invisible value, because
``/api/cameras`` is not only a display feed. ``live-update.js:156`` does
``state.cameras = (await j('/api/cameras')).cameras``, and cam-edit's save
collector resolves its "keep what is stored" fallbacks out of exactly that
array — ``discovery.js:614`` ``const existingCam = (state.cameras || [])
.find(...)``. A field the projection omits therefore does not read as
"unchanged" on save; it reads as *absent*, and the collector writes its
zero-value over the stored one:

* ``discovery.js:765``  ``label_thresholds: existingCam?.label_thresholds
  || {}`` — and ``upsert_camera`` replaces nested dicts wholesale, so
  every Netz-dragged per-class spawn threshold is wiped by the next
  unrelated camera save. The comment above that line explains the hazard
  and prescribes this exact defence; the field it reads was never shipped.
* ``discovery.js:789`` → ``detection-perclass.js:20`` — same, for the
  per-class confirmation window.
* ``discovery.js:729`` ``wildlife_motion_sensitivity`` and
  ``discovery.js:758`` ``roi_min_net_disp_frac`` fall back to ``0``.
  Neither has a form input (they live on other panels), so the stored
  override was reset on every save.

So the guard below is not "does the row contain field X". It is the
writer-against-reader assertion that none of the four repairs made:
every key ``CAMERA_SCHEMA`` can store has to come back out, secrets
excepted. A positive list that is only ever checked against itself —
which is what a per-field test amounts to — can never catch the next
omission.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import flask
import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state  # noqa: E402
from app.routes import cameras as camera_routes  # noqa: E402
from app.schema import CAMERA_SCHEMA  # noqa: E402

CAM = "reolink_rlc810a_garten_23"

# The one field held back on purpose. The endpoint is polled every 3 s
# over unauthenticated plain HTTP, so the password ships as the boolean
# `password_set`; `rtsp_url` / `snapshot_url` do come back, with the
# userinfo stripped (see routes/_secrets).
WITHHELD = {"password"}


@pytest.fixture
def client(monkeypatch):
    def _wire(cam_extra: dict):
        cam = {"id": CAM, "name": "Garten", "location": "Hof", **cam_extra}
        monkeypatch.setattr(
            app_state, "get_effective_config", lambda: {"cameras": [cam]}, raising=False
        )
        monkeypatch.setattr(app_state, "runtimes", {}, raising=False)
        monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), raising=False)
        app = flask.Flask(__name__)
        app.register_blueprint(camera_routes.bp)
        return app.test_client()

    return _wire


def _row(c) -> dict:
    r = c.get("/api/cameras")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["cameras"][0]


def test_every_storable_camera_field_comes_back_out(client):
    """The writer-against-reader guard. `CAMERA_SCHEMA` is what
    `upsert_camera` will persist; anything it can store and this endpoint
    cannot return is a value the cam-edit form silently resets."""
    row = _row(client({}))
    missing = sorted((set(CAMERA_SCHEMA) - WITHHELD) - set(row))
    assert not missing, (
        "/api/cameras drops stored camera fields: "
        f"{missing}. state.cameras is the cam-edit save collector's "
        "fallback source, so an omitted field is written back as its "
        "zero value on the next save."
    )


def test_the_password_is_never_in_the_row(client):
    row = _row(client({"password": "hunter2"}))
    assert "password" not in row
    assert row["password_set"] is True


def test_a_stored_value_survives_the_projection(client):
    """Not the default — the *stored* value. `setdefault` against a
    schema default would satisfy the key-set guard above while still
    handing the collector a zero to write back."""
    row = _row(
        client(
            {
                "label_thresholds": {"bird": 0.42},
                "confirmation_window": {"cat": {"n": 2, "m": 3}},
                "wildlife_motion_sensitivity": 0.7,
                "roi_min_net_disp_frac": 0.25,
            }
        )
    )
    assert row["label_thresholds"] == {"bird": 0.42}
    assert row["confirmation_window"] == {"cat": {"n": 2, "m": 3}}
    assert row["wildlife_motion_sensitivity"] == 0.7
    assert row["roi_min_net_disp_frac"] == 0.25


def test_the_runtime_status_still_wins_over_the_config(client, monkeypatch):
    """The backfill is additive. `status` / `enabled` / `armed` describe
    what the runtime is doing right now; the stored config values must not
    overwrite them, or the dashboard tile reports a camera as running
    because settings.json says `enabled: true`."""
    rt = SimpleNamespace(
        status=lambda: {
            "id": CAM,
            "name": "Garten",
            "enabled": False,
            "armed": False,
            "status": "error",
            "today_events": 0,
        },
        recent_detections=[],
    )
    c = client({"enabled": True, "armed": True})
    monkeypatch.setattr(app_state, "runtimes", {CAM: rt}, raising=False)
    row = _row(c)
    assert row["status"] == "error"
    assert row["enabled"] is False
    assert row["armed"] is False
