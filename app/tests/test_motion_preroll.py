"""Motion pre-roll: the ffmpeg stream-copy path's missing lead-in.

The confirmed diagnosis this closes: the ffmpeg stream-copy recording
path (RTSP `-c copy`, the path that preserves native resolution and the
one production actually runs) starts the encoder at trigger time —
0 seconds of pre-roll, regardless of what recording_settings.pre_motion_
seconds displayed. Two things had to be true at once for real pre-roll
to exist there:

  1. A continuously-running ring buffer of main-stream frames, because
     ffmpeg's own subprocess never hands a frame back to Python — the
     motion/detection loop's own decoded ``proc_frame`` is the only
     place a pre-roll source can come from.
  2. A splice step at finalize time that can fail in several distinct
     ways (too few buffered frames, a failed JPEG→mp4 encode, a failed
     concat, an unreadable spliced result) and in every one of them must
     leave the trigger-only clip that already works completely alone —
     never a corrupt file, never a lost recording.

This file covers both halves:

  * ``MotionPreroll`` — the ring itself (eviction at the time boundary,
    the byte-cap safety valve, the capacity_s=0 opt-out).
  * ``MotionPrerollMixin._splice_preroll_onto_clip`` — the splice, and
    every failure mode falling back to the untouched trigger-only clip.
  * ``resolve_pre_motion_seconds`` — the same "0 = inherit global
    default" convention post_motion_tail_s already uses.
  * The ``_recording_step.py`` wiring: ffmpeg-available feeds the new
    ring, not the legacy OpenCV-fallback ``_pre_buffer``, and vice versa.

ffmpeg itself is not installed in this sandbox (nor, most likely, in
CI's test runner), so the encode/concat calls are stubbed at the same
seam ``test_timelapse_unification.py`` already established for the
same reason — real subprocess calls are exercised only by
``_concat_preroll_and_clip``'s own guard clauses (missing/undersized
inputs, missing ffmpeg binary), which don't need a working binary to
prove they return False.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import app.camera_runtime._recording._preroll as preroll_mod
from app.camera_runtime._recording._preroll import (
    MotionPreroll,
    MotionPrerollMixin,
    resolve_pre_motion_seconds,
)


def _tiny_frame():
    return np.zeros((8, 8, 3), dtype="uint8")


class _Splicer(MotionPrerollMixin):
    def __init__(self, camera_id="cam1", cfg=None):
        self.camera_id = camera_id
        # The splice reads `record_audio` off the camera config; an empty
        # dict is the shipped default (audio off), which is what every
        # test in this file below asserts against.
        self.cfg = cfg or {}


class _FakeCap:
    """Stand-in for cv2.VideoCapture — reports a fixed frame count/fps
    without needing a real, ffmpeg-produced video file on disk."""

    def __init__(self, fc: int, fps: float):
        self._fc = fc
        self._fps = fps

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return self._fc
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        return 0

    def release(self):
        pass


# ── The ring ─────────────────────────────────────────────────────────────


def test_ring_evicts_frames_older_than_its_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(preroll_mod.time, "time", lambda: clock[0])
    ring = MotionPreroll("cam1", capacity_s=1.0)
    frame = _tiny_frame()

    ring.push(frame)  # t=1000.0 — will fall outside the 1s window by the end
    clock[0] = 1000.5
    ring.push(frame)  # t=1000.5
    clock[0] = 1001.5  # now 1000.0 is 1.5s stale, 1000.5 is 1.0s stale (kept)
    ring.push(frame)  # t=1001.5

    kept_ts = [round(t, 2) for t, _ in ring.snapshot()]
    assert kept_ts == [1000.5, 1001.5], "evicted the wrong end, or evicted nothing"


def test_ring_capacity_zero_disables_pushing_entirely(monkeypatch):
    """pre_motion_seconds: 0 must cost nothing per frame, not just hand
    back an empty snapshot — the operator turned the feature off."""
    ring = MotionPreroll("cam1", capacity_s=0.0)
    calls = []
    monkeypatch.setattr(
        cv2, "imencode", lambda *a, **k: (calls.append(1), (True, np.zeros(1, "uint8")))[1]
    )

    ring.push(_tiny_frame())

    assert ring.snapshot() == []
    assert calls == [], "paid for a JPEG encode on a ring that is turned off"


def test_a_none_frame_is_a_safe_no_op():
    ring = MotionPreroll("cam1", capacity_s=3.0)
    ring.push(None)  # must not raise
    assert ring.snapshot() == []


def test_the_byte_cap_binds_before_the_time_cutoff_and_is_logged(monkeypatch, caplog):
    """A run of unusually detailed frames must not outgrow the budget
    even though every frame is still inside the time window."""
    clock = [2000.0]
    monkeypatch.setattr(preroll_mod.time, "time", lambda: clock[0])
    ring = MotionPreroll("cam1", capacity_s=100.0, max_bytes=1)  # first frame already over cap
    caplog.set_level("WARNING")

    ring.push(_tiny_frame())
    clock[0] += 0.01
    ring.push(_tiny_frame())

    assert ring.bytes_held <= 1 or len(ring.snapshot()) <= 1
    assert ring.byte_cap_drops >= 1
    assert any("byte cap" in r.message for r in caplog.records)
    assert any("cam1" in r.message for r in caplog.records), "warning must name the camera"


def test_snapshot_is_a_frozen_copy(monkeypatch):
    clock = [3000.0]
    monkeypatch.setattr(preroll_mod.time, "time", lambda: clock[0])
    ring = MotionPreroll("cam1", capacity_s=10.0)
    ring.push(_tiny_frame())

    snap = ring.snapshot()
    clock[0] += 1.0
    ring.push(_tiny_frame())

    assert len(snap) == 1, "a later push mutated an already-taken snapshot"


# ── Config resolution ───────────────────────────────────────────────────


def test_camera_override_wins_over_the_global_default():
    assert resolve_pre_motion_seconds({"pre_motion_seconds": 5.0}, {}) == 5.0


def test_zero_on_the_camera_inherits_the_global_default():
    assert (
        resolve_pre_motion_seconds(
            {"pre_motion_seconds": 0}, {"processing": {"pre_motion_seconds": 7.0}}
        )
        == 7.0
    )


def test_the_shipped_default_is_three_seconds():
    assert resolve_pre_motion_seconds({}, {}) == 3.0
    assert resolve_pre_motion_seconds(None, None) == 3.0


# ── The splice: normal case ─────────────────────────────────────────────


def test_splice_success_replaces_the_clip_and_reports_the_real_span(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt1.mp4"
    vid_path.write_bytes(b"ORIGINAL-TRIGGER-CLIP" * 100)

    def _fake_encode(frames, out_path, fps, *, crf=22, log_tag="", silent_audio=False):
        Path(out_path).write_bytes(b"PREROLL-SEGMENT" * 100)
        return True

    def _fake_concat(preroll_path, main_path, out_path, want_audio=False):
        Path(out_path).write_bytes(b"SPLICED-RESULT" * 100)
        return True

    monkeypatch.setattr(preroll_mod, "encode_jpeg_frames_to_mp4", _fake_encode)
    monkeypatch.setattr(MotionPrerollMixin, "_concat_preroll_and_clip", staticmethod(_fake_concat))
    monkeypatch.setattr(preroll_mod.cv2, "VideoCapture", lambda p: _FakeCap(fc=30, fps=10.0))

    frames = [(1000.0 + i * 0.35, b"x") for i in range(9)]  # ~2.8s span
    achieved = _Splicer()._splice_preroll_onto_clip(vid_path, frames, "evt1", tmp_path)

    expected_span = frames[-1][0] - frames[0][0]
    assert achieved == pytest.approx(round(expected_span, 2), abs=0.01)
    assert vid_path.read_bytes() == b"SPLICED-RESULT" * 100
    assert not (tmp_path / "evt1.preroll.mp4").exists(), "temp pre-roll segment left on disk"
    assert not (tmp_path / "evt1.spliced.mp4").exists(), "temp spliced file left on disk"


def test_splice_with_a_not_yet_full_ring_reports_the_shorter_real_span(tmp_path, monkeypatch):
    """A camera that just started (or just had its clip start) has fewer
    buffered frames than the configured target — the achieved value must
    be the REAL shorter span, never the configured 3 s."""
    vid_path = tmp_path / "evt2.mp4"
    vid_path.write_bytes(b"ORIGINAL" * 100)
    monkeypatch.setattr(
        preroll_mod,
        "encode_jpeg_frames_to_mp4",
        lambda frames, out_path, fps, **kw: Path(out_path).write_bytes(b"x" * 2000) or True,
    )
    monkeypatch.setattr(
        MotionPrerollMixin,
        "_concat_preroll_and_clip",
        staticmethod(lambda pre, main, out, **kw: Path(out).write_bytes(b"y" * 2000) or True),
    )
    monkeypatch.setattr(preroll_mod.cv2, "VideoCapture", lambda p: _FakeCap(fc=10, fps=15.0))

    frames = [(1000.0, b"x"), (1000.6, b"x")]  # only 0.6s buffered
    achieved = _Splicer()._splice_preroll_onto_clip(vid_path, frames, "evt2", tmp_path)

    assert achieved == pytest.approx(0.6, abs=0.01)


# ── The splice: fallback / failure modes ────────────────────────────────


def test_splice_skips_with_fewer_than_two_frames(tmp_path, monkeypatch):
    """Nothing to derive a time span (and therefore an fps) from — must
    not even attempt an encode."""
    vid_path = tmp_path / "evt3.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    called = []
    monkeypatch.setattr(
        preroll_mod, "encode_jpeg_frames_to_mp4", lambda *a, **k: called.append(1) or True
    )
    splicer = _Splicer()

    assert splicer._splice_preroll_onto_clip(vid_path, [], "evt3", tmp_path) == 0.0
    assert splicer._splice_preroll_onto_clip(vid_path, [(1.0, b"x")], "evt3", tmp_path) == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"
    assert called == []


def test_splice_falls_back_when_the_encode_fails(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt4.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    concat_called = []
    monkeypatch.setattr(preroll_mod, "encode_jpeg_frames_to_mp4", lambda *a, **k: False)
    monkeypatch.setattr(
        MotionPrerollMixin,
        "_concat_preroll_and_clip",
        staticmethod(lambda *a, **kw: concat_called.append(1) or True),
    )
    splicer = _Splicer()

    achieved = splicer._splice_preroll_onto_clip(
        vid_path, [(1.0, b"x"), (1.5, b"x")], "evt4", tmp_path
    )

    assert achieved == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL", "the trigger-only clip must survive untouched"
    assert concat_called == [], "must not attempt a concat after a failed encode"


def test_splice_falls_back_when_the_concat_fails(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt5.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    monkeypatch.setattr(
        preroll_mod,
        "encode_jpeg_frames_to_mp4",
        lambda frames, out_path, fps, **kw: Path(out_path).write_bytes(b"PREROLL") or True,
    )
    monkeypatch.setattr(
        MotionPrerollMixin, "_concat_preroll_and_clip", staticmethod(lambda *a, **kw: False)
    )
    splicer = _Splicer()

    achieved = splicer._splice_preroll_onto_clip(
        vid_path, [(1.0, b"x"), (1.5, b"x")], "evt5", tmp_path
    )

    assert achieved == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"
    assert not (tmp_path / "evt5.preroll.mp4").exists(), "temp pre-roll segment not cleaned up"


def test_splice_falls_back_when_the_result_is_unreadable(tmp_path, monkeypatch):
    """encode + concat both report success but hand back something cv2
    cannot make sense of (e.g. a truncated/corrupt mp4) — never trust the
    exit code alone over the trigger-only clip we already know plays."""
    vid_path = tmp_path / "evt6.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    monkeypatch.setattr(
        preroll_mod,
        "encode_jpeg_frames_to_mp4",
        lambda frames, out_path, fps, **kw: Path(out_path).write_bytes(b"PREROLL") or True,
    )
    monkeypatch.setattr(
        MotionPrerollMixin,
        "_concat_preroll_and_clip",
        staticmethod(lambda pre, main, out, **kw: Path(out).write_bytes(b"CORRUPT") or True),
    )
    monkeypatch.setattr(preroll_mod.cv2, "VideoCapture", lambda p: _FakeCap(fc=0, fps=0.0))
    splicer = _Splicer()

    achieved = splicer._splice_preroll_onto_clip(
        vid_path, [(1.0, b"x"), (1.5, b"x")], "evt6", tmp_path
    )

    assert achieved == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"
    assert not (tmp_path / "evt6.spliced.mp4").exists(), "the bad spliced file left on disk"


# ── _concat_preroll_and_clip's own guard clauses (no mocking) ───────────


def test_concat_refuses_missing_inputs(tmp_path):
    ok = MotionPrerollMixin._concat_preroll_and_clip(
        tmp_path / "missing-pre.mp4", tmp_path / "missing-main.mp4", tmp_path / "out.mp4"
    )
    assert ok is False


def test_concat_refuses_undersized_inputs(tmp_path):
    pre = tmp_path / "pre.mp4"
    pre.write_bytes(b"x")  # under the 1024-byte floor
    main = tmp_path / "main.mp4"
    main.write_bytes(b"y" * 2000)
    assert MotionPrerollMixin._concat_preroll_and_clip(pre, main, tmp_path / "out.mp4") is False


def test_concat_refuses_when_ffmpeg_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(preroll_mod.shutil, "which", lambda _: None)
    pre = tmp_path / "pre.mp4"
    pre.write_bytes(b"x" * 2000)
    main = tmp_path / "main.mp4"
    main.write_bytes(b"y" * 2000)

    assert MotionPrerollMixin._concat_preroll_and_clip(pre, main, tmp_path / "out.mp4") is False


# ── _recording_step.py wiring ────────────────────────────────────────────


class _FakeRing:
    def __init__(self):
        self.pushed = []

    def push(self, frame):
        self.pushed.append(frame)


def test_ffmpeg_available_feeds_the_ring_not_the_legacy_buffer(monkeypatch):
    import app.camera_runtime._recording_step as step_mod

    monkeypatch.setattr(step_mod, "_FFMPEG_AVAILABLE", True)

    class _RT(step_mod.RecordingStepMixin):
        def __init__(self):
            self.global_cfg = {"processing": {}}
            self.cfg = {}
            self._recording = False
            self._pre_buffer = []
            self.motion_preroll = _FakeRing()

    rt = _RT()
    frame = _tiny_frame()
    rt._rtsp_recording_step(
        proc_frame=frame,
        now_dt=None,
        has_motion=False,
        labels=[],
        detections=[],
        drawn=None,
        effective_bbox=None,
        cooldown=10,
    )

    assert rt.motion_preroll.pushed == [frame]
    assert rt._pre_buffer == []


def test_ffmpeg_unavailable_feeds_the_legacy_buffer_not_the_ring(monkeypatch):
    import app.camera_runtime._recording_step as step_mod

    monkeypatch.setattr(step_mod, "_FFMPEG_AVAILABLE", False)

    class _RT(step_mod.RecordingStepMixin):
        def __init__(self):
            self.global_cfg = {"processing": {}}
            self.cfg = {}
            self._recording = False
            self._pre_buffer = []
            self.motion_preroll = _FakeRing()

    rt = _RT()
    frame = _tiny_frame()
    rt._rtsp_recording_step(
        proc_frame=frame,
        now_dt=None,
        has_motion=False,
        labels=[],
        detections=[],
        drawn=None,
        effective_bbox=None,
        cooldown=10,
    )

    assert rt.motion_preroll.pushed == []
    assert len(rt._pre_buffer) == 1
