"""Kamera-Timelapses: configurable, off by default, and never half-deleted.

The exemption in `storage_retention._collect_expired` is not an
oversight — `tl_<stem>.json` is the SINGLE record of an mp4 that lives
under `timelapse/`, outside the swept tree. Deleting the record alone
made the April tile vanish, come back at the next boot (because
`media_index._timelapse` re-registers it from the mp4) and vanish again.
That is the whole reason `tl_*` ids were made immortal.

So the decision taken here is deliberately conservative:

  * the exemption in `cleanup_old` STAYS — nothing in this file changes
    the motion sweep;
  * the new sweep retires the mp4, the thumbnail, the sidecar AND the
    manifest as ONE trash entry, because that is the only deletion the
    archive can represent without producing the ghost tile again;
  * it ships OFF (`0` = nie löschen). A category that has never been
    deleted on any install does not become mortal because someone
    upgraded — it becomes CONFIGURABLE. Turning it on is an act the
    operator performs on a screen showing the number.
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

from app import app_state, maintenance, trash  # noqa: E402
from app.storage import EventStore  # noqa: E402
from app.timelapse_retention import sweep_camera_timelapses  # noqa: E402

CAM = "reolink_cx810_squirreltownnutbar_181"
_ANCIENT = 90 * 86400
_REAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096


@pytest.fixture
def store(tmp_storage_root: Path) -> EventStore:
    return EventStore(str(tmp_storage_root))


@pytest.fixture(autouse=True)
def _wire_app_state(tmp_storage_root, store, monkeypatch):
    """`trash` reaches through app_state for the grace period and the
    trash root; `storage_retention` reads keep_judged_events from there."""
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), raising=False)
    monkeypatch.setattr(app_state, "base_cfg", {}, raising=False)


def _age(path: Path, seconds: int = _ANCIENT) -> Path:
    old = time.time() - seconds
    os.utime(path, (old, old))
    return path


def _timelapse(root: Path, stem: str, *, aged: bool = True, judged: bool = False) -> dict:
    """One camera timelapse exactly as the pipeline leaves it: mp4 +
    thumb + sidecar under timelapse/<cam>/, manifest in the event
    store's camera ROOT."""
    cam_dir = root / "timelapse" / CAM
    cam_dir.mkdir(parents=True, exist_ok=True)
    mp4 = cam_dir / f"{stem}.mp4"
    mp4.write_bytes(_REAL_MP4)
    thumb = cam_dir / f"{stem}.jpg"
    thumb.write_bytes(b"\xff\xd8\xff\xdb")
    sidecar = cam_dir / f"{stem}.json"
    sidecar.write_text(json.dumps({"profile": "daily"}), encoding="utf-8")
    events_dir = root / "motion_detection" / CAM
    events_dir.mkdir(parents=True, exist_ok=True)
    manifest = events_dir / f"tl_{stem}.json"
    payload = {"event_id": f"tl_{stem}", "camera_id": CAM, "type": "timelapse"}
    if judged:
        payload["confirmed"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    if aged:
        for p in (mp4, thumb, sidecar, manifest):
            _age(p)
    return {"mp4": mp4, "thumb": thumb, "sidecar": sidecar, "manifest": manifest}


# ── the decision: off unless asked ─────────────────────────────────────


@pytest.mark.parametrize("window", [0, -1])
def test_nie_loeschen_touches_nothing(tmp_storage_root, store, window):
    """0 is the shipped value. An install that upgrades into this code
    must find every timelapse it had, in the place it had it."""
    files = _timelapse(tmp_storage_root, "2026-04-30")
    assert sweep_camera_timelapses(store, window) == 0
    for path in files.values():
        assert path.exists(), f"{path.name} deleted by a window that means 'nie löschen'"


def test_the_shipped_default_is_nie_loeschen():
    from app.settings._consts import CAMERA_TIMELAPSE_RETENTION_DAYS_DEFAULT

    assert CAMERA_TIMELAPSE_RETENTION_DAYS_DEFAULT == 0


def test_the_daily_job_skips_the_sweep_while_the_row_is_off(tmp_storage_root, store, monkeypatch):
    """The guard is applied by the caller, and it must not be able to
    resurrect a window for a row the operator switched back off: the
    previously-enforced value would otherwise come back as the window."""
    files = _timelapse(tmp_storage_root, "2026-04-30")
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), raising=False)
    called: list = []
    monkeypatch.setattr(
        "app.timelapse_retention.sweep_camera_timelapses",
        lambda *a, **k: called.append(a) or 0,
        raising=False,
    )
    maintenance._sweep_camera_timelapses(maintenance.logging.getLogger(__name__))
    assert called == []
    assert files["mp4"].exists()


# ── when it IS switched on ─────────────────────────────────────────────


def test_an_expired_timelapse_is_retired_whole(tmp_storage_root, store):
    """Video, thumbnail, sidecar and manifest, together. Deleting the
    manifest alone is what produced the reappearing ghost tile."""
    files = _timelapse(tmp_storage_root, "2026-04-30")
    assert sweep_camera_timelapses(store, 14, keep_judged=False) == 4
    for path in files.values():
        assert not path.exists(), f"{path.name} survived while its companions were retired"


def test_the_files_go_to_the_trash_and_restore_to_their_original_paths(tmp_storage_root, store):
    files = _timelapse(tmp_storage_root, "2026-04-30")
    sweep_camera_timelapses(store, 14, keep_judged=False)
    entries = trash.list_trashed()
    assert [e["event_id"] for e in entries] == ["tl_2026-04-30"]
    trash.restore(CAM, "tl_2026-04-30")
    for path in files.values():
        assert path.exists(), f"{path.name} did not come back from the Papierkorb"


def test_a_fresh_timelapse_is_left_alone(tmp_storage_root, store):
    files = _timelapse(tmp_storage_root, "2026-08-30", aged=False)
    assert sweep_camera_timelapses(store, 14, keep_judged=False) == 0
    assert files["mp4"].exists()


def test_a_judged_timelapse_is_immortal(tmp_storage_root, store):
    """Same exemption, same switch and same id set as the motion sweep —
    a human verdict outlives the retention window everywhere."""
    files = _timelapse(tmp_storage_root, "2026-04-30", judged=True)
    assert sweep_camera_timelapses(store, 14) == 0
    assert files["mp4"].exists()
    assert files["manifest"].exists()


def test_a_video_without_a_manifest_still_gets_cleaned_up(tmp_storage_root, store):
    """An unregistered mp4 (built via an HTTP route before
    media_index/_timelapse existed) is still a file taking space."""
    cam_dir = tmp_storage_root / "timelapse" / CAM
    cam_dir.mkdir(parents=True, exist_ok=True)
    mp4 = cam_dir / "2026-04-30_rolling10min.mp4"
    mp4.write_bytes(_REAL_MP4)
    _age(mp4)
    assert sweep_camera_timelapses(store, 14, keep_judged=False) == 1
    assert not mp4.exists()


def test_a_stray_sidecar_without_a_video_is_not_swept(tmp_storage_root, store):
    """The mp4 is the anchor. A lone sidecar is an integrity-report
    finding, not a recording with an age."""
    cam_dir = tmp_storage_root / "timelapse" / CAM
    cam_dir.mkdir(parents=True, exist_ok=True)
    orphan = cam_dir / "2026-04-30.json"
    orphan.write_text("{}", encoding="utf-8")
    _age(orphan)
    assert sweep_camera_timelapses(store, 14, keep_judged=False) == 0
    assert orphan.exists()


def test_a_missing_timelapse_tree_is_a_noop(tmp_storage_root, store):
    (tmp_storage_root / "timelapse").rmdir()
    assert sweep_camera_timelapses(store, 14, keep_judged=False) == 0


# ── the motion sweep is unchanged ──────────────────────────────────────


def test_the_motion_sweep_still_never_touches_a_timelapse_record(tmp_storage_root, store):
    """The exemption that this whole design is built around stays in
    place: `cleanup_old` must remain incapable of orphaning an mp4."""
    files = _timelapse(tmp_storage_root, "2026-04-30")
    store.cleanup_old(14, keep_judged=False)
    assert files["manifest"].exists()
    assert files["mp4"].exists()
