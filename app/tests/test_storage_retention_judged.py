"""C5 · `cleanup_old` must not eat the judgement corpus.

`EventStore.cleanup_old` hard-unlinks every file under
motion_detection/ whose mtime is past `storage.retention_days`
(default 14) — with no exception for events a human has judged. Since
those verdicts are the training signal for threshold calibration, the
corpus dissolved inside the retention window.

The trap these tests pin: confirming an event REWRITES its JSON, so the
manifest gets a fresh mtime and survives on its own — while the
snapshot and the clip keep their original mtime and get deleted. A
"protect the JSON" fix alone would leave judged events without the
image they are a verdict about.

An unreadable JSON must stay mortal (otherwise every truncated manifest
becomes immortal) and must not crash the sweep.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import app_state
from app.storage import EventStore, is_judged_event, keep_judged_events_enabled

CAM = "reolink_cx810_gartendachterrasse_181"
DATE = "2026-05-01"
DAY = 86400.0


@pytest.fixture
def store(tmp_storage_root: Path) -> EventStore:
    """EventStore over the shared throwaway storage tree."""
    return EventStore(str(tmp_storage_root))


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    """`cleanup_old` resolves `storage.keep_judged_events` through
    app_state. Blank it so every test states its own setting."""
    monkeypatch.setattr(app_state, "settings", None, raising=False)
    monkeypatch.setattr(app_state, "base_cfg", None, raising=False)


def _age(path: Path, days: float) -> None:
    stamp = time.time() - days * DAY
    os.utime(path, (stamp, stamp))


def _event_files(store: EventStore, event_id: str) -> dict[str, Path]:
    """The on-disk family of one event: manifest, snapshot, clip and
    the tracks.json sidecar — all sharing the event id as stem."""
    day_dir = store.events_dir / CAM / DATE
    day_dir.mkdir(parents=True, exist_ok=True)
    return {
        "json": day_dir / f"{event_id}.json",
        "jpg": day_dir / f"{event_id}.jpg",
        "mp4": day_dir / f"{event_id}.mp4",
        "tracks": day_dir / f"{event_id}.tracks.json",
    }


def _write_event(
    store: EventStore,
    event_id: str,
    payload: dict,
    *,
    media_age: float,
    json_age: float | None = None,
) -> dict[str, Path]:
    """Lay down one full event and backdate it. `json_age` defaults to
    `media_age`; passing a smaller value models the confirm endpoint
    having rewritten the manifest after the media was captured."""
    files = _event_files(store, event_id)
    files["json"].write_text(json.dumps(payload), encoding="utf-8")
    files["jpg"].write_bytes(b"jpeg-bytes")
    files["mp4"].write_bytes(b"mp4-bytes")
    files["tracks"].write_text(json.dumps({"tracks": []}), encoding="utf-8")
    for key, path in files.items():
        _age(path, media_age if key != "json" else (media_age if json_age is None else json_age))
    return files


def _judged(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "camera_id": CAM,
        "labels": ["person"],
        "confirmed": True,
        "confirmed_at": "2026-05-01T12:00:00",
    }


def test_is_judged_event_marker_fields():
    """`confirmed` / `confirmed_at` mark a verdict; a default manifest
    and a non-dict payload do not."""
    assert is_judged_event({"confirmed": True}) is True
    assert is_judged_event({"confirmed_at": "2026-05-01T12:00:00"}) is True
    assert is_judged_event({"confirmed": False}) is False
    assert is_judged_event({"labels": ["person"]}) is False
    assert is_judged_event({}) is False
    assert is_judged_event(None) is False
    assert is_judged_event("not-a-dict") is False


def test_judged_event_survives_past_retention(store: EventStore):
    """The whole family — manifest, snapshot, clip, sidecar — outlives
    the retention window once a human confirmed the event."""
    eid = "20260501-120000-000001"
    files = _write_event(store, eid, _judged(eid), media_age=30)

    store.cleanup_old(14)

    for key, path in files.items():
        assert path.exists(), f"judged {key} was deleted"


def test_judged_media_survives_when_confirm_refreshed_the_json(store: EventStore):
    """Confirming rewrites the JSON, so the manifest is young and the
    media is old. Protecting the manifest alone would still lose the
    image the verdict is about."""
    eid = "20260501-120000-000002"
    files = _write_event(store, eid, _judged(eid), media_age=30, json_age=0)

    store.cleanup_old(14)

    assert files["json"].exists()
    assert files["jpg"].exists(), "snapshot of a judged event was deleted"
    assert files["mp4"].exists(), "clip of a judged event was deleted"


def test_unjudged_event_is_removed(store: EventStore, sample_event: dict):
    """The default manifest (`confirmed: False`) stays mortal."""
    eid = "20260501-120000-000003"
    files = _write_event(store, eid, {**sample_event, "event_id": eid}, media_age=30)

    removed = store.cleanup_old(14)

    assert removed == len(files)
    for key, path in files.items():
        assert not path.exists(), f"unjudged {key} survived"


def test_unreadable_json_does_not_crash_and_is_not_judged(store: EventStore):
    """A truncated manifest must not raise and must not become
    immortal — treating it as judged would pin corrupt files forever."""
    eid = "20260501-120000-000004"
    files = _event_files(store, eid)
    files["json"].write_text('{"event_id": "20260501-1200', encoding="utf-8")
    files["jpg"].write_bytes(b"jpeg-bytes")
    for path in (files["json"], files["jpg"]):
        _age(path, 30)

    assert store.judged_event_ids() == set()

    removed = store.cleanup_old(14)

    assert removed == 2
    assert not files["json"].exists()
    assert not files["jpg"].exists()


def test_unreadable_json_does_not_shield_a_judged_sibling(store: EventStore):
    """One corrupt file in the tree must not abort the scan before the
    judged events later in it are collected."""
    bad = "20260501-120000-000005"
    good = "20260501-120000-000006"
    bad_files = _event_files(store, bad)
    bad_files["json"].write_text("{{{", encoding="utf-8")
    _age(bad_files["json"], 30)
    good_files = _write_event(store, good, _judged(good), media_age=30)

    store.cleanup_old(14)

    assert not bad_files["json"].exists()
    assert good_files["jpg"].exists()


def test_keep_judged_false_removes_judged_events(store: EventStore):
    """The explicit opt-out restores the old behaviour."""
    eid = "20260501-120000-000007"
    files = _write_event(store, eid, _judged(eid), media_age=30)

    removed = store.cleanup_old(14, keep_judged=False)

    assert removed == len(files)
    for path in files.values():
        assert not path.exists()


def test_setting_off_in_settings_json_removes_judged(store: EventStore, monkeypatch):
    """`storage.keep_judged_events: false` in settings.json turns the
    protection off without any caller change."""
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(data={"storage": {"keep_judged_events": False}}),
        raising=False,
    )
    eid = "20260501-120000-000008"
    files = _write_event(store, eid, _judged(eid), media_age=30)

    removed = store.cleanup_old(14)

    assert removed == len(files)
    assert not files["json"].exists()


def test_keep_judged_events_enabled_resolution(monkeypatch):
    """Defaults to True; settings.json wins over config.yaml."""
    assert keep_judged_events_enabled() is True

    monkeypatch.setattr(
        app_state, "base_cfg", {"storage": {"keep_judged_events": False}}, raising=False
    )
    assert keep_judged_events_enabled() is False

    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(data={"storage": {"keep_judged_events": True}}),
        raising=False,
    )
    assert keep_judged_events_enabled() is True


def test_recent_files_are_never_touched(store: EventStore, sample_event: dict):
    """Retention still applies to everything inside the window."""
    eid = "20260501-120000-000009"
    files = _write_event(store, eid, {**sample_event, "event_id": eid}, media_age=1)

    assert store.cleanup_old(14) == 0
    for path in files.values():
        assert path.exists()
