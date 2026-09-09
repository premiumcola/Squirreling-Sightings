"""``GET /api/media/queue-status`` — the global encode queue, for real.

The per-camera media list can only ever show its own "hängt" tiles; a
clip queued behind another camera's burst is invisible there. This
route is the one place a position and an ETA can be told honestly,
straight from ``camera_runtime/_recording/_encode_queue.py``'s own
in-memory state.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import app_state
from app.camera_runtime._recording import _encode_queue as q
from app.routes import media as media_routes

CAMERAS = [
    {"id": "cam_a", "name": "Squirrel Town 'Nut Bar'"},
    {"id": "cam_b", "name": "Werkstatt"},
]


@pytest.fixture(autouse=True)
def _reset_queue():
    with q._CV:
        q._running = 0
        q._wartend.clear()
        q._inflight.clear()
        q._camera_of.clear()
        q._recent_s.clear()
    yield
    with q._CV:
        q._running = 0
        q._wartend.clear()
        q._inflight.clear()
        q._camera_of.clear()
        q._recent_s.clear()


@pytest.fixture
def client(monkeypatch, tmp_storage_root: Path):
    app = Flask(__name__)
    app.register_blueprint(media_routes.bp)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(get_review=lambda _k: None), raising=False
    )
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(
        app_state,
        "get_effective_config",
        lambda *a, **k: {"cameras": CAMERAS, "storage": {}, "processing": {}},
        raising=False,
    )
    return app.test_client()


def test_empty_queue_has_no_fabricated_eta(client):
    resp = client.get("/api/media/queue-status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["running"] == 0
    assert body["queued"] == []
    assert body["avg_encode_s"] is None


def test_queued_items_carry_position_camera_name_and_eta(client):
    with q._CV:
        q._wartend.extend([("20260906-100000-000000", 1), ("20260906-110000-000000", 2)])
        q._camera_of["20260906-100000-000000"] = "cam_a"
        q._camera_of["20260906-110000-000000"] = "cam_b"
        q._recent_s.extend([20.0, 30.0])  # avg 25.0

    body = client.get("/api/media/queue-status").get_json()
    assert body["avg_encode_s"] == 25.0
    assert body["slots"] == q.ENCODE_SLOTS
    first, second = body["queued"]
    assert first["event_id"] == "20260906-100000-000000"
    assert first["camera_name"] == "Squirrel Town 'Nut Bar'"
    assert first["position"] == 1
    assert second["camera_name"] == "Werkstatt"
    assert second["position"] == 2
    # ETA rounds UP to whole slot-rounds — a clip at position 2 on 2 slots
    # is still due after the FIRST round finishes, not the second.
    import math

    slots = q.ENCODE_SLOTS
    assert first["eta_s"] == math.ceil(1 / slots) * 25.0
    assert second["eta_s"] == math.ceil(2 / slots) * 25.0


def test_unknown_camera_id_falls_back_to_the_id_itself(client):
    with q._CV:
        q._wartend.append(("20260906-100000-000000", 1))
        q._camera_of["20260906-100000-000000"] = "cam_unlisted"

    body = client.get("/api/media/queue-status").get_json()
    assert body["queued"][0]["camera_name"] == "cam_unlisted"
