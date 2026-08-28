"""FB-1 · the web judgement surfaces must reach the ledger.

Before this, the ledger heard only from the two Telegram buttons. The
label editor — the product's de-facto correction surface — wrote
``event["labels"]`` and nothing else, and `corrected_label` had zero
producers anywhere in the codebase. Every correction a user made in the
web UI was thrown away.

The tests boot only the `events` blueprint on a bare Flask app: the real
boot sequence constructs camera runtimes and a Telegram poller, and a
second poller against the live token is exactly the conflict this repo
spent days chasing.
"""

from __future__ import annotations

import pytest

from app import app_state
from app import trash as _trash
from app.detection_feedback import iter_records
from app.routes import events as events_routes

flask = pytest.importorskip("flask")

CAM = "reolink_cx810_werkstatt_172"
EID = "evt_web_verdict_001"


class _StoreStub:
    """Two methods, which is exactly what these handlers touch."""

    def __init__(self, event):
        self.event = event
        self.updates = []

    def get_event(self, cam_id, event_id):
        if cam_id != CAM or event_id != EID:
            return None
        return self.event

    def update_event(self, cam_id, event_id, event):
        self.updates.append((cam_id, event_id, dict(event)))


@pytest.fixture
def client(tmp_storage_root, monkeypatch):
    """Flask test client wired to a temp storage root and a stub store."""
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(events_routes.bp)
    return app.test_client()


@pytest.fixture
def store(monkeypatch):
    def _make(**overrides):
        event = {"event_id": EID, "camera_id": CAM, "labels": ["cat"], "top_label": "cat"}
        event.update(overrides)
        stub = _StoreStub(event)
        monkeypatch.setattr(app_state, "store", stub, raising=False)
        return stub

    return _make


def _verdicts(storage_root):
    return [r for r in iter_records(storage_root) if r.get("kind") == "verdict"]


def test_confirm_writes_a_verdict(client, store, tmp_storage_root):
    store()
    resp = client.post(f"/api/camera/{CAM}/events/{EID}/confirm")
    assert resp.status_code == 200

    records = _verdicts(tmp_storage_root)
    assert len(records) == 1
    rec = records[0]
    assert rec["correct"] is True
    assert rec["source"] == "web"
    assert rec["event_id"] == EID
    # Without the camera the record cannot feed a per-camera calibration,
    # which is the whole point of keeping it.
    assert rec["cam"] == CAM


def test_changed_top_label_writes_the_correction(client, store, tmp_storage_root):
    store(labels=["cat"], top_label="cat")
    resp = client.post(
        f"/api/camera/{CAM}/events/{EID}/labels",
        json={"labels": ["squirrel"]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["top_label"] == "squirrel"

    records = _verdicts(tmp_storage_root)
    assert len(records) == 1
    assert records[0]["correct"] is False
    assert records[0]["corrected_label"] == "squirrel"
    assert records[0]["source"] == "web"
    assert records[0]["cam"] == CAM


def test_added_secondary_label_writes_nothing(client, store, tmp_storage_root):
    """The user did not dispute the detector — he annotated. Recording
    that as `correct=False` would poison the corpus with events nobody
    ever called wrong."""
    store(labels=["cat"], top_label="cat")
    resp = client.post(
        f"/api/camera/{CAM}/events/{EID}/labels",
        json={"labels": ["cat", "dog"]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["top_label"] == "cat"
    assert _verdicts(tmp_storage_root) == []


def test_cleared_labels_record_nothing(client, store, tmp_storage_root):
    """An emptied list must NOT be filed as a correction to "motion".

    "motion" there is OUR fallback, not a claim the user made. Recording
    it would invent a positive example of a class nobody asserted — and
    a poisoned corpus is worse than an empty one, because it silently
    biases every threshold later calibrated from it.
    """
    store(labels=["cat"], top_label="cat")
    client.post(f"/api/camera/{CAM}/events/{EID}/labels", json={"labels": []})

    assert _verdicts(tmp_storage_root) == []


def test_two_tap_correction_files_exactly_one_verdict(client, store, tmp_storage_root):
    """The label editor toggles one bubble per request, so cat→squirrel
    arrives as remove-cat then add-squirrel. Only the second tap is a
    claim; booking the intermediate empty state would file a spurious
    correction as well."""
    store(labels=["cat"], top_label="cat")
    client.post(f"/api/camera/{CAM}/events/{EID}/labels", json={"labels": []})
    client.post(f"/api/camera/{CAM}/events/{EID}/labels", json={"labels": ["squirrel"]})

    records = _verdicts(tmp_storage_root)
    assert len(records) == 1, f"expected one verdict for one correction, got {len(records)}"
    assert records[0]["corrected_label"] == "squirrel"


def test_delete_writes_a_false_alarm_verdict(client, store, tmp_storage_root, monkeypatch):
    store()
    monkeypatch.setattr(
        _trash,
        "move_to_trash",
        lambda cam_id, event_id: {"json_deleted": True, "trashed": True},
    )
    resp = client.delete(f"/api/camera/{CAM}/events/{EID}")
    assert resp.status_code == 200

    records = _verdicts(tmp_storage_root)
    assert len(records) == 1
    assert records[0]["correct"] is False
    assert records[0]["source"] == "web_delete"
    assert records[0]["cam"] == CAM


def test_bulk_delete_books_a_false_alarm_per_event(client, tmp_storage_root, monkeypatch):
    """P1 · this is the gesture that clears a run of false alarms, and
    `confirmed-false >= 20` is the binding constraint on every stratum.
    Treating it as mere housekeeping threw away the scarcest evidence in
    the corpus, a batch at a time."""
    monkeypatch.setattr(
        _trash,
        "move_to_trash",
        lambda cam_id, event_id: {"json_deleted": True, "trashed": True},
    )
    resp = client.post(
        f"/api/camera/{CAM}/events/delete-bulk",
        json={"event_ids": [EID, "evt_other"]},
    )
    assert resp.status_code == 200
    records = _verdicts(tmp_storage_root)
    assert len(records) == 2
    assert {r["source"] for r in records} == {"web_bulk_delete"}
    assert all(r["correct"] is False for r in records)
    assert all(r["cam"] == CAM for r in records)


def test_bulk_delete_never_books_a_timelapse(client, tmp_storage_root, monkeypatch):
    """The same `tl_` guard the single-delete path carries. A timelapse
    manifest nobody judged must never enter the corpus as a false alarm
    — a poisoned corpus is worse than an empty one."""
    monkeypatch.setattr(
        _trash,
        "move_to_trash",
        lambda cam_id, event_id: {"json_deleted": True, "trashed": True},
    )
    resp = client.post(
        f"/api/camera/{CAM}/events/delete-bulk",
        json={"event_ids": ["tl_2026-08-28", EID]},
    )
    assert resp.status_code == 200
    records = _verdicts(tmp_storage_root)
    assert [r["event_id"] for r in records] == [EID]


def test_ledger_failure_never_breaks_the_request(client, store, monkeypatch):
    """The ledger's own contract is best-effort; the handler must keep
    that promise for anything the call itself can raise."""
    store()

    def _boom(*args, **kwargs):
        raise RuntimeError("ledger on fire")

    monkeypatch.setattr(events_routes, "record_verdict", _boom)
    resp = client.post(f"/api/camera/{CAM}/events/{EID}/confirm")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_missing_event_still_404s(client, store, tmp_storage_root):
    store()
    resp = client.post(f"/api/camera/{CAM}/events/evt_nope/confirm")
    assert resp.status_code == 404
    assert _verdicts(tmp_storage_root) == []


def test_a_404_delete_records_nothing(client, tmp_storage_root, monkeypatch):
    """A double-tap or client retry must not book a second false alarm.

    The verdict used to be written above the existence check, so a
    DELETE on an already-deleted event returned 404 and still filed a
    correct=False record — inflating the false-alarm count for an event
    the user judged exactly once.
    """
    monkeypatch.setattr(
        _trash,
        "move_to_trash",
        lambda cam_id, event_id: {"json_deleted": False, "trashed": False},
    )
    resp = client.delete(f"/api/camera/{CAM}/events/evt_does_not_exist")
    assert resp.status_code == 404
    assert _verdicts(tmp_storage_root) == []


def test_deleting_a_timelapse_records_nothing(client, tmp_storage_root, monkeypatch):
    """The timelapse card's delete posts a backstop DELETE for `tl_<stem>`.

    Booking that as a false alarm files a judgement on a timelapse video
    nobody disputed — pure fabrication, and it lands in the same corpus
    the detection thresholds are calibrated from.
    """
    monkeypatch.setattr(
        _trash,
        "move_to_trash",
        lambda cam_id, event_id: {"json_deleted": True, "trashed": True},
    )
    resp = client.delete(f"/api/camera/{CAM}/events/tl_20260813")
    assert resp.status_code == 200
    assert _verdicts(tmp_storage_root) == []
