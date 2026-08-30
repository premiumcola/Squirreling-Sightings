"""A clip whose producer died must not spin forever.

The defect: ``set_clip_stage`` is only ever called *forwards*, by the
thread doing the work. Kill that thread — container restart, ffmpeg
hang, power cut — and the manifest keeps the stage it had. Nothing
else in the codebase ever wrote a terminal state, so the card read
"hängt · 5 h 51 min" for the rest of the archive's life and the only
exit was deleting the event by hand.

Two halves close it, sharing one vocabulary
(:func:`app.clip_recovery.needs_adoption`, ``interrupted_at``):

* the boot sweep, which knows every in-flight clip from before the
  process started is orphaned, and
* the SIGTERM stamp, which says so on the way out.

The pin that matters most is the recovery: ffmpeg often finishes
writing the mp4 before the process dies, and that finished clip used
to be presented as "hängt" forever. It is the one case where the fix
gives the operator something back rather than just stopping a lie.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import app_state, clip_recovery
from app.camera_runtime._recording._stages import STAGE_ENCODING, STAGE_READY, STAGE_RECORDING
from app.clip_recovery import (
    INTERRUPTED_AT,
    INTERRUPTED_REASON_DE,
    needs_adoption,
    stamp_interrupted_clips,
    sweep_orphaned_clips,
)
from app.routes import media as media_routes
from app.storage import EventStore

CAM = "reolink_cx810_gartendachterrasse_181"
DATE = "2026-08-27"

#: Boot. Everything the fixtures stamp is deliberately older than this,
#: which is exactly what makes it orphaned.
BOOT = datetime(2026, 8, 27, 12, 0, 0)

#: An ISO base-media header (size field + ``ftyp``) padded past
#: MIN_VIDEO_BYTES — what ``media_index.probe_container`` accepts, which
#: is the archive's existing "is this an mp4 at all" test.
REAL_MP4 = b"\x00\x00\x10\x00ftypisom" + b"\x00" * 4096


def _day(root: Path) -> Path:
    day = root / "motion_detection" / CAM / DATE
    day.mkdir(parents=True, exist_ok=True)
    return day


def _stub(root: Path, event_id: str, *, stage: str, since: datetime, **extra) -> Path:
    """An in-flight manifest exactly as ``_write_recording_event_stub``
    leaves it: real metadata, null media fields, a stage and a clock."""
    payload = {
        "event_id": event_id,
        "camera_id": CAM,
        "camera_name": "Garten",
        "time": since.isoformat(timespec="seconds"),
        "labels": ["motion", "bird"],
        "top_label": "bird",
        "detections": [{"label": "bird", "confidence": 0.81}],
        "snapshot_relpath": None,
        "snapshot_url": None,
        "video_relpath": None,
        "video_url": None,
        "duration_s": 0.0,
        "file_size_bytes": 0,
        "stage": stage,
        "stage_since": since.isoformat(timespec="seconds"),
        "status": "recording" if stage == STAGE_RECORDING else "processing",
    }
    payload.update(extra)
    path = _day(root) / f"{event_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sweep(root: Path, **kw):
    kw.setdefault("started_at", BOOT)
    kw.setdefault("now", BOOT)
    return sweep_orphaned_clips(root, **kw)


# ── A · the recovery that gives something back ─────────────────────────────
def test_an_orphan_whose_encode_finished_is_recovered_to_ready(tmp_storage_root):
    """ffmpeg wrote the mp4, then the container went down before the
    manifest was updated. That clip is playable and was being shown as
    "hängt" forever."""
    path = _stub(
        tmp_storage_root,
        "20260827-060000-000000",
        stage=STAGE_ENCODING,
        since=BOOT - timedelta(hours=5, minutes=51),
    )
    (_day(tmp_storage_root) / "20260827-060000-000000.mp4").write_bytes(REAL_MP4)

    assert _sweep(tmp_storage_root) == {"recovered": 1, "failed": 0}
    ev = _read(path)
    assert ev["stage"] == STAGE_READY
    assert ev["status"] == "ready"
    assert ev["video_relpath"] == f"motion_detection/{CAM}/{DATE}/20260827-060000-000000.mp4"
    assert ev["video_url"].endswith(ev["video_relpath"])
    assert ev["file_size_bytes"] == len(REAL_MP4)
    assert "encode_error" not in ev
    assert not needs_adoption(ev)


def test_the_stream_copy_is_accepted_when_the_reencode_never_finished(tmp_storage_root):
    """`_reencode_motion_clip` already falls back to `<id>.raw.mp4` on its
    own error path. A clip killed before that fallback ran must reach the
    same place, not be thrown away."""
    path = _stub(
        tmp_storage_root,
        "20260827-061000-000000",
        stage=STAGE_ENCODING,
        since=BOOT - timedelta(hours=2),
    )
    (_day(tmp_storage_root) / "20260827-061000-000000.raw.mp4").write_bytes(REAL_MP4)

    assert _sweep(tmp_storage_root)["recovered"] == 1
    assert _read(path)["video_relpath"].endswith("20260827-061000-000000.raw.mp4")


def test_a_truncated_encode_is_not_sold_as_a_playable_clip(tmp_storage_root):
    """Below MIN_VIDEO_BYTES is crash residue, not a video — the same
    rule `media_state` and the media rescan already apply."""
    path = _stub(
        tmp_storage_root,
        "20260827-062000-000000",
        stage=STAGE_ENCODING,
        since=BOOT - timedelta(hours=2),
    )
    (_day(tmp_storage_root) / "20260827-062000-000000.mp4").write_bytes(b"\x00" * 200)

    assert _sweep(tmp_storage_root) == {"recovered": 0, "failed": 1}
    assert _read(path)["status"] == "error"


# ── B · the honest failure ─────────────────────────────────────────────────
def test_an_orphan_with_nothing_on_disk_is_marked_failed(tmp_storage_root):
    path = _stub(
        tmp_storage_root,
        "20260827-070000-000000",
        stage=STAGE_RECORDING,
        since=BOOT - timedelta(hours=1, minutes=20),
    )

    assert _sweep(tmp_storage_root) == {"recovered": 0, "failed": 1}
    ev = _read(path)
    assert ev["stage"] == "failed"
    assert ev["status"] == "error", "the coarse field the older consumers read must follow"
    assert ev["encode_error"] == INTERRUPTED_REASON_DE
    assert "Neustart" in ev["encode_error"], "the reason must name the real cause, in German"
    assert not needs_adoption(ev)


def test_nothing_is_deleted_and_the_evidence_survives(tmp_storage_root):
    """The operator said "haus es einfach weg". A stub still carries
    detections and labels, so the sweep changes the state and leaves the
    record — auto-delete stays a decision they get to make."""
    path = _stub(
        tmp_storage_root,
        "20260827-071000-000000",
        stage=STAGE_RECORDING,
        since=BOOT - timedelta(hours=3),
    )
    _sweep(tmp_storage_root)
    ev = _read(path)
    assert path.exists()
    assert ev["detections"] == [{"label": "bird", "confidence": 0.81}]
    assert ev["labels"] == ["motion", "bird"]


# ── C · never race the live pipeline ───────────────────────────────────────
def test_a_clip_recording_right_now_is_left_alone(tmp_storage_root):
    """The sweep runs after `rebuild_runtimes()`, so a camera that fired
    motion two seconds ago already has a stub on disk. Adopting it would
    break a recording that is working."""
    path = _stub(
        tmp_storage_root,
        "20260827-120005-000000",
        stage=STAGE_RECORDING,
        since=BOOT + timedelta(seconds=5),
    )

    assert _sweep(tmp_storage_root) == {"recovered": 0, "failed": 0}
    assert _read(path)["stage"] == STAGE_RECORDING


def test_a_finished_clip_is_never_touched(tmp_storage_root):
    day = _day(tmp_storage_root)
    (day / "20260827-100000-000000.mp4").write_bytes(REAL_MP4)
    before = {
        "event_id": "20260827-100000-000000",
        "camera_id": CAM,
        "time": f"{DATE}T10:00:00",
        "status": "ready",
        "video_relpath": f"motion_detection/{CAM}/{DATE}/20260827-100000-000000.mp4",
    }
    path = day / "20260827-100000-000000.json"
    path.write_text(json.dumps(before), encoding="utf-8")

    assert _sweep(tmp_storage_root) == {"recovered": 0, "failed": 0}
    assert _read(path) == before


# ── D · idempotence + robustness ───────────────────────────────────────────
def test_a_second_sweep_finds_nothing_left_to_do(tmp_storage_root):
    """Boot happens a lot. Clearing `interrupted_at` is what retires an
    event from the candidate set."""
    _stub(
        tmp_storage_root,
        "20260827-080000-000000",
        stage=STAGE_ENCODING,
        since=BOOT - timedelta(hours=4),
    )
    path = _stub(
        tmp_storage_root,
        "20260827-081000-000000",
        stage=STAGE_ENCODING,
        since=BOOT - timedelta(hours=4),
    )
    (_day(tmp_storage_root) / "20260827-081000-000000.mp4").write_bytes(REAL_MP4)

    first = _sweep(tmp_storage_root)
    after_first = _read(path)
    assert first == {"recovered": 1, "failed": 1}
    assert _sweep(tmp_storage_root) == {"recovered": 0, "failed": 0}
    assert _read(path) == after_first


def test_an_unreadable_manifest_does_not_abort_the_sweep(tmp_storage_root):
    """The crash we are cleaning up after is exactly what leaves a
    half-written JSON behind. One bad file may not cost every other
    clip its recovery."""
    (_day(tmp_storage_root) / "20260827-085900-000000.json").write_text(
        '{"event_id": "20260827-085900-0', encoding="utf-8"
    )
    path = _stub(
        tmp_storage_root,
        "20260827-090000-000000",
        stage=STAGE_ENCODING,
        since=BOOT - timedelta(hours=4),
    )

    assert _sweep(tmp_storage_root) == {"recovered": 0, "failed": 1}
    assert _read(path)["status"] == "error"


def test_a_missing_storage_tree_is_not_an_error(tmp_path):
    assert sweep_orphaned_clips(tmp_path / "nope", started_at=BOOT) == {
        "recovered": 0,
        "failed": 0,
    }


# ── E · the shutdown stamp ─────────────────────────────────────────────────
def test_sigterm_stamps_every_in_flight_clip_interrupted(tmp_storage_root):
    path = _stub(tmp_storage_root, "20260827-115900-000000", stage=STAGE_ENCODING, since=BOOT)

    assert stamp_interrupted_clips(tmp_storage_root, now=BOOT) == 1
    ev = _read(path)
    assert ev["stage"] == "failed"
    assert ev["status"] == "error"
    assert ev[INTERRUPTED_AT] == BOOT.isoformat(timespec="seconds")
    assert ev["encode_error"] == INTERRUPTED_REASON_DE


def test_the_stamp_is_idempotent_across_repeated_signals(tmp_storage_root):
    """SIGTERM then SIGKILL then a second `docker stop` — the stamp may
    not keep rewriting manifests it already owns."""
    _stub(tmp_storage_root, "20260827-115901-000000", stage=STAGE_ENCODING, since=BOOT)
    assert stamp_interrupted_clips(tmp_storage_root, now=BOOT) == 1
    assert stamp_interrupted_clips(tmp_storage_root, now=BOOT) == 0


def test_the_stamp_leaves_finished_clips_alone(tmp_storage_root):
    day = _day(tmp_storage_root)
    path = day / "20260827-100000-000000.json"
    path.write_text(json.dumps({"event_id": "x", "status": "ready"}), encoding="utf-8")
    assert stamp_interrupted_clips(tmp_storage_root, now=BOOT) == 0


def test_the_stamped_clip_is_still_offered_to_the_next_boot(tmp_storage_root):
    """The stamp is terminal for the UI but not for the sweep: the mp4
    may have landed in the seconds between the signal and SIGKILL, and
    `interrupted_at` is what keeps that clip a candidate."""
    path = _stub(tmp_storage_root, "20260827-115902-000000", stage=STAGE_ENCODING, since=BOOT)
    stamp_interrupted_clips(tmp_storage_root, now=BOOT)
    (_day(tmp_storage_root) / "20260827-115902-000000.mp4").write_bytes(REAL_MP4)

    # Next boot: the stamp predates it, so the age guard would call this
    # clip "ours" — `interrupted_at` overrides that.
    assert sweep_orphaned_clips(
        tmp_storage_root, started_at=BOOT - timedelta(minutes=1), now=BOOT
    ) == {"recovered": 1, "failed": 0}
    assert _read(path)["stage"] == STAGE_READY
    assert INTERRUPTED_AT not in _read(path)


def test_the_stamp_walk_stays_inside_the_docker_stop_window(tmp_storage_root):
    """Bounded to the recent day folders on purpose — SIGKILL is ten
    seconds behind SIGTERM, so this path may not rglob a whole archive."""
    old = tmp_storage_root / "motion_detection" / CAM / "2019-01-01"
    old.mkdir(parents=True, exist_ok=True)
    stale = old / "20190101-120000-000000.json"
    stale.write_text(
        json.dumps({"event_id": "20190101-120000-000000", "stage": STAGE_ENCODING}),
        encoding="utf-8",
    )

    assert stamp_interrupted_clips(tmp_storage_root, now=BOOT) == 0
    assert "stage" in _read(stale) and INTERRUPTED_AT not in _read(stale)
    # The unbounded boot sweep is the one that gets to it.
    assert sweep_orphaned_clips(tmp_storage_root, started_at=BOOT, now=BOOT)["failed"] == 1


# ── F · what the library shows afterwards ──────────────────────────────────
@pytest.fixture
def client(monkeypatch, tmp_storage_root: Path):
    """The real media route over the tmp tree — the surface that renders
    "hängt"."""
    app = Flask(__name__)
    app.register_blueprint(media_routes.bp)
    monkeypatch.setattr(app_state, "store", EventStore(str(tmp_storage_root)), raising=False)
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


def _items(client):
    return client.get(f"/api/camera/{CAM}/media?limit=9999").get_json()["items"]


def test_the_haengt_card_becomes_a_playable_clip(client, tmp_storage_root):
    _stub(
        tmp_storage_root,
        "20260827-060000-000000",
        stage=STAGE_ENCODING,
        since=BOOT - timedelta(hours=5, minutes=51),
    )
    (_day(tmp_storage_root) / "20260827-060000-000000.mp4").write_bytes(REAL_MP4)
    assert _items(client)[0]["stage_stalled"] is True, "the defect, before the sweep"

    _sweep(tmp_storage_root)
    item = _items(client)[0]
    assert "stage_stalled" not in item
    assert item["status"] == "ready"


def test_the_haengt_card_stops_lying_when_there_is_nothing_to_recover(client, tmp_storage_root):
    """No file, so nothing to play. `filter_visible` already hides every
    media-less terminal event, so the card goes rather than turning into
    a permanent "fehlgeschlagen" tile — the manifest stays on disk and
    the integrity report lists it under "Einträge ohne Medienverweis"."""
    _stub(
        tmp_storage_root,
        "20260827-070000-000000",
        stage=STAGE_RECORDING,
        since=BOOT - timedelta(hours=1, minutes=20),
    )
    assert _items(client)[0]["stage_stalled"] is True, "the defect, before the sweep"

    _sweep(tmp_storage_root)
    assert _items(client) == []


# ── G · one vocabulary, not two ────────────────────────────────────────────
def test_both_halves_share_the_orphan_predicate():
    """A second definition of "this clip was abandoned" is how the two
    halves would start disagreeing about which events exist."""
    src = Path(clip_recovery.__file__).read_text(encoding="utf-8")
    assert src.count("def needs_adoption") == 1
    assert (
        src.count("needs_adoption(event)") == 2
    ), "the boot sweep and the shutdown stamp must both ask the same helper"
