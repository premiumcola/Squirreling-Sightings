"""The continuous stream-copy ring buffer — see ``_ring_buffer.py``'s own
module docstring for why it exists (the operator's "wieso kein
Loop-Stream?!" pushback on the old stills-based pre-roll).

Covers the pure segment-selection helpers (no filesystem, no subprocess)
and ``StreamRingBufferMixin``'s real-filesystem glue. ffmpeg itself is
not installed in this sandbox (see ``test_motion_preroll.py``'s module
docstring for the same fact) — the spawn path is exercised for real
where that's exactly the point (missing-binary handling needs no mock),
and mocked only where a genuinely running subprocess is what's under
test.
"""

from __future__ import annotations

import time
from pathlib import Path

import app.camera_runtime._recording._ring_buffer as ring_mod
from app.camera_runtime._recording._ring_buffer import (
    StreamRingBufferMixin,
    parse_segment_stem,
    segments_covering,
    stale_segments,
)


class _Ring(StreamRingBufferMixin):
    def __init__(self, camera_id, storage_root, rtsp_url="rtsp://192.0.2.10/stream"):
        self.camera_id = camera_id
        self.global_cfg = {"storage": {"root": str(storage_root)}}
        self.cfg = {"rtsp_url": rtsp_url} if rtsp_url else {}


class _FakeProc:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class _OneShotEvent:
    """Stands in for threading.Event in a direct (non-threaded) call to
    ``_ring_cleanup_loop`` — False on the first wait() (run one sweep),
    True on the second (stop), so the loop body runs exactly once."""

    def __init__(self):
        self.calls = 0

    def wait(self, timeout=None):
        self.calls += 1
        return self.calls > 1


# ── pure helpers ─────────────────────────────────────────────────────────


def test_parse_segment_stem_reads_the_epoch_filename(tmp_path):
    assert parse_segment_stem(tmp_path / "1700000000.mp4") == 1700000000.0


def test_parse_segment_stem_rejects_a_non_numeric_stem(tmp_path):
    assert parse_segment_stem(tmp_path / "not-a-timestamp.mp4") is None


def test_segments_covering_sorts_unsorted_input_and_keeps_the_overlap():
    a = (1000.0, Path("a.mp4"))
    b = (1001.0, Path("b.mp4"))
    c = (1002.0, Path("c.mp4"))
    out = segments_covering([c, a, b], start_ts=1000.5, end_ts=1001.5, segment_time_s=1.0)
    assert out == [Path("a.mp4"), Path("b.mp4")]


def test_segments_covering_excludes_a_segment_that_ended_before_the_window():
    a = (1000.0, Path("a.mp4"))
    b = (1001.0, Path("b.mp4"))
    out = segments_covering([a, b], start_ts=1001.5, end_ts=1002.0, segment_time_s=1.0)
    assert out == [Path("b.mp4")]


def test_segments_covering_excludes_a_segment_that_starts_after_the_window():
    a = (1000.0, Path("a.mp4"))
    b = (2000.0, Path("b.mp4"))
    out = segments_covering([a, b], start_ts=999.0, end_ts=1000.5, segment_time_s=1.0)
    assert out == [Path("a.mp4")]


def test_segments_covering_estimates_the_last_segments_end_generously():
    """The last segment has no next-segment start to bound it — its end is
    estimated as start + 4*segment_time_s, generous over the janitor not
    having written the next file yet."""
    only = (1000.0, Path("only.mp4"))
    assert segments_covering([only], start_ts=1003.9, end_ts=1004.0, segment_time_s=1.0) == [
        Path("only.mp4")
    ]
    assert segments_covering([only], start_ts=1004.1, end_ts=1005.0, segment_time_s=1.0) == []


def test_stale_segments_selects_only_what_is_older_than_the_cutoff():
    stamped = [(100.0, Path("old.mp4")), (200.0, Path("new.mp4"))]
    assert stale_segments(stamped, cutoff_ts=150.0) == [Path("old.mp4")]


# ── the mixin's filesystem glue ──────────────────────────────────────────


def test_ring_buffer_dir_is_per_camera_under_storage_root(tmp_path):
    rt = _Ring("cam1", tmp_path)
    assert rt._ring_buffer_dir() == tmp_path / "_ring" / "cam1"


def test_ring_stamped_segments_reads_real_files_and_skips_junk(tmp_path):
    rt = _Ring("cam1", tmp_path)
    ring_dir = rt._ring_buffer_dir()
    ring_dir.mkdir(parents=True)
    (ring_dir / "1000.mp4").write_bytes(b"x")
    (ring_dir / "1001.mp4").write_bytes(b"x")
    (ring_dir / "not-a-timestamp.mp4").write_bytes(b"x")
    (ring_dir / "1002.txt").write_bytes(b"x")

    names = {p.name for _, p in rt._ring_stamped_segments()}
    assert names == {"1000.mp4", "1001.mp4"}


def test_ring_stamped_segments_empty_when_directory_never_created(tmp_path):
    rt = _Ring("cam1", tmp_path)
    assert rt._ring_stamped_segments() == []


def test_ring_segments_covering_selects_by_wallclock(tmp_path):
    rt = _Ring("cam1", tmp_path)
    ring_dir = rt._ring_buffer_dir()
    ring_dir.mkdir(parents=True)
    (ring_dir / "1000.mp4").write_bytes(b"x")
    (ring_dir / "1002.mp4").write_bytes(b"x")
    (ring_dir / "1004.mp4").write_bytes(b"x")

    names = {p.name for p in rt._ring_segments_covering(1001.5, 1003.0)}
    assert names == {"1000.mp4", "1002.mp4"}


def test_ring_segments_covering_empty_when_the_buffer_never_started(tmp_path):
    rt = _Ring("cam1", tmp_path)
    assert rt._ring_segments_covering(0.0, 10.0) == []


# ── start/stop — a snapshot-only camera and a missing ffmpeg binary ─────


def test_start_ring_buffer_noop_when_the_camera_has_no_rtsp_url(tmp_path):
    rt = _Ring("cam1", tmp_path, rtsp_url=None)
    rt._start_ring_buffer()
    assert getattr(rt, "_ring_proc", None) is None


def test_start_ring_buffer_handles_a_missing_ffmpeg_binary_gracefully(tmp_path):
    rt = _Ring("cam1", tmp_path)
    rt._start_ring_buffer()
    assert getattr(rt, "_ring_proc", None) is None
    assert rt._ring_buffer_dir().is_dir(), "directory must be created before the spawn attempt"


def test_stop_ring_buffer_is_a_safe_no_op_when_nothing_was_started(tmp_path):
    rt = _Ring("cam1", tmp_path)
    rt._stop_ring_buffer()  # must not raise


def test_start_ring_buffer_spawns_the_segment_muxer_and_stop_terminates_it(tmp_path, monkeypatch):
    calls = []

    def _fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProc()

    monkeypatch.setattr(ring_mod._subprocess, "Popen", _fake_popen)
    rt = _Ring("cam1", tmp_path)

    rt._start_ring_buffer()

    assert rt._ring_proc is not None
    assert len(calls) == 1
    cmd = calls[0]
    assert "segment" in cmd, "must use the segment muxer, not a single growing file"
    assert cmd[cmd.index("-i") + 1] == "rtsp://192.0.2.10/stream"

    rt._stop_ring_buffer()
    assert rt._ring_proc is None


def test_start_ring_buffer_stops_a_previous_instance_first(tmp_path, monkeypatch):
    procs = []

    def _fake_popen(cmd, **kwargs):
        p = _FakeProc()
        procs.append(p)
        return p

    monkeypatch.setattr(ring_mod._subprocess, "Popen", _fake_popen)
    rt = _Ring("cam1", tmp_path)

    rt._start_ring_buffer()
    first = rt._ring_proc
    rt._start_ring_buffer()
    second = rt._ring_proc

    assert first is not second
    assert first.terminated, "the previous ffmpeg instance was never stopped"
    rt._stop_ring_buffer()


# ── the janitor sweep ─────────────────────────────────────────────────────


def test_ring_cleanup_loop_deletes_only_segments_older_than_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(ring_mod, "_ring_seconds", lambda: 10.0)
    rt = _Ring("cam1", tmp_path)
    ring_dir = rt._ring_buffer_dir()
    ring_dir.mkdir(parents=True)
    now = time.time()
    old = ring_dir / f"{int(now - 20)}.mp4"
    fresh = ring_dir / f"{int(now - 1)}.mp4"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")

    rt._ring_cleanup_loop(_OneShotEvent())

    assert not old.exists()
    assert fresh.exists()
