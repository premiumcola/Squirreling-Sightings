"""The camera-edit "Außenkamera" toggle has to survive the full round
trip: schema default → ``default_camera`` seeding a fresh camera →
``SettingsStore.upsert_camera`` persisting an explicit value → ``GET
/api/cameras`` shipping it back to the frontend that hydrates the
Allgemein-tab toggle.

Mirrors ``test_camera_color_reaches_ui.py``'s structure — that file's
own lesson (a field missing from either the ``/api/cameras`` projection
or ``default_camera``'s skeleton is a field that is stored and
invisible) is exactly the failure mode this field must not repeat.
"""

from __future__ import annotations

import importlib
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

CAM = "reolink_rlc810a_werkstatt_44"


# ── /api/cameras projection ────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    def _wire(cam_extra: dict):
        cam = {"id": CAM, "name": "Werkstatt", "location": "Keller", **cam_extra}
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


def test_the_camera_list_ships_an_explicit_false(client):
    assert _row(client({"outdoor": False}))["outdoor"] is False


def test_the_camera_list_ships_an_explicit_true(client):
    assert _row(client({"outdoor": True}))["outdoor"] is True


def test_a_legacy_camera_missing_the_key_defaults_to_outdoor_true(client):
    assert _row(client({}))["outdoor"] is True


# ── default_camera skeleton ─────────────────────────────────────────────────


def test_a_new_camera_is_seeded_outdoor_by_default():
    assert default_camera({})["outdoor"] is True


def test_a_new_camera_keeps_an_explicit_indoor_flag():
    assert default_camera({"id": CAM, "outdoor": False})["outdoor"] is False


# ── SettingsStore.upsert_camera round trip ──────────────────────────────────


def _make_store(tmp_path: Path):
    sys.modules.pop("app.settings_store", None)
    import app.settings_store

    importlib.reload(app.settings_store)
    from app.settings_store import SettingsStore

    storage = tmp_path / "storage"
    storage.mkdir()
    base_config = {
        "app": {"name": "Squirreling · Sightings"},
        "server": {
            "host": "0.0.0.0",
            "port": 8099,
            "default_discovery_subnet": "192.0.2.0/24",
        },
        "cameras": [],
    }
    return SettingsStore(storage / "settings.json", base_config)


def test_upsert_camera_persists_an_explicit_indoor_flag(tmp_path: Path):
    store = _make_store(tmp_path)
    cam = {
        "id": CAM,
        "name": "Werkstatt",
        "manufacturer": "Reolink",
        "model": "RLC-810A",
        "rtsp_url": "rtsp://user:pass@192.0.2.44/h265Preview_01_main",
        "outdoor": False,
    }
    store.upsert_camera(dict(cam))
    saved = store.get_camera(CAM)
    assert saved is not None
    assert saved["outdoor"] is False


def test_upsert_camera_round_trip_survives_load_modify_save_reload(tmp_path: Path):
    """CLAUDE.md's settings round-trip discipline: load → modify → save
    → reload → diff. The outdoor flag must be the only field that
    changed between the two saves."""
    store = _make_store(tmp_path)
    base = {
        "id": CAM,
        "name": "Werkstatt",
        "manufacturer": "Reolink",
        "model": "RLC-810A",
        "rtsp_url": "rtsp://user:pass@192.0.2.44/h265Preview_01_main",
    }
    store.upsert_camera(dict(base))
    before = dict(store.get_camera(CAM))
    assert before["outdoor"] is True  # schema default on first save

    flipped = dict(before)
    flipped["outdoor"] = False
    store.upsert_camera(flipped)
    after = store.get_camera(CAM)

    diff_keys = {k for k in after if after.get(k) != before.get(k)}
    assert diff_keys == {"outdoor"}
    assert after["outdoor"] is False

    # Reload from disk — a fresh SettingsStore instance over the same
    # settings.json must see the persisted value, not an in-memory-only
    # write.
    sys.modules.pop("app.settings_store", None)
    import app.settings_store

    importlib.reload(app.settings_store)
    from app.settings_store import SettingsStore

    base_config = {
        "app": {"name": "Squirreling · Sightings"},
        "server": {"host": "0.0.0.0", "port": 8099},
        "cameras": [],
    }
    reloaded = SettingsStore(store.path, base_config)
    assert reloaded.get_camera(CAM)["outdoor"] is False
