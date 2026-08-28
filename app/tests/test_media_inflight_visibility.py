"""A clip must be visible in the library *while* it is being made.

The bug this locks out is why the user said "Dann seh ich das nirgendwo".

`orchestration.js` has rendered a "wird aufgenommen…" placeholder tile
for `status === 'recording'` since the stub was introduced, and
`_start_ffmpeg_recording` writes that stub at trigger time — so on
paper the tile appears the instant motion fires. It never did. The
recording stub carries `snapshot_relpath: null` and `video_relpath:
null` (there is no file yet; that is the entire point of a stub), and
`/api/camera/<id>/media` asks the store for `media_only=True`, whose
test is literally "does this event point at a file". The stub failed
it. Every in-flight clip was filtered out of the response for the whole
window it was in flight, and the placeholder rendered for nobody.

The fix belongs in the route, not in `media_only`: "has a file on disk"
is a correct and useful predicate for EventStore to keep answering. The
media library just needs a wider question — "has a file, *or* is still
being produced".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import app_state
from app.routes import media as media_routes
from app.storage import EventStore

CAM = "reolink_cx810_gartendachterrasse_181"
DATE = "2026-08-27"


@pytest.fixture
def store(tmp_storage_root: Path) -> EventStore:
    return EventStore(str(tmp_storage_root))


@pytest.fixture
def client(monkeypatch, store, tmp_storage_root: Path):
    """Flask test client over the media blueprint alone."""
    app = Flask(__name__)
    app.register_blueprint(media_routes.bp)
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(get_review=lambda _k: None), raising=False
    )
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(
        app_state,
        "get_effective_config",
        lambda *a, **k: {"cameras": [], "storage": {}, "processing": {"clip_max_duration_s": 120}},
        raising=False,
    )
    return app.test_client()


def _write_event(root: Path, payload: dict) -> None:
    day = root / "motion_detection" / CAM / DATE
    day.mkdir(parents=True, exist_ok=True)
    (day / f"{payload['event_id']}.json").write_text(json.dumps(payload), encoding="utf-8")


def _stub(event_id: str, *, stage: str, since: datetime, **extra) -> dict:
    ev = {
        "event_id": event_id,
        "camera_id": CAM,
        "time": since.isoformat(timespec="seconds"),
        "labels": ["motion"],
        "snapshot_relpath": None,
        "snapshot_url": None,
        "video_relpath": None,
        "video_url": None,
        "stage": stage,
        "stage_since": since.isoformat(timespec="seconds"),
        "status": {"recording": "recording", "ready": "ready"}.get(stage, "processing"),
    }
    ev.update(extra)
    return ev


def _finished(root: Path, event_id: str) -> dict:
    """A finished clip — manifest AND the files it points at.

    The files are not decoration. Since the media-index rewrite an event
    only counts when its media is really on disk and non-empty, so a
    manifest pointing at a deleted mp4 is deliberately invisible. The
    mp4 body is padded past ``MIN_VIDEO_BYTES`` for the same reason: a
    0-byte file is not a clip.
    """
    day = root / "motion_detection" / CAM / DATE
    day.mkdir(parents=True, exist_ok=True)
    (day / f"{event_id}.mp4").write_bytes(b"\x00" * 4096)
    (day / f"{event_id}.jpg").write_bytes(b"\xff\xd8\xff")
    return {
        "event_id": event_id,
        "camera_id": CAM,
        "time": f"{DATE}T10:00:00",
        "labels": ["motion"],
        "video_relpath": f"motion_detection/{CAM}/{DATE}/{event_id}.mp4",
        "snapshot_relpath": f"motion_detection/{CAM}/{DATE}/{event_id}.jpg",
        "status": "ready",
    }


def _items(client):
    res = client.get(f"/api/camera/{CAM}/media?limit=9999")
    assert res.status_code == 200
    return res.get_json()


# ── the load-bearing one ───────────────────────────────────────────────────
def test_a_clip_being_recorded_appears_in_the_library(client, tmp_storage_root):
    """Fails against the old route: media_only=True dropped this event."""
    _write_event(
        tmp_storage_root, _stub("20260827-120000-000000", stage="recording", since=datetime.now())
    )
    body = _items(client)
    ids = [i["event_id"] for i in body["items"]]
    assert "20260827-120000-000000" in ids
    assert body["total_count"] == 1


def test_a_clip_being_encoded_appears_in_the_library(client, tmp_storage_root):
    _write_event(
        tmp_storage_root, _stub("20260827-120100-000000", stage="encoding", since=datetime.now())
    )
    assert [i["event_id"] for i in _items(client)["items"]] == ["20260827-120100-000000"]


def test_metadata_only_events_stay_hidden(client, tmp_storage_root):
    """The widening is "or in flight", not "show everything". An event
    that produced no file and is not being produced is still noise."""
    _write_event(
        tmp_storage_root,
        {
            "event_id": "20260827-090000-000000",
            "camera_id": CAM,
            "time": f"{DATE}T09:00:00",
            "labels": ["motion"],
            "status": "ready",
        },
    )
    assert _items(client)["items"] == []


def test_finished_clips_are_unaffected(client, tmp_storage_root):
    _write_event(tmp_storage_root, _finished(tmp_storage_root, "20260827-100000-000000"))
    body = _items(client)
    assert [i["event_id"] for i in body["items"]] == ["20260827-100000-000000"]
    assert "stage_stalled" not in body["items"][0]


# ── the derived fields the tile renders ────────────────────────────────────
def test_in_flight_items_carry_stage_and_age(client, tmp_storage_root):
    since = datetime.now() - timedelta(seconds=12)
    _write_event(tmp_storage_root, _stub("20260827-120200-000000", stage="encoding", since=since))
    item = _items(client)["items"][0]
    assert item["stage"] == "encoding"
    assert 10 <= item["stage_age_s"] <= 20
    assert item["stage_stalled"] is False


def test_an_abandoned_stub_is_reported_stalled_not_busy(client, tmp_storage_root):
    """Container restarted mid-clip. Nothing will ever advance this
    event, so the tile must stop pretending work is happening."""
    since = datetime.now() - timedelta(hours=3)
    _write_event(tmp_storage_root, _stub("20260827-080000-000000", stage="recording", since=since))
    item = _items(client)["items"][0]
    assert item["stage_stalled"] is True


def test_legacy_processing_events_still_resolve(client, tmp_storage_root):
    """Events written before `stage` existed carry status only."""
    ev = _stub("20260827-120300-000000", stage="processing", since=datetime.now())
    ev.pop("stage")
    ev.pop("stage_since")
    _write_event(tmp_storage_root, ev)
    item = _items(client)["items"][0]
    assert item["stage"] == "processing"
    assert item["stage_stalled"] is False


# ── ordering + pagination must survive the rewrite ─────────────────────────
def test_newest_first_ordering_and_offset_still_hold(client, tmp_storage_root):
    _write_event(tmp_storage_root, _finished(tmp_storage_root, "20260827-100000-000000"))
    _write_event(
        tmp_storage_root,
        _stub("20260827-235900-000000", stage="recording", since=datetime.now()),
    )
    body = _items(client)
    assert [i["event_id"] for i in body["items"]] == [
        "20260827-235900-000000",
        "20260827-100000-000000",
    ]
    assert body["total_count"] == 2
    page2 = client.get(f"/api/camera/{CAM}/media?limit=1&offset=1").get_json()
    assert [i["event_id"] for i in page2["items"]] == ["20260827-100000-000000"]
    assert page2["total_count"] == 2, "total_count must count all matches, not the page"
