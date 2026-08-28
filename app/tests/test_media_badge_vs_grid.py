"""The badge and the grid, from the two real routes, on one fixture.

The invariant test that shipped with the "one source of truth" commit
derived BOTH numbers from the same local ``visible`` list, so it could
not fail whatever the routes did. Nothing exercised
``GET /api/media/storage-stats`` against ``GET /api/camera/<id>/media``
— which is the only place the remaining disagreements were visible:

  B1  A `["fox"]` event matched no object label and was not "motion"
      either, so it fell out of `label_counts` entirely: the grid
      rendered a tile, every chip above it read 0.
  C1  Archived cards labelled `event_count` "Bewegung", but
      `event_count` counts every visible non-timelapse event — an
      archived camera with 7 person events read "Bewegung 7".
  C2  The badge route answered sizes from the walked index, the grid
      route stat()ed anything. They agreed only as long as no manifest
      pointed outside motion_detection/ and timelapse/.
  D1  The "read-only" integrity report created
      motion_detection/<id>/ for every id it inspected, ghost ids
      included, and its second run reported the first run's handiwork.
  E   Rolling previews ("letzte 10 Minuten") were registered as
      permanent archive entries — one more tile per button press, in a
      tree nothing sweeps.
  F   `index.media` was keyed by stem, so `<id>.jpg` and `<id>.mp4`
      collided and a two-file event counted as one.

RFC-5737 documentation IPs only; nothing here touches a real archive.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import app_state
from app.media_index import build_report, is_rolling_preview, register_timelapse_events
from app.routes import media as media_routes
from app.storage import EventStore

CAM = "reolink_cx810_squirreltownnutbar_181"
GHOST = "reolink_duo3_werkstatt_190"
DATE = "2026-04-30"
_REAL_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096
_JPG = b"\xff\xd8\xff\xdb" + b"\x00" * 512


@pytest.fixture
def store(tmp_storage_root: Path) -> EventStore:
    return EventStore(str(tmp_storage_root))


@pytest.fixture
def client(monkeypatch, store, tmp_storage_root: Path):
    """Flask test client over the media blueprint, one configured cam."""
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
        lambda *a, **k: {
            "cameras": [{"id": CAM, "name": "Squirrel Town"}],
            "storage": {"media_limit_default": 500},
            "processing": {"clip_max_duration_s": 120},
        },
        raising=False,
    )
    return app.test_client()


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _clip(root: Path, event_id: str, labels: list, *, cam: str = CAM, tree: str = None) -> dict:
    """A motion event whose clip and thumbnail really are on disk.

    ``tree`` puts the media somewhere other than motion_detection/ while
    the manifest stays where the store looks for it — the shape that
    separated the badge lookup from the grid lookup.
    """
    media_dir = f"{tree or 'motion_detection'}/{cam}" + ("" if tree else f"/{DATE}")
    _write(root / media_dir / f"{event_id}.mp4", _REAL_MP4)
    _write(root / media_dir / f"{event_id}.jpg", _JPG)
    payload = {
        "event_id": event_id,
        "camera_id": cam,
        "camera_name": cam,
        "time": f"{DATE}T10:00:00",
        "labels": labels,
        "video_relpath": f"{media_dir}/{event_id}.mp4",
        "snapshot_relpath": f"{media_dir}/{event_id}.jpg",
    }
    day = root / "motion_detection" / cam / DATE
    day.mkdir(parents=True, exist_ok=True)
    (day / f"{event_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _badge(client, cam_id: str = CAM) -> dict:
    body = client.get('/api/media/storage-stats').get_json()
    for row in body["cameras"] + body["archived"]:
        if row["camera_id"] == cam_id:
            return row
    raise AssertionError(f"{cam_id} in keiner Sektion von storage-stats")


def _grid(client, cam_id: str = CAM) -> list:
    return client.get(f'/api/camera/{cam_id}/media').get_json()["items"]


# ── the invariant, across the two routes ───────────────────────────────────
def test_badge_chips_sum_to_the_grid(client, tmp_storage_root):
    """Every tile is counted under exactly one chip. Sum the chips, get
    the grid — on a fixture that mixes objects, wildlife and bare
    motion."""
    _clip(tmp_storage_root, "20260430-100000-000000", ["motion", "person"])
    _clip(tmp_storage_root, "20260430-110000-000000", ["motion"])
    _clip(tmp_storage_root, "20260430-120000-000000", ["fox"])
    _clip(tmp_storage_root, "20260430-130000-000000", ["hedgehog"])
    _clip(tmp_storage_root, "20260430-140000-000000", ["marten"])

    stats = _badge(client)
    items = _grid(client)

    assert len(items) == 5
    assert stats["event_count"] == 5
    assert sum(stats["label_counts"].values()) == len(items)


def test_a_wildlife_sighting_gets_a_badge_not_only_a_tile(client, tmp_storage_root):
    """B1 verbatim: FOX event_count 1, label_counts {}, chips render 0,
    grid renders 1 tile."""
    _clip(tmp_storage_root, "20260430-120000-000000", ["fox"])

    stats = _badge(client)
    assert len(_grid(client)) == 1
    assert stats["event_count"] == 1
    assert stats["label_counts"] == {"fox": 1}


def test_an_unknown_label_falls_back_to_motion_instead_of_vanishing(client, tmp_storage_root):
    """A class from a model this build has never heard of still lands in
    a bucket — a chip row that does not sum to the grid is the defect."""
    _clip(tmp_storage_root, "20260430-150000-000000", ["capybara"])

    stats = _badge(client)
    assert len(_grid(client)) == 1
    assert stats["label_counts"] == {"motion": 1}


def test_both_routes_see_media_that_lives_outside_the_counted_trees(client, tmp_storage_root):
    """C2: the badge answered from the walked trees, the grid stat()ed
    anything. One manifest pointing at weather/ split them."""
    _clip(tmp_storage_root, "20260430-160000-000000", ["motion"], tree="weather")

    assert len(_grid(client)) == 1
    assert _badge(client)["event_count"] == 1


def test_archived_cameras_are_counted_the_same_way_as_active_ones(client, tmp_storage_root):
    """C1: the archived card's only count was `event_count` under a
    "Bewegung" icon. It carries label_counts like every other card, so
    seven person events cannot read as seven motion events."""
    for n in range(7):
        _clip(tmp_storage_root, f"20260430-2{n}0000-000000", ["person"], cam=GHOST)

    stats = _badge(client, GHOST)
    assert stats["event_count"] == 7
    assert stats["label_counts"] == {"person": 7}
    assert stats["label_counts"].get("motion", 0) == 0


# ── F · two files, two files ───────────────────────────────────────────────
def test_a_clip_and_its_thumbnail_count_as_two_files(client, tmp_storage_root):
    _clip(tmp_storage_root, "20260430-100000-000000", ["motion"])
    assert _badge(client)["jpg_count"] == 2, "<id>.jpg und <id>.mp4 kollidierten im Index"


# ── D1 · the report creates nothing ────────────────────────────────────────
def test_the_integrity_report_does_not_create_the_directories_it_reports(tmp_storage_root, store):
    _write(tmp_storage_root / "weather" / GHOST / "sunrise.mp4", _REAL_MP4)
    cameras = [{"id": CAM, "name": "Squirrel Town"}]

    first = build_report(tmp_storage_root, store, cameras)
    second = build_report(tmp_storage_root, store, cameras)

    assert not (tmp_storage_root / "motion_detection" / GHOST).exists()
    assert not (tmp_storage_root / "motion_detection" / CAM).exists()
    trees = {row["camera_id"]: row["verzeichnisse"] for row in first["fremde_verzeichnisse"]}
    assert trees == {GHOST: ["weather"]}
    assert second["fremde_verzeichnisse"] == first["fremde_verzeichnisse"]


# ── D3 · the container probe sees every tree it charges for ────────────────
def test_a_broken_clip_outside_the_counted_trees_is_still_reported(tmp_storage_root, store):
    _write(tmp_storage_root / "weather" / CAM / "sunrise.mp4", b"not-an-mp4")
    _write(tmp_storage_root / "adhoc_clips" / CAM / "adhoc.mp4", b"")

    report = build_report(tmp_storage_root, store, [{"id": CAM, "name": "Squirrel Town"}])
    defekt = next(f for f in report["kameras"][0]["befunde"] if f["code"] == "defekte_videos")
    pfade = {e["pfad"] for e in defekt["eintraege"]}
    assert f"weather/{CAM}/sunrise.mp4" in pfade
    assert f"adhoc_clips/{CAM}/adhoc.mp4" in pfade


# ── E · a preview is not an archive entry ──────────────────────────────────
def test_rolling_previews_are_never_registered_as_archive_tiles(client, tmp_storage_root, store):
    tl = tmp_storage_root / "timelapse" / CAM
    _write(tl / f"{DATE}_day.mp4", _REAL_MP4)
    _write(tl / f"{DATE}_rolling10min.mp4", _REAL_MP4)
    _write(tl / f"{DATE}_rolling60min.mp4", _REAL_MP4)

    assert register_timelapse_events(tmp_storage_root, store) == 1
    # Idempotent, and pressing the preview button again adds nothing.
    assert register_timelapse_events(tmp_storage_root, store) == 0

    assert _badge(client)["timelapse_count"] == 1
    assert sum(1 for i in _grid(client) if i.get("type") == "timelapse") == 1

    report = build_report(tmp_storage_root, store, [{"id": CAM, "name": "Squirrel Town"}])
    kam = report["kameras"][0]
    assert kam["zaehler"]["abweichung"] == 0, "Vorschauen sind keine fehlenden Einträge"
    codes = {f["code"]: f for f in kam["befunde"]}
    assert codes["rolling_vorschauen"]["anzahl"] == 2
    assert "timelapse_ohne_eintrag" not in codes


def test_rolling_stems_are_recognised_by_shape_not_by_a_list():
    assert is_rolling_preview("2026-08-25_rolling10min")
    assert is_rolling_preview("2026-08-25_rolling60min")
    assert not is_rolling_preview("2026-08-25_day")
    assert not is_rolling_preview("2026-08-25_rolling")
