"""The /api/netz surface, through a real Flask app.

The non-negotiable this pins: the endpoint returns the EFFECTIVE value
per class through the documented resolution order, PLUS the layer that
won, the evidence count and the guard-rail bounds. The operator's
original complaint is that the settings showed the wrong layer — a
prettier wrong display would be a failure, not a fix.
"""

from __future__ import annotations

import pytest
from flask import Flask

from app import app_state, net_archive
from app.routes import netz as netz_routes
from app.settings_store import SettingsStore
from app.storage import EventStore
from app.thresholds._apply import push_for, spawn_for

CAM = "cam_werkstatt"


@pytest.fixture
def client(tmp_storage_root, monkeypatch):
    base = {
        "app": {},
        "storage": {"root": str(tmp_storage_root)},
        "cameras": [
            {
                "id": CAM,
                "name": "Werkstatt",
                "rtsp_url": "rtsp://cam.lan/s",
                "object_filter": ["person", "cat", "dog", "bird"],
                "role": "security",
            },
            {
                "id": "cam_nutbar",
                "name": "Nut Bar",
                "rtsp_url": "rtsp://cam.lan/n",
                "object_filter": ["squirrel", "bird"],
                "role": "wildlife",
            },
        ],
        "telegram": {"push": {"labels": {"person": {"push": True, "threshold": 0.85}}}},
        "mqtt": {},
        "processing": {},
    }
    settings = SettingsStore(tmp_storage_root / "settings.json", base)
    monkeypatch.setattr(app_state, "settings", settings)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root)
    monkeypatch.setattr(app_state, "store", EventStore(tmp_storage_root), raising=False)
    monkeypatch.setattr(app_state, "rebuild_runtimes", lambda: None, raising=False)
    app = Flask(__name__)
    app.register_blueprint(netz_routes.bp)
    return app.test_client()


# ── state ─────────────────────────────────────────────────────────────


def test_state_reports_the_effective_value_and_the_layer_that_won(client):
    body = client.get(f"/api/netz/state?cam={CAM}").get_json()
    assert body["ok"] is True
    person = next(a for a in body["axes"] if a["label"] == "person")
    assert person["E"] == 50
    assert person["spawn"] == spawn_for("person", 50)
    assert person["push"] == 0.85
    # WHICH layer produced each number — the whole point of the endpoint.
    assert person["source"]["push"] == "global"
    # `source` and `provenance` answer two DIFFERENT questions, and the
    # difference shows up right here on a fresh install:
    #   source     — which ladder layer physically held the value.
    #                `default_camera` SEEDS label_thresholds with
    #                LABEL_THRESHOLD_DEFAULTS, so the camera layer holds
    #                0.45 even though nobody chose it. That is a true
    #                statement about the config.
    #   provenance — which FORCE last moved the axis. Nobody has, so it
    #                is "werk", and that is what the vertex outline
    #                draws.
    # Reporting only `source` would make an untouched axis look tuned;
    # reporting only `provenance` would hide where the number lives.
    assert person["source"]["spawn"] == "camera"
    assert person["spawn"] == spawn_for("person", 50)
    assert person["provenance"] == "werk"


def test_state_carries_the_rails_and_the_frozen_list(client):
    body = client.get(f"/api/netz/state?cam={CAM}").get_json()
    assert body["rails"]["spawn"] == [0.25, 0.90]
    assert body["rails"]["push"] == [0.45, 0.98]
    assert body["rails"]["person_auto_floor_e"] == 35
    assert body["rails"]["max_learner_step_e"] == 5
    # Naming the frozen values is the difference between "frozen" and
    # "forgotten".
    keys = {f["key"] for f in body["frozen"]}
    assert "confirmation_window" in keys
    assert "detection_min_score" in keys
    assert "label_veto" in keys


def test_axes_follow_the_class_filter_in_the_fixed_global_order(client):
    body = client.get(f"/api/netz/state?cam={CAM}").get_json()
    assert [a["label"] for a in body["axes"]] == ["person", "cat", "dog", "bird"]
    other = client.get("/api/netz/state?cam=cam_nutbar").get_json()
    # Filtered by the camera's own enabled set, but never re-sorted.
    assert [a["label"] for a in other["axes"]] == ["bird", "squirrel"]


def test_the_empty_state_reports_no_evidence(client):
    body = client.get(f"/api/netz/state?cam={CAM}").get_json()
    for axis in body["axes"]:
        assert axis["evidence"]["judged"] == 0
        assert axis["evidence"]["ready"] is False
        assert axis["proposal"] is None
    assert body["progress"]["judged"] == 0
    assert body["progress"]["needed"] == 50


def test_the_camera_switcher_lists_every_camera_with_its_role(client):
    body = client.get(f"/api/netz/state?cam={CAM}").get_json()
    roles = {c["id"]: c["role"] for c in body["cameras"]}
    assert roles == {CAM: "security", "cam_nutbar": "wildlife"}


def test_an_unknown_camera_is_a_404(client):
    assert client.get("/api/netz/state?cam=nope").status_code == 404


# ── the drag ──────────────────────────────────────────────────────────


def test_a_patch_moves_the_effective_value_and_pins_the_axis(client):
    res = client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 70}})
    assert res.status_code == 200
    body = res.get_json()
    assert body["written"]["person"]["spawn"] == spawn_for("person", 70)
    assert body["written"]["person"]["push"] == push_for("person", 70)
    person = next(a for a in body["state"]["axes"] if a["label"] == "person")
    assert person["E"] == 70
    # The camera layer now wins, and the panel says so.
    assert person["source"]["push"] == "camera"
    assert person["source"]["spawn"] == "camera"
    assert person["provenance"] == "manuell"
    # More sensitive: the bar came down.
    assert person["push"] < 0.85


def test_a_drag_unpins_the_learner_for_that_axis(client):
    cam = app_state.settings.get_camera(CAM)
    app_state.settings.upsert_camera({**cam, "net_adapted": {"person": {"E": 20}}})
    client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 70}})
    stored = app_state.settings.get_camera(CAM)
    assert "person" not in stored["net_adapted"]
    assert stored["net_pin"]["person"]["E"] == 70


def test_a_commit_writes_one_archive_record_per_axis(client):
    client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 62, "cat": 40}})
    page = net_archive.list_records(app_state.storage_root)
    kinds = {r["kind"] for r in page["items"]}
    assert kinds == {net_archive.KIND_NETZ}
    assert page["total"] == 2
    reasons = " ".join(r["reason_de"] for r in page["items"])
    assert "von 50 auf 62" in reasons
    assert "von 50 auf 40" in reasons


def test_an_empty_patch_is_rejected(client):
    assert client.patch(f"/api/netz/{CAM}/axes", json={"axes": {}}).status_code == 400


def test_reset_returns_the_axis_to_factory_and_unpins_it(client):
    client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 70}})
    res = client.post(f"/api/netz/{CAM}/reset", json={"label": "person"})
    assert res.status_code == 200
    person = next(a for a in res.get_json()["state"]["axes"] if a["label"] == "person")
    assert person["E"] == 50
    assert person["provenance"] == "werk"
    assert person["push"] == 0.85


def test_reset_without_a_label_clears_every_axis(client):
    client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 70, "cat": 30}})
    res = client.post(f"/api/netz/{CAM}/reset", json={})
    assert set(res.get_json()["reset"]) == {"person", "cat", "dog", "bird"}
    assert app_state.settings.get_camera(CAM)["net_pin"] == {}


def test_the_automatik_toggle_is_the_single_on_off(client):
    res = client.post(f"/api/netz/{CAM}/auto", json={"enabled": False})
    assert res.get_json()["state"]["auto"] is False
    assert app_state.settings.get_camera(CAM)["net_auto"] is False


def test_preview_says_so_when_there_is_no_corpus(client):
    body = client.get(f"/api/netz/{CAM}/preview?label=person&e=62").get_json()
    assert body["ok"] is True
    assert body["has_corpus"] is False
    assert body["thresholds"]["push"] == push_for("person", 62)


def test_preview_rejects_a_missing_label(client):
    assert client.get(f"/api/netz/{CAM}/preview?e=62").status_code == 400


# ── the archive ───────────────────────────────────────────────────────


def test_the_archive_is_empty_and_says_so(client):
    body = client.get("/api/netz/archive").get_json()
    assert body["ok"] is True
    assert body["items"] == []
    assert body["total"] == 0


def test_restore_puts_the_net_back_and_pins_what_it_touched(client):
    client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 62}})
    eid = net_archive.list_records(app_state.storage_root)["items"][0]["event_id"]
    client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 20}})
    assert app_state.settings.get_camera(CAM)["net_pin"]["person"]["E"] == 20

    res = client.post(f"/api/netz/archive/{eid}/restore")
    assert res.status_code == 200
    person = next(a for a in res.get_json()["state"]["axes"] if a["label"] == "person")
    assert person["E"] == 62
    assert person["provenance"] == "manuell"


def test_restoring_a_missing_record_is_a_404(client):
    assert client.post("/api/netz/archive/nope/restore").status_code == 404


def test_a_frame_that_was_never_written_is_a_404_not_a_500(client):
    assert client.get("/api/netz/archive/nope/frame.jpg").status_code == 404
