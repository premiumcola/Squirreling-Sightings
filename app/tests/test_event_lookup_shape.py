"""The shape of GET /api/event/<id>, pinned.

This route is a hand-built projection of the event document, and that is
exactly why it needs a test: /api/camera/<cam>/media hands the WHOLE
event JSON through, so every key this one does not name is a key one
reader silently loses. It has happened twice — `provenance` (repaired,
and the repair left the comment that states the rule) and `whole_clip`,
the species-bearing block the player's object list prefers over every
other basis.

A key going missing is invisible at the call site: the frontend reads
`item?.whole_clip?.detections`, gets undefined, and quietly falls back to
a narrower source. Nothing throws and nothing logs. The assertion that
catches it is on the RESPONSE KEY SET, so the next key to be dropped —
or added without thought — fails here instead of in a panel.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from app import app_state
from app.routes import media as media_routes
from app.routes.media import EVENT_LOOKUP_KEYS
from app.storage import EventStore

CAM = "cam_lookup"
EVENT_ID = "20260902T101500_cam_lookup"

WHOLE_CLIP = {
    "detections": [
        {
            "track_id": 7,
            "label": "bird",
            "score": 0.81,
            "species": "Grünfink",
            "species_latin": "Chloris chloris",
            "model": "bird_classifier",
            "frames": 12,
            "first_s": 1.5,
            "last_s": 4.25,
        }
    ],
    "species": [
        {
            "species": "Grünfink",
            "species_latin": "Chloris chloris",
            "best_score": 0.81,
            "frames": 12,
        }
    ],
    "frames": 40,
    "truncated": False,
}


@pytest.fixture
def event_doc() -> dict:
    return {
        "event_id": EVENT_ID,
        "camera_id": CAM,
        "time": "2026-09-02 10:15:00",
        "labels": ["bird"],
        "top_label": "bird",
        "bird_species": "Grünfink",
        "video_relpath": f"motion_detection/{CAM}/2026-09-02/{EVENT_ID}.mp4",
        "snapshot_relpath": f"motion_detection/{CAM}/2026-09-02/{EVENT_ID}.jpg",
        "detections": [{"label": "bird", "score": 0.62}],
        "whole_clip": WHOLE_CLIP,
        "provenance": {"schema": 1, "camera": {"id": CAM}},
    }


@pytest.fixture
def client(monkeypatch, tmp_storage_root: Path, event_doc: dict):
    store = EventStore(str(tmp_storage_root))
    store.add_event(CAM, event_doc)
    monkeypatch.setattr(app_state, "store", store, raising=False)
    app = Flask(__name__)
    app.register_blueprint(media_routes.bp)
    return app.test_client()


def _get(client, event_id: str = EVENT_ID):
    return client.get(f"/api/event/{event_id}")


def test_response_key_set_is_exactly_the_declared_one(client):
    """The whole point of the file: no key leaves or joins by accident."""
    body = _get(client).get_json()
    assert set(body) == set(EVENT_LOOKUP_KEYS)


def test_whole_clip_survives_the_projection(client):
    """A deep-linked clip must get the same object list as one opened
    from the grid — which means the species-bearing block, not just a
    label."""
    body = _get(client).get_json()
    assert body["whole_clip"] == WHOLE_CLIP
    assert body["whole_clip"]["detections"][0]["species"] == "Grünfink"


def test_provenance_still_survives_it(client):
    """The repair this route's comment records. Pinned so it cannot be
    undone by the next edit to the projection."""
    assert _get(client).get_json()["provenance"] == {"schema": 1, "camera": {"id": CAM}}


def test_an_event_without_the_block_answers_null_not_404(client, tmp_storage_root: Path):
    """Every event recorded before the aggregate existed has no
    `whole_clip`. The key must still be present and null — the frontend
    reads it optionally, and a 500 here would break every old deep
    link."""
    store = EventStore(str(tmp_storage_root))
    old_id = "20240101T090000_cam_lookup"
    store.add_event(
        CAM, {"event_id": old_id, "camera_id": CAM, "time": "2024-01-01 09:00:00", "labels": []}
    )
    body = _get(client, old_id).get_json()
    assert set(body) == set(EVENT_LOOKUP_KEYS)
    assert body["whole_clip"] is None
    assert body["provenance"] is None


def test_top_label_still_falls_back_to_primary_label(client, tmp_storage_root: Path):
    """The oldest events carry the class under `primary_label`, and the
    router filters the media list on this field — an empty one loses the
    event it was asked to open."""
    store = EventStore(str(tmp_storage_root))
    legacy_id = "20230601T080000_cam_lookup"
    store.add_event(
        CAM,
        {
            "event_id": legacy_id,
            "camera_id": CAM,
            "time": "2023-06-01 08:00:00",
            "primary_label": "cat",
        },
    )
    assert _get(client, legacy_id).get_json()["top_label"] == "cat"


def test_missing_event_is_a_404(client):
    res = _get(client, "20200101T000000_nope")
    assert res.status_code == 404
    assert res.get_json() == {"error": "not found"}
