"""A camera's identity colour has to survive the round trip.

The Color-Picker in cam-edit's Allgemein tab writes ``cameras[].color``,
the schema validates it, ``upsert_camera`` stores it, and the frontend's
``getCameraColor`` prefers it over the name-derived auto-tone. Between
those two ends it was dropped twice:

* ``/api/cameras`` builds each row as an explicit key-by-key projection
  and never copied ``color``. ``state.cameras`` is populated from that
  response, so every surface reading it — dashboard tile titles, the
  timeline lanes, the cam-edit avatar — fell back to the auto-tone. The
  saved colour was in settings.json and nowhere else.
* ``default_camera`` had no ``color`` entry, so the full default
  skeleton a NEW camera is seeded from omitted the key entirely.

Both halves pinned, plus the invariant behind them: the projection must
carry every user-settable identity field the frontend reads, or the
value is stored and invisible.
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
from app.settings.defaults import default_camera  # noqa: E402

CAM = "reolink_rlc810a_garten_23"
_PICKED = "#b48b6a"


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
    payload = r.get_json()
    rows = payload["cameras"] if isinstance(payload, dict) else payload
    return rows[0]


def test_the_camera_list_ships_the_picked_colour(client):
    assert _row(client({"color": _PICKED}))["color"] == _PICKED


def test_an_unset_colour_is_shipped_as_empty_not_omitted(client):
    """`getCameraColor` treats "" as "no override" and falls back to the
    auto-tone — but the key has to be there for the form to hydrate the
    Auto state at all."""
    assert _row(client({}))["color"] == ""


def test_a_new_camera_is_seeded_with_the_key(client):
    assert default_camera({})["color"] == ""


def test_a_new_camera_keeps_a_colour_it_was_created_with(client):
    assert default_camera({"id": CAM, "color": _PICKED})["color"] == _PICKED
