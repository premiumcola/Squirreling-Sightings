"""``net_state``'s ``tuning`` key — the Kamera-Feinschliff fold.

These are the camera-WIDE capture/motion/tracking loop settings that used
to live on the Erkennung tab's own form (Analyse-Intervall,
Bewegungs-Vortrigger/Nachlauf, Objekt-Tracking, Kleintier-ROI). They can
never become per-class radar axes — the pipeline stage they govern runs
before a detection has been classified — so ``net_state`` now reports
them as a flat dict instead, with the same defaults
``hydrateErkennungFields``/``discovery.js``'s save collector already use.
"""

from __future__ import annotations

from app import app_state
from app.routes import _netz_helpers as H
from app.settings_store import SettingsStore

CAM = "cam_werkstatt"


def _settings(tmp_path, camera_overrides=None):
    base = {
        "app": {},
        "storage": {"root": str(tmp_path)},
        "cameras": [
            {
                "id": CAM,
                "name": "Werkstatt",
                "rtsp_url": "rtsp://cam.lan/s",
                "object_filter": ["person"],
                "role": "security",
                **(camera_overrides or {}),
            }
        ],
        "telegram": {"push": {}},
        "mqtt": {},
        "processing": {},
    }
    return SettingsStore(tmp_path / "settings.json", base)


def test_a_never_touched_camera_reports_the_schema_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(app_state, "settings", _settings(tmp_path))
    monkeypatch.setattr(app_state, "storage_root", tmp_path)
    tuning = H.net_state(CAM)["tuning"]
    assert tuning == {
        "frame_interval_ms": 350,
        "motion_sensitivity": 0.5,
        "post_motion_tail_s": 0,
        "track_miss_grace_seconds": 0,
        "track_iou_match_threshold": 0,
        "track_spawn_min_score": 0,
        "track_block_contain": 0,
        "track_filter_ghosts": True,
        "roi_mode": "off",
        "wildlife_motion_sensitivity": 0,
        "roi_min_net_disp_frac": 0,
    }


def test_a_customised_camera_reports_its_own_values(tmp_path, monkeypatch):
    overrides = {
        "frame_interval_ms": 500,
        "motion_sensitivity": 0.8,
        "post_motion_tail_s": 8,
        "track_miss_grace_seconds": 6.0,
        "track_iou_match_threshold": 0.35,
        "track_filter_ghosts": False,
        "roi_mode": "2x2",
        "wildlife_motion_sensitivity": 1.4,
        "roi_min_net_disp_frac": 0.08,
    }
    monkeypatch.setattr(app_state, "settings", _settings(tmp_path, overrides))
    monkeypatch.setattr(app_state, "storage_root", tmp_path)
    tuning = H.net_state(CAM)["tuning"]
    for key, val in overrides.items():
        assert tuning[key] == val, key


def test_ghost_filter_off_is_not_swallowed_by_the_default_on_fallback(tmp_path, monkeypatch):
    """`is not False` (not truthiness) is the only correct test here —
    the field defaults ON, so a bare `or True` fallback would make an
    explicit False indistinguishable from "never set"."""
    monkeypatch.setattr(app_state, "settings", _settings(tmp_path, {"track_filter_ghosts": False}))
    monkeypatch.setattr(app_state, "storage_root", tmp_path)
    assert H.net_state(CAM)["tuning"]["track_filter_ghosts"] is False
