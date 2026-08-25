"""Grace-period boundary for the trash sweep.

`cleanup_expired()` shipped with the docstring "wire into the existing
daily maintenance cron in a follow-up commit". That commit never
landed, so `storage/.trash` never emptied on its own (11 GB of stale
entries were found once) and the only way to clear it was a manual
POST /api/trash/empty. It is now called from
`maintenance._run_daily_cleanup`.

Since that makes it an automatic, irreversible delete, these tests pin
the boundary: entries inside the grace period must survive, entries
past it must go.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import app_state, trash


@pytest.fixture
def trash_root(tmp_path: Path, monkeypatch):
    """Point the trash module at a throwaway storage root."""
    monkeypatch.setattr(app_state, "store", SimpleNamespace(root=str(tmp_path)), raising=False)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"trash": {"grace_days": 7}}), raising=False
    )
    root = tmp_path / ".trash"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _entry(root: Path, cam: str, event_id: str, age_days: float | None, *, meta=True) -> Path:
    ev = root / cam / event_id
    ev.mkdir(parents=True, exist_ok=True)
    (ev / f"{event_id}.jpg").write_bytes(b"payload")
    if meta:
        stamp = (datetime.now() - timedelta(days=age_days)).isoformat()
        (ev / "meta.json").write_text(json.dumps({"trashed_at": stamp}), encoding="utf-8")
    return ev


def test_entry_inside_grace_survives(trash_root: Path):
    fresh = _entry(trash_root, "cam1", "ev-fresh", age_days=2)
    assert trash.cleanup_expired() == 0
    assert fresh.exists()


def test_entry_past_grace_is_purged(trash_root: Path):
    stale = _entry(trash_root, "cam1", "ev-stale", age_days=30)
    assert trash.cleanup_expired() == 1
    assert not stale.exists()


def test_boundary_just_inside_grace_survives(trash_root: Path):
    """6.9 days with a 7-day grace — must NOT be deleted."""
    edge = _entry(trash_root, "cam1", "ev-edge", age_days=6.9)
    assert trash.cleanup_expired() == 0
    assert edge.exists()


def test_mixed_entries_purge_only_the_expired(trash_root: Path):
    fresh = _entry(trash_root, "cam1", "ev-fresh", age_days=1)
    stale = _entry(trash_root, "cam2", "ev-stale", age_days=99)
    assert trash.cleanup_expired() == 1
    assert fresh.exists()
    assert not stale.exists()


def test_entry_without_meta_is_swept(trash_root: Path):
    """A dir with no meta.json is debris from an interrupted move."""
    orphan = _entry(trash_root, "cam1", "ev-orphan", age_days=None, meta=False)
    assert trash.cleanup_expired() == 1
    assert not orphan.exists()


def test_missing_trash_root_is_a_noop(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(app_state, "store", SimpleNamespace(root=str(tmp_path)), raising=False)
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), raising=False)
    assert trash.cleanup_expired() == 0
