"""The Mediathek must not lie about what it holds.

Four concrete shapes from the operator's archive, each of which the old
code counted wrongly:

  1. a `.tracks.json` sidecar next to every clip — counted as a second
     event by `_filter_events`, which doubled `stats_range` and the
     Telegram daily report;
  2. an event manifest whose mp4 is gone — a tile that plays nothing;
  3. a 0-byte mp4 — "eine Fake-Datei, die gar kein Video ist";
  4. a camera directory no configured camera claims — the Werkstatt
     question: "liegt da vielleicht doch irgendwas ab?".

Plus the load-bearing invariant behind the whole rewrite: the Timelapse
badge and the Timelapse grid come from ONE list and therefore cannot
disagree. The old code counted `*.mp4` files for the badge and `tl_*`
manifests for the grid, which is how "Timelapse 3" ended up above a
single tile.

RFC-5737 documentation IPs only; nothing here touches a real archive.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.media_index import (  # noqa: E402
    MIN_VIDEO_BYTES,
    build_report,
    camera_stats,
    media_state,
    register_timelapse_events,
    scan_camera,
    size_lookup_fs,
    visible_media_events,
)
from app.storage import EventStore  # noqa: E402

CAM = "reolink_cx810_squirreltownnutbar_181"
GHOST = "reolink_duo3_werkstatt_190"
DATE = "2026-04-30"

#: Big enough to clear MIN_VIDEO_BYTES, small enough to keep tmp dirs tiny.
_REAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _event(root: Path, event_id: str, **fields) -> dict:
    payload = {
        "event_id": event_id,
        "camera_id": CAM,
        "time": f"{DATE}T10:00:00",
        "labels": ["motion"],
        **fields,
    }
    day = root / "motion_detection" / CAM / DATE
    day.mkdir(parents=True, exist_ok=True)
    (day / f"{event_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _clip(root: Path, event_id: str, *, body: bytes = _REAL_MP4) -> dict:
    """A motion event with a real clip and a real thumbnail on disk."""
    rel_dir = f"motion_detection/{CAM}/{DATE}"
    _write(root / rel_dir / f"{event_id}.mp4", body)
    _write(root / rel_dir / f"{event_id}.jpg", b"\xff\xd8\xff\xdb")
    return _event(
        root,
        event_id,
        video_relpath=f"{rel_dir}/{event_id}.mp4",
        snapshot_relpath=f"{rel_dir}/{event_id}.jpg",
    )


@pytest.fixture
def store(tmp_storage_root: Path) -> EventStore:
    return EventStore(str(tmp_storage_root))


def _stats(root: Path, store: EventStore, cam_id: str = CAM) -> dict:
    index = scan_camera(root, cam_id)
    visible = visible_media_events(store, index.size_of, cam_id)
    return camera_stats(index, visible)


# ── 1 · tracks sidecars are not events ─────────────────────────────────────
def test_tracks_sidecars_do_not_inflate_any_count(tmp_storage_root, store):
    for n in range(3):
        event_id = f"20260430-1000{n}0-000000"
        _clip(tmp_storage_root, event_id)
        _write(
            tmp_storage_root / f"motion_detection/{CAM}/{DATE}/{event_id}.tracks.json",
            b'{"schema": 3, "tracks": []}',
        )

    stats = _stats(tmp_storage_root, store)
    assert stats["event_count"] == 3, "one event per clip, not one per JSON file"
    assert stats["label_counts"]["motion"] == 3

    # The same defect fed stats_range and, through aggregate_summary,
    # the Telegram daily report.
    assert store.stats_range(CAM)["total_events"] == 3
    assert store.count_events(CAM) == 3


# ── 2 · an event whose media is gone must not be counted or shown ──────────
def test_event_without_media_is_hidden_and_reported(tmp_storage_root, store):
    _clip(tmp_storage_root, "20260430-100000-000000")
    # Manifest survives, mp4 does not — the shape purge_orphans leaves
    # behind between sweeps, and the shape a deleted thumbnail creates.
    _event(
        tmp_storage_root,
        "20260430-110000-000000",
        video_relpath=f"motion_detection/{CAM}/{DATE}/20260430-110000-000000.mp4",
    )

    stats = _stats(tmp_storage_root, store)
    assert stats["event_count"] == 1
    assert stats["label_counts"]["motion"] == 1

    report = build_report(tmp_storage_root, store, [{"id": CAM, "name": "Squirrel Town"}])
    codes = {f["code"]: f for f in report["kameras"][0]["befunde"]}
    assert "ereignis_ohne_medien" in codes, "hidden, but never silently"
    assert codes["ereignis_ohne_medien"]["anzahl"] == 1


def test_media_state_prefers_the_video_over_a_surviving_thumbnail(tmp_storage_root):
    """A thumbnail next to a deleted clip must not rescue the event —
    that is exactly the tile that promises a video and plays nothing."""
    rel = f"motion_detection/{CAM}/{DATE}/20260430-120000-000000"
    _write(tmp_storage_root / f"{rel}.jpg", b"\xff\xd8\xff\xdb")
    event = {"video_relpath": f"{rel}.mp4", "snapshot_relpath": f"{rel}.jpg"}
    assert media_state(event, size_lookup_fs(tmp_storage_root)) == "missing_video"


# ── 3 · zero-byte / truncated videos are not videos ────────────────────────
def test_zero_byte_video_is_never_counted(tmp_storage_root, store):
    _clip(tmp_storage_root, "20260430-100000-000000")
    _clip(tmp_storage_root, "20260430-130000-000000", body=b"")

    stats = _stats(tmp_storage_root, store)
    assert stats["event_count"] == 1, "0 Byte ist kein Video"

    report = build_report(tmp_storage_root, store, [{"id": CAM, "name": "Squirrel Town"}])
    codes = {f["code"] for f in report["kameras"][0]["befunde"]}
    assert "defekte_videos" in codes


def test_truncated_video_is_refused_by_the_registrar(tmp_storage_root, store):
    tl = tmp_storage_root / "timelapse" / CAM
    _write(tl / "2026-04-30_day.mp4", _REAL_MP4)
    _write(tl / "2026-08-25_rolling10min.mp4", b"\x00" * (MIN_VIDEO_BYTES - 1))

    assert register_timelapse_events(tmp_storage_root, store) == 1
    assert _stats(tmp_storage_root, store)["timelapse_count"] == 1


# ── 4 · media under an id no camera claims ─────────────────────────────────
def test_unclaimed_camera_dir_is_reported_not_deleted(tmp_storage_root, store):
    ghost_mp4 = _write(tmp_storage_root / "timelapse" / GHOST / "2026-04-30_day.mp4", _REAL_MP4)
    _write(tmp_storage_root / "weather" / GHOST / "sunrise.mp4", _REAL_MP4)

    report = build_report(tmp_storage_root, store, [{"id": CAM, "name": "Squirrel Town"}])
    fremde = {r["camera_id"]: r for r in report["fremde_verzeichnisse"]}
    assert GHOST in fremde
    assert set(fremde[GHOST]["verzeichnisse"]) == {"timelapse", "weather"}
    assert ghost_mp4.exists(), "der Bericht löscht nichts"


def test_weather_and_adhoc_bytes_surface_even_though_no_card_shows_them(tmp_storage_root, store):
    """0 MB on the camera card is a statement about two trees, not about
    the disk. The report is where the other three become visible."""
    # Past 0.1 MB so the rounded figure is visibly non-zero.
    bulky = _REAL_MP4 + b"\x00" * 300_000
    _write(tmp_storage_root / "weather" / CAM / "clip.mp4", bulky)
    _write(tmp_storage_root / "adhoc_clips" / CAM / "adhoc-1.mp4", bulky)

    assert _stats(tmp_storage_root, store)["size_mb"] == 0.0
    report = build_report(tmp_storage_root, store, [{"id": CAM, "name": "Squirrel Town"}])
    groessen = report["kameras"][0]["groessen"]
    assert groessen["wetter_mb"] > 0
    assert groessen["adhoc_mb"] > 0
    ungefegt = {r["pfad"]: r for r in report["ungefegte_verzeichnisse"]}
    assert ungefegt["adhoc_clips"]["gefegt_von"] is None


# ── the invariant: badge and grid come from one list ───────────────────────
def test_timelapse_badge_equals_grid_after_registration(tmp_storage_root, store):
    """Squirrel Town: three mp4s on disk, one of them with a metadata
    sidecar. The old badge said 3, the old grid said 1."""
    tl = tmp_storage_root / "timelapse" / CAM
    for stem in ("2026-04-30_day", "2026-08-25_rolling10min", "2026-08-26_rolling10min"):
        _write(tl / f"{stem}.mp4", _REAL_MP4)
    (tl / "2026-04-30_day.json").write_text(
        json.dumps({"time": f"{DATE}T12:00:00", "profile": "day"}), encoding="utf-8"
    )

    register_timelapse_events(tmp_storage_root, store)

    index = scan_camera(tmp_storage_root, CAM)
    visible = visible_media_events(store, index.size_of, CAM)
    badge = camera_stats(index, visible)["timelapse_count"]
    grid = sum(1 for e in visible if e.get("type") == "timelapse")
    assert badge == grid == 3

    report = build_report(tmp_storage_root, store, [{"id": CAM, "name": "Squirrel Town"}])
    assert report["kameras"][0]["zaehler"]["abweichung"] == 0


def test_timelapse_events_never_show_up_as_motion(tmp_storage_root, store):
    """ "Bewegung 1" on a camera with zero motion events: the badge
    derived motion as event_count minus objects, and event_count still
    contained the timelapse manifest."""
    _write(tmp_storage_root / "timelapse" / CAM / "2026-04-30_day.mp4", _REAL_MP4)
    register_timelapse_events(tmp_storage_root, store)

    stats = _stats(tmp_storage_root, store)
    assert stats["timelapse_count"] == 1
    assert stats["event_count"] == 0
    assert stats["label_counts"].get("motion", 0) == 0


def test_registration_is_idempotent(tmp_storage_root, store):
    _write(tmp_storage_root / "timelapse" / CAM / "2026-04-30_day.mp4", _REAL_MP4)
    assert register_timelapse_events(tmp_storage_root, store) == 1
    assert register_timelapse_events(tmp_storage_root, store) == 0
    assert _stats(tmp_storage_root, store)["timelapse_count"] == 1


def test_rescan_does_not_mint_ghost_events_from_raw_and_best_files(tmp_storage_root, store):
    """`<id>.raw.mp4` and `<id>.best.jpg` belong to an event that already
    exists. Registering them added a phantom motion event per incident on
    every click, and purge_orphans could not remove it."""
    event_id = "20260430-100000-000000"
    _clip(tmp_storage_root, event_id)
    rel_dir = tmp_storage_root / "motion_detection" / CAM / DATE
    _write(rel_dir / f"{event_id}.raw.mp4", _REAL_MP4)
    _write(rel_dir / f"{event_id}.best.jpg", b"\xff\xd8\xff\xdb")

    assert store.scan_media_files([CAM]) == 0
    assert _stats(tmp_storage_root, store)["event_count"] == 1
