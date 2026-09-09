"""Splicing REAL ring-buffer footage onto a finished clip — see
``_ring_splice.py``'s own module docstring. The stills-based counterpart
(``_preroll.py::_splice_preroll_onto_clip``) is covered in
``test_motion_preroll.py``, including the two tests there proving it
tries this ring path FIRST and only falls back to stills when this
returns 0.0.

ffmpeg/ffprobe are not installed in this sandbox (see
``test_motion_preroll.py``'s module docstring for the same fact), so the
concat/probe calls are stubbed at the same seam that file already
established.
"""

from __future__ import annotations

from pathlib import Path

import cv2

import app.camera_runtime._recording._ring_splice as ring_splice_mod
from app.camera_runtime._recording._preroll import MotionPrerollMixin
from app.camera_runtime._recording._ring_splice import RingPrerollSpliceMixin


class _RingSplicer(RingPrerollSpliceMixin, MotionPrerollMixin):
    def __init__(self, camera_id="cam1", cfg=None):
        self.camera_id = camera_id
        self.cfg = cfg or {}


class _FakeCap:
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


# ── _probe_duration_s ────────────────────────────────────────────────────


def test_probe_duration_s_computes_frames_over_fps(tmp_path, monkeypatch):
    monkeypatch.setattr(ring_splice_mod.cv2, "VideoCapture", lambda p: _FakeCap(fc=60, fps=30.0))
    assert RingPrerollSpliceMixin._probe_duration_s(tmp_path / "x.mp4") == 2.0


def test_probe_duration_s_is_zero_when_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(ring_splice_mod.cv2, "VideoCapture", lambda p: _FakeCap(fc=0, fps=0.0))
    assert RingPrerollSpliceMixin._probe_duration_s(tmp_path / "x.mp4") == 0.0


# ── the splice: normal cases ─────────────────────────────────────────────


def test_a_single_segment_is_copied_then_spliced(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt1.mp4"
    vid_path.write_bytes(b"ORIGINAL-TRIGGER-CLIP" * 100)
    seg = tmp_path / "1000.mp4"
    seg.write_bytes(b"RING-SEGMENT" * 100)
    concat_calls = []

    def _fake_concat(paths, out_path, want_audio=False):
        concat_calls.append((list(paths), want_audio))
        Path(out_path).write_bytes(b"SPLICED" * 200)
        return True

    monkeypatch.setattr(MotionPrerollMixin, "_concat_segments", staticmethod(_fake_concat))
    monkeypatch.setattr(RingPrerollSpliceMixin, "_probe_duration_s", staticmethod(lambda p: 2.5))
    monkeypatch.setattr(MotionPrerollMixin, "_is_playable", staticmethod(lambda p: True))
    splicer = _RingSplicer()

    achieved = splicer._splice_ring_preroll_onto_clip(vid_path, [seg], "evt1", tmp_path)

    assert achieved == 2.5
    assert vid_path.read_bytes() == b"SPLICED" * 200
    assert len(concat_calls) == 1, "a single segment must be copied, not concat-joined, first"
    joined_paths, want_audio = concat_calls[0]
    assert joined_paths[1] == vid_path
    assert want_audio is False
    assert not (tmp_path / "evt1.ringpre.mp4").exists()
    assert not (tmp_path / "evt1.ringspliced.mp4").exists()


def test_multiple_segments_are_joined_then_spliced(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt2.mp4"
    vid_path.write_bytes(b"ORIGINAL" * 100)
    seg_a = tmp_path / "1000.mp4"
    seg_b = tmp_path / "1001.mp4"
    seg_a.write_bytes(b"A" * 2000)
    seg_b.write_bytes(b"B" * 2000)
    concat_calls = []

    def _fake_concat(paths, out_path, want_audio=False):
        concat_calls.append(list(paths))
        Path(out_path).write_bytes(b"OUT" * 500)
        return True

    monkeypatch.setattr(MotionPrerollMixin, "_concat_segments", staticmethod(_fake_concat))
    monkeypatch.setattr(RingPrerollSpliceMixin, "_probe_duration_s", staticmethod(lambda p: 1.8))
    monkeypatch.setattr(MotionPrerollMixin, "_is_playable", staticmethod(lambda p: True))
    splicer = _RingSplicer()

    achieved = splicer._splice_ring_preroll_onto_clip(vid_path, [seg_a, seg_b], "evt2", tmp_path)

    assert achieved == 1.8
    assert len(concat_calls) == 2, "must join the segments AND splice the join onto the clip"
    assert concat_calls[0] == [seg_a, seg_b]
    assert concat_calls[1][1] == vid_path


# ── the splice: fallback / failure modes ────────────────────────────────


def test_empty_ring_segments_is_a_safe_no_op(tmp_path):
    vid_path = tmp_path / "evt3.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    splicer = _RingSplicer()

    assert splicer._splice_ring_preroll_onto_clip(vid_path, [], "evt3", tmp_path) == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"


def test_falls_back_when_joining_multiple_segments_fails(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt4.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    seg_a = tmp_path / "1000.mp4"
    seg_b = tmp_path / "1001.mp4"
    seg_a.write_bytes(b"A" * 2000)
    seg_b.write_bytes(b"B" * 2000)
    calls = []
    monkeypatch.setattr(
        MotionPrerollMixin,
        "_concat_segments",
        staticmethod(lambda *a, **k: calls.append(1) or False),
    )
    splicer = _RingSplicer()

    achieved = splicer._splice_ring_preroll_onto_clip(vid_path, [seg_a, seg_b], "evt4", tmp_path)

    assert achieved == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"
    assert calls == [1], "must not attempt the splice-onto-clip step after a failed join"


def test_falls_back_when_the_joined_preroll_is_unreadable(tmp_path, monkeypatch):
    """Join reports success but the result probes to 0s — never trust the
    exit code alone (same rule the stills splice already follows)."""
    vid_path = tmp_path / "evt5.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    seg = tmp_path / "1000.mp4"
    seg.write_bytes(b"X" * 2000)
    splice_calls = []
    monkeypatch.setattr(
        MotionPrerollMixin,
        "_concat_segments",
        staticmethod(lambda *a, **k: splice_calls.append(1) or True),
    )
    monkeypatch.setattr(RingPrerollSpliceMixin, "_probe_duration_s", staticmethod(lambda p: 0.0))
    splicer = _RingSplicer()

    achieved = splicer._splice_ring_preroll_onto_clip(vid_path, [seg], "evt5", tmp_path)

    assert achieved == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"
    assert splice_calls == [], "must not splice an unreadable pre-roll onto the clip"


def test_falls_back_when_the_splice_onto_clip_fails(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt6.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    seg = tmp_path / "1000.mp4"
    seg.write_bytes(b"X" * 2000)
    monkeypatch.setattr(RingPrerollSpliceMixin, "_probe_duration_s", staticmethod(lambda p: 3.0))
    monkeypatch.setattr(MotionPrerollMixin, "_concat_segments", staticmethod(lambda *a, **k: False))
    splicer = _RingSplicer()

    achieved = splicer._splice_ring_preroll_onto_clip(vid_path, [seg], "evt6", tmp_path)

    assert achieved == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"


def test_falls_back_when_the_final_spliced_result_is_unreadable(tmp_path, monkeypatch):
    vid_path = tmp_path / "evt7.mp4"
    vid_path.write_bytes(b"ORIGINAL")
    seg = tmp_path / "1000.mp4"
    seg.write_bytes(b"X" * 2000)

    def _fake_concat(paths, out_path, want_audio=False):
        Path(out_path).write_bytes(b"CORRUPT" * 200)
        return True

    monkeypatch.setattr(RingPrerollSpliceMixin, "_probe_duration_s", staticmethod(lambda p: 3.0))
    monkeypatch.setattr(MotionPrerollMixin, "_concat_segments", staticmethod(_fake_concat))
    monkeypatch.setattr(MotionPrerollMixin, "_is_playable", staticmethod(lambda p: False))
    splicer = _RingSplicer()

    achieved = splicer._splice_ring_preroll_onto_clip(vid_path, [seg], "evt7", tmp_path)

    assert achieved == 0.0
    assert vid_path.read_bytes() == b"ORIGINAL"
    assert not (tmp_path / "evt7.ringspliced.mp4").exists()
