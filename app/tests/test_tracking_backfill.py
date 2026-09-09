"""The fine track catches itself up — nobody has to press a button.

„Was heisst Feinspur nachbauen wozu?? Ich will wenn ichs anschau dass
alles bereit und fertig ist!"

Until this existed, a clip that missed its `tracks.json` (the worker was
busy, the container restarted mid-encode, the clip predates the sidecar
entirely) kept a note in the player offering a REBUILD BUTTON, and stayed
that way until somebody pressed it. The scan behind that button now also
runs unattended on the daily maintenance tick — one implementation for
both, per CLAUDE.md's no-parallel-implementations rule.

Stub-based: no real worker thread, no decode. `_FakeWorker` records what
it was handed, which is the whole contract this sweep has.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.tracking_worker._backfill import DEFAULT_BACKFILL_BUDGET, sweep_missing_tracks
from app.tracking_worker._consts import TRACKS_SCHEMA

CAM = "reolink_cx810_squirreltownnutbar_181"
DAY = "2026-04-30"


class _FakeWorker:
    def __init__(self):
        self.jobs = []

    def enqueue(self, job):
        self.jobs.append(job)


class _FakeStore:
    def __init__(self, root: Path):
        self.events_dir = root / "motion_detection"


def _clip(root: Path, event_id: str, *, sidecar_schema=None, with_video=True) -> None:
    """One event JSON, its mp4, and optionally a tracks sidecar."""
    day = root / "motion_detection" / CAM / DAY
    day.mkdir(parents=True, exist_ok=True)
    rel = f"motion_detection/{CAM}/{DAY}/{event_id}.mp4"
    if with_video:
        (root / rel).write_bytes(b"\x00" * 2048)
    (day / f"{event_id}.json").write_text(
        json.dumps({"event_id": event_id, "camera_id": CAM, "video_relpath": rel}),
        encoding="utf-8",
    )
    if sidecar_schema is not None:
        (day / f"{event_id}.tracks.json").write_text(
            json.dumps({"schema": sidecar_schema, "tracks": []}), encoding="utf-8"
        )


def _sweep(root: Path, worker, **kw) -> dict:
    return sweep_missing_tracks(_FakeStore(root), root, worker, **kw)


def test_a_clip_without_a_sidecar_is_queued(tmp_path):
    _clip(tmp_path, "20260430-100000-000000")
    worker = _FakeWorker()

    result = _sweep(tmp_path, worker)

    assert result["queued"] == 1
    assert worker.jobs[0].camera_id == CAM
    assert worker.jobs[0].event_id == "20260430-100000-000000"


def test_a_current_sidecar_is_left_alone(tmp_path):
    _clip(tmp_path, "20260430-100000-000000", sidecar_schema=TRACKS_SCHEMA)
    worker = _FakeWorker()

    result = _sweep(tmp_path, worker)

    assert result == {"queued": 0, "up_to_date": 1, "missing_video": 0, "remaining": 0}
    assert worker.jobs == []


def test_a_sidecar_from_an_older_schema_is_rebuilt(tmp_path):
    _clip(tmp_path, "20260430-100000-000000", sidecar_schema=TRACKS_SCHEMA - 1)
    worker = _FakeWorker()

    assert _sweep(tmp_path, worker)["queued"] == 1


def test_a_corrupt_sidecar_is_treated_as_missing(tmp_path):
    _clip(tmp_path, "20260430-100000-000000")
    day = tmp_path / "motion_detection" / CAM / DAY
    (day / "20260430-100000-000000.tracks.json").write_text("{not json", encoding="utf-8")
    worker = _FakeWorker()

    assert _sweep(tmp_path, worker)["queued"] == 1


def test_an_event_whose_video_is_gone_is_reported_not_queued(tmp_path):
    _clip(tmp_path, "20260430-100000-000000", with_video=False)
    worker = _FakeWorker()

    result = _sweep(tmp_path, worker)

    assert result["queued"] == 0
    assert result["missing_video"] == 1


def test_the_budget_stops_the_pass_and_says_what_is_left(tmp_path):
    """Each job decodes a clip, so an un-indexed archive must not turn one
    nightly tick into hours of CPU — the rest goes to the next tick."""
    for i in range(5):
        _clip(tmp_path, f"20260430-1000{i}0-000000")
    worker = _FakeWorker()

    result = _sweep(tmp_path, worker, budget=2)

    assert result["queued"] == 2
    assert result["remaining"] == 3
    assert len(worker.jobs) == 2


def test_a_camera_filter_narrows_the_scan(tmp_path):
    _clip(tmp_path, "20260430-100000-000000")
    worker = _FakeWorker()

    assert _sweep(tmp_path, worker, cam_filter="some_other_cam")["queued"] == 0
    assert _sweep(tmp_path, worker, cam_filter=CAM)["queued"] == 1


def test_no_worker_is_a_safe_no_op(tmp_path):
    _clip(tmp_path, "20260430-100000-000000")

    assert sweep_missing_tracks(_FakeStore(tmp_path), tmp_path, None)["queued"] == 0


def test_an_empty_archive_is_a_safe_no_op(tmp_path):
    assert _sweep(tmp_path, _FakeWorker())["queued"] == 0


def test_the_unattended_budget_is_bounded():
    """A guard on the constant itself: an unbounded nightly pass over a
    large archive is the failure mode this budget exists to prevent."""
    assert 0 < DEFAULT_BACKFILL_BUDGET <= 200
