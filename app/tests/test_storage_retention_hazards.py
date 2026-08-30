"""The nightly sweep must never be the thing that loses the archive.

Three hazards pinned here, all of them "the sweep deletes more than
anyone asked it to":

  A1a  It hard-unlinked. `storage.retention_days` moved into the
       resolution order in the same commit that started reading
       settings.json first, so the first unattended run after the
       upgrade would have permanently removed everything between the
       config.yaml window and whatever the slider had been left at —
       a slider that had never enforced anything until then.
  A1b  `cleanup_old(0)` meant "cutoff is now", i.e. the whole
       motion_detection/ tree, and `int(override or …)` turned an
       explicit `retention_days: 0` into the configured default so the
       one value that must be refused never reached the sweep.
  A2   `tl_<stem>.json` is the SINGLE record of a timelapse mp4 the
       sweep deliberately never touches. It lands in the camera root
       (`event_date_subdir("tl_…")` is None) and the sweep walked the
       camera root by mtime — so the April tile vanished 14 days after
       registration while its mp4 sat there, came back at the next
       container restart, and vanished again.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state, maintenance, storage_retention  # noqa: E402
from app.storage import EventStore  # noqa: E402

CAM = "reolink_cx810_squirreltownnutbar_181"
DATE = "2026-04-30"
_REAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096

#: Comfortably past any 14-day window.
_ANCIENT = 90 * 86400


@pytest.fixture
def store(tmp_storage_root: Path) -> EventStore:
    return EventStore(str(tmp_storage_root))


def _age(path: Path, seconds: int = _ANCIENT) -> Path:
    old = time.time() - seconds
    os.utime(path, (old, old))
    return path


def _write(path: Path, payload: bytes, *, aged: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _age(path) if aged else path


def _old_event(root: Path, event_id: str) -> Path:
    """A motion event, manifest + clip + thumb, all long expired."""
    rel_dir = f"motion_detection/{CAM}/{DATE}"
    _write(root / rel_dir / f"{event_id}.mp4", _REAL_MP4)
    _write(root / rel_dir / f"{event_id}.jpg", b"\xff\xd8\xff\xdb")
    payload = {
        "event_id": event_id,
        "camera_id": CAM,
        "time": f"{DATE}T10:00:00",
        "labels": ["motion"],
        "video_relpath": f"{rel_dir}/{event_id}.mp4",
        "snapshot_relpath": f"{rel_dir}/{event_id}.jpg",
    }
    return _write(root / rel_dir / f"{event_id}.json", json.dumps(payload).encode())


# ── A1a · the sweep is recoverable ─────────────────────────────────────────
def test_expired_files_go_to_the_trash_not_into_the_void(tmp_storage_root, store):
    manifest = _old_event(tmp_storage_root, "20260430-100000-000000")

    retired = store.cleanup_old(14)

    assert retired == 3, "manifest + clip + thumbnail"
    assert not manifest.exists()
    trash = tmp_storage_root / ".trash" / CAM / "20260430-100000-000000"
    assert trash.is_dir(), "eine Aufbewahrungsänderung muss umkehrbar sein"
    assert (trash / "20260430-100000-000000.mp4").exists()
    assert (trash / "20260430-100000-000000.jpg").exists()
    meta = json.loads((trash / "meta.json").read_text(encoding="utf-8"))
    assert meta["retired_by"] == "retention"
    assert f"motion_detection/{CAM}/{DATE}/20260430-100000-000000.mp4" in meta["files"]


def test_retired_files_restore_to_their_original_paths(tmp_storage_root, store, monkeypatch):
    manifest = _old_event(tmp_storage_root, "20260430-110000-000000")
    store.cleanup_old(14)
    assert not manifest.exists()

    monkeypatch.setattr(app_state, "store", store, raising=False)
    from app.trash import restore

    assert restore(CAM, "20260430-110000-000000") is True
    assert manifest.exists()
    assert (manifest.parent / "20260430-110000-000000.mp4").exists()


# ── A1b · a non-positive window is refused ─────────────────────────────────
def test_zero_days_is_refused_instead_of_wiping_the_tree(tmp_storage_root, store):
    manifest = _old_event(tmp_storage_root, "20260430-120000-000000")

    assert store.cleanup_old(0) == 0
    assert manifest.exists(), "retention=0 heisst nicht „alles löschen“"
    assert not (tmp_storage_root / ".trash").exists()


def test_explicit_zero_survives_resolution_instead_of_becoming_the_default(monkeypatch):
    """`int(override or …)` swallowed a 0 and returned 14, so the value
    the sweep has to refuse never arrived there."""
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"storage": {"retention_days": 30}})
    )
    monkeypatch.setattr(app_state, "base_cfg", {"storage": {"retention_days": 21}})
    assert maintenance.resolve_retention_days(0) == 0


# ── A1c · a narrowing is announced, never acted on unattended ──────────────
@pytest.fixture
def layers(monkeypatch):
    """The two config layers plus a settings object that records what
    the guard writes to runtime state."""
    runtime: dict = {}

    def _apply(settings_storage: dict, base_storage: dict, enforced=None):
        if enforced is not None:
            runtime[storage_retention.ENFORCED_KEY] = enforced
        settings = SimpleNamespace(
            data={"storage": settings_storage},
            runtime_get=lambda key, default=None: runtime.get(key, default),
            runtime_set=runtime.__setitem__,
        )
        monkeypatch.setattr(app_state, "settings", settings, raising=False)
        monkeypatch.setattr(app_state, "base_cfg", {"storage": base_storage}, raising=False)
        return runtime

    return _apply


def test_a_narrowed_window_is_announced_and_not_acted_on(layers, caplog):
    """The exact deploy shape: config.yaml says 30, the slider has been
    writing 7 into settings.json that nothing enforced. The operator
    pulls and restarts — tonight's sweep must not remove 23 days."""
    layers({"retention_days": 7}, {"retention_days": 30})
    with caplog.at_level("WARNING"):
        window = storage_retention.nightly_window(
            maintenance.resolve_retention_days(), maintenance.config_retention_days()
        )
    assert window == 30, "die unbeaufsichtigte Bereinigung löscht weiter nach 30 Tagen"
    assert "7" in caplog.text and "30" in caplog.text


def test_the_warning_repeats_until_the_operator_confirms(layers, caplog):
    runtime = layers({"retention_days": 7}, {"retention_days": 30})
    assert storage_retention.nightly_window(7, 30) == 30
    assert storage_retention.ENFORCED_KEY not in runtime, "nichts wird stillschweigend übernommen"

    # "Jetzt bereinigen" with an explicit value IS the confirmation.
    storage_retention.acknowledge_window(7)
    assert runtime[storage_retention.ENFORCED_KEY] == 7
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert storage_retention.nightly_window(7, 30) == 7
    assert caplog.text == ""


def test_widening_the_window_needs_no_confirmation(layers):
    runtime = layers({"retention_days": 60}, {"retention_days": 30})
    assert storage_retention.nightly_window(60, 30) == 60
    assert runtime[storage_retention.ENFORCED_KEY] == 60


def test_a_refused_window_is_never_recorded_as_confirmed(layers):
    runtime = layers({}, {"retention_days": 30})
    storage_retention.acknowledge_window(0)
    assert storage_retention.ENFORCED_KEY not in runtime
    assert storage_retention.nightly_window(0, 30) == 30


def test_an_independent_key_tracks_its_own_window_without_colliding(layers):
    """weather_service/_retention.py guards four independent categories
    with this same mechanism — a caller-supplied `key` must get its own
    slot in runtime.* rather than sharing (and corrupting) the main
    event store's ENFORCED_KEY."""
    runtime = layers({"retention_days": 60}, {"retention_days": 30})
    other_key = "weather_retention_enforced_sun_timelapses_days"
    # The main store's window widens and IS recorded under ENFORCED_KEY.
    assert storage_retention.nightly_window(60, 30) == 60
    assert runtime[storage_retention.ENFORCED_KEY] == 60
    # A second, independent window under its own key starts fresh — the
    # main store's recorded 60 must not leak into it.
    assert storage_retention.nightly_window(21, 21, key=other_key) == 21
    assert runtime[other_key] == 21
    assert runtime[storage_retention.ENFORCED_KEY] == 60, "the two keys must not collide"
    storage_retention.acknowledge_window(5, key=other_key)
    assert runtime[other_key] == 5
    assert (
        runtime[storage_retention.ENFORCED_KEY] == 60
    ), "acknowledging one key must not touch the other"


# ── A2 · the single record of a timelapse is immortal ──────────────────────
def test_the_sweep_never_removes_a_timelapse_record(tmp_storage_root, store):
    """`migrations.py` calls this entry "the single record of a
    timelapse" — and the mp4 it records lives under timelapse/, which the
    sweep never touches. Deleting the record while keeping the artefact
    is how the April tile disappeared and reappeared on every restart."""
    _write(tmp_storage_root / "timelapse" / CAM / f"{DATE}_day.mp4", _REAL_MP4)
    record = _write(
        tmp_storage_root / "motion_detection" / CAM / f"tl_{DATE}_day.json",
        json.dumps(
            {
                "event_id": f"tl_{DATE}_day",
                "camera_id": CAM,
                "type": "timelapse",
                "labels": ["timelapse"],
                "time": f"{DATE}T12:00:00",
                "video_relpath": f"timelapse/{CAM}/{DATE}_day.mp4",
            }
        ).encode(),
    )
    _old_event(tmp_storage_root, "20260430-130000-000000")

    retired = store.cleanup_old(14)

    assert record.exists(), "das mp4 überlebt — sein einziger Nachweis muss es auch"
    assert retired == 3, "nur das Bewegungsereignis wurde eingelagert"
    assert not (tmp_storage_root / ".trash" / CAM / f"tl_{DATE}_day").exists()


def test_the_timelapse_tile_survives_a_sweep(tmp_storage_root, store):
    """End to end: register, sweep, count. The tile used to be gone."""
    from app.media_index import camera_stats, register_timelapse_events, scan_camera
    from app.media_index import visible_media_events

    _write(tmp_storage_root / "timelapse" / CAM / f"{DATE}_day.mp4", _REAL_MP4)
    assert register_timelapse_events(tmp_storage_root, store) == 1
    for manifest in (tmp_storage_root / "motion_detection" / CAM).rglob("tl_*.json"):
        _age(manifest)

    store.cleanup_old(14)

    index = scan_camera(tmp_storage_root, CAM)
    visible = visible_media_events(store, index.size_lookup(tmp_storage_root), CAM)
    assert camera_stats(index, visible)["timelapse_count"] == 1
