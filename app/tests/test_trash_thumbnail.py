"""Papierkorb preview image — `trash.list_trashed()` exposes `thumb_url`.

User ask: the operator wants a preview per trashed row so they can tell
one deleted clip from the next before restoring or purging. The
snapshot that shipped with the event is already moved into
`storage/.trash/<cam>/<event>/` by `move_to_trash`/`retire_to_trash` —
nothing new gets written or moved for this, it's read-only exposure of
a file that's already there, served through the existing
`/media/<path:subpath>` route (routes/bootstrap/_shell.py) since `.trash`
lives directly under the same `storage_root` that route serves from.

These tests pin: the canonical `<event_id>.jpg` wins when present, a
differently-named `*.jpg` is used as a fallback, a Telegram-only
`*.best.jpg` render is never mistaken for the event's own snapshot,
and an entry with no image at all reports `thumb_url: None` rather
than a broken path.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import app_state, trash


@pytest.fixture
def trash_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(app_state, "store", SimpleNamespace(root=str(tmp_path)), raising=False)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"trash": {"grace_days": 7}}), raising=False
    )
    root = tmp_path / ".trash"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _entry(root: Path, cam: str, event_id: str, *, files: tuple[str, ...] = ()) -> Path:
    ev = root / cam / event_id
    ev.mkdir(parents=True, exist_ok=True)
    for name in files:
        (ev / name).write_bytes(b"payload")
    (ev / "meta.json").write_text(
        json.dumps({"cam_id": cam, "event_id": event_id, "trashed_at": datetime.now().isoformat()}),
        encoding="utf-8",
    )
    return ev


def test_canonical_snapshot_is_exposed_as_thumb_url(trash_root: Path):
    _entry(trash_root, "cam1", "ev1", files=("ev1.jpg", "ev1.mp4", "ev1.json"))
    items = trash.list_trashed()
    assert len(items) == 1
    assert items[0]["thumb_url"] == "/media/.trash/cam1/ev1/ev1.jpg"


def test_no_image_at_all_reports_none(trash_root: Path):
    _entry(trash_root, "cam1", "ev1", files=("ev1.mp4", "ev1.json"))
    items = trash.list_trashed()
    assert items[0]["thumb_url"] is None


def test_falls_back_to_a_differently_named_jpg(trash_root: Path):
    """A retention-retired entry may not carry the canonical
    `<event_id>.jpg` name — any other still should still surface."""
    _entry(trash_root, "cam1", "ev1", files=("snapshot_2026.jpg", "ev1.mp4"))
    items = trash.list_trashed()
    assert items[0]["thumb_url"] == "/media/.trash/cam1/ev1/snapshot_2026.jpg"


def test_best_jpg_alone_is_not_treated_as_the_preview(trash_root: Path):
    """`<event_id>.best.jpg` is a Telegram-only bbox-burned render
    (telegram_bot/_outbound/_best_frame.py) — never the event's real
    snapshot, and not guaranteed to exist for most events."""
    _entry(trash_root, "cam1", "ev1", files=("ev1.best.jpg", "ev1.mp4"))
    items = trash.list_trashed()
    assert items[0]["thumb_url"] is None


def test_canonical_snapshot_wins_over_a_best_jpg_sitting_next_to_it(trash_root: Path):
    _entry(trash_root, "cam1", "ev1", files=("ev1.jpg", "ev1.best.jpg"))
    items = trash.list_trashed()
    assert items[0]["thumb_url"] == "/media/.trash/cam1/ev1/ev1.jpg"
