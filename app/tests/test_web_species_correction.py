"""Event-level species correction — the web analogue of the Telegram
species picker (see ``test_telegram_species_correction.py``, the
reference implementation this mirrors: same seeded event, same
``confirmed_video_count`` assertions, same "unsicher leaves the guess
in place and counts nothing" behaviour).

Flask test client over just the `events` blueprint (bare Flask app, no
camera runtimes / Telegram poller — same reasoning as
`test_web_verdicts.py`), backed by a REAL `EventStore` rather than a
stub so `add_event`/`get_event`/`update_event` round-trip for real and
`confirmed_video_count` reads the counter file the route actually wrote.
"""

from __future__ import annotations

import pytest

from app import app_state
from app.detection_feedback import iter_records
from app.routes import events as events_routes
from app.species_video_count import confirmed_video_count
from app.storage import EventStore

flask = pytest.importorskip("flask")

CAM_ID = "cam_nutbar"
EVENT_ID = "20260909-120000-000001"


@pytest.fixture
def rig(tmp_storage_root, monkeypatch):
    """(test client, real EventStore) pair, both wired to the same tmp root."""
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    store = EventStore(str(tmp_storage_root))
    monkeypatch.setattr(app_state, "store", store, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(events_routes.bp)
    return app.test_client(), store


def _seed_event(store, **overrides):
    payload = {
        "event_id": EVENT_ID,
        "camera_id": CAM_ID,
        "labels": ["bird"],
        "top_label": "bird",
        "bird_species": "Elster",
        "species_candidates": [
            {"name": "Elster", "latin": "Pica pica", "score": 0.59},
            {"name": "Kohlmeise", "latin": "Parus major", "score": 0.31},
        ],
        "time": "2026-09-09T12:00:00",
    }
    payload.update(overrides)
    store.add_event(CAM_ID, payload)
    return payload


def _verdicts(storage_root):
    return [r for r in iter_records(storage_root) if r.get("kind") == "verdict"]


def _post(client, species, event_id=EVENT_ID):
    return client.post(
        f"/api/camera/{CAM_ID}/events/{event_id}/species",
        json={"species": species},
    )


# ── picking a species ─────────────────────────────────────────────────


def test_picking_a_species_sets_it_and_counts_one_video(rig, tmp_storage_root):
    client, store = rig
    _seed_event(store)

    resp = _post(client, "Kohlmeise")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["bird_species"] == "Kohlmeise"
    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated["bird_species"] == "Kohlmeise"
    assert confirmed_video_count(tmp_storage_root, "Kohlmeise") == 1
    # The original (superseded) guess must not gain a count from this.
    assert confirmed_video_count(tmp_storage_root, "Elster") == 0


def test_ledger_records_a_correct_verdict_naming_the_species(rig, tmp_storage_root):
    client, store = rig
    _seed_event(store)

    _post(client, "Kohlmeise")

    records = _verdicts(tmp_storage_root)
    assert len(records) == 1
    rec = records[0]
    assert rec["correct"] is True
    assert rec["source"] == "web"
    assert rec["species"] == "Kohlmeise"
    assert rec["event_id"] == EVENT_ID
    assert rec["cam"] == CAM_ID


# ── "unsicher" (species=None) ───────────────────────────────────────────


def test_unsicher_confirms_the_bird_but_counts_no_species(rig, tmp_storage_root):
    client, store = rig
    _seed_event(store)

    resp = _post(client, None)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    # Left exactly as the original best-effort guess — mirrors
    # `_cb_species_unsure`, which never calls `_correct_bird_species`.
    assert body["bird_species"] == "Elster"
    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated["bird_species"] == "Elster"
    assert confirmed_video_count(tmp_storage_root, "Elster") == 0
    assert confirmed_video_count(tmp_storage_root, "Kohlmeise") == 0

    records = _verdicts(tmp_storage_root)
    assert len(records) == 1
    assert records[0]["correct"] is True
    assert records[0]["species"] is None


def test_blank_species_string_is_treated_as_unsicher(rig, tmp_storage_root):
    client, store = rig
    _seed_event(store)

    resp = _post(client, "   ")

    assert resp.status_code == 200
    assert resp.get_json()["bird_species"] == "Elster"
    assert confirmed_video_count(tmp_storage_root, "Elster") == 0


# ── missing event ────────────────────────────────────────────────────────


def test_missing_event_404s(rig, tmp_storage_root):
    client, _store = rig

    resp = _post(client, "Kohlmeise", event_id="evt_does_not_exist")

    assert resp.status_code == 404
    assert resp.get_json() == {"ok": False, "error": "Event nicht gefunden"}
    assert _verdicts(tmp_storage_root) == []


# ── ledger failure must not break the request ───────────────────────────


def test_ledger_failure_never_breaks_the_request(rig, monkeypatch):
    client, store = rig
    _seed_event(store)

    def _boom(*args, **kwargs):
        raise RuntimeError("ledger on fire")

    monkeypatch.setattr(events_routes, "record_verdict", _boom)
    resp = _post(client, "Kohlmeise")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
