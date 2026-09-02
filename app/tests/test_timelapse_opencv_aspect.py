"""The OpenCV fallback encoder must letterbox an off-size frame, not stretch it.

``test_timelapse_aspect`` documents the original defect: one odd frame —
a camera answering a single snapshot at a different resolution after a
reconnect — set the geometry for a whole timelapse, and every other
frame was stretched to match. Its own cause section names BOTH encoders:
``scale=w:h`` in the ffmpeg path and ``cv2.resize`` in the OpenCV
fallback, and it calls the repair "two independent fixes".

Only the ffmpeg path was ever repaired. ``_write_video_opencv`` still
resizes an off-size frame straight onto the output box, which distorts
it. The fallback is not dead code: ``_write_video`` calls it whenever
ffmpeg is missing or returns non-zero, so on a host without ffmpeg the
original bug is still shipping in full.

Assertion strategy: a 2:1 white frame fitted into a 4:3 output box must
come out with black bars. Aspect-preserving fit of 100x50 into 64x48
scales by min(64/100, 48/50) = 0.64 to 64x32, leaving 8 black rows top
and bottom. A plain stretch leaves the frame white edge to edge.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.timelapse import TimelapseBuilder  # noqa: E402


class _RecordingWriter:
    """Stand-in for ``cv2.VideoWriter`` that keeps what was written."""

    def __init__(self):
        self.frames: list[np.ndarray] = []
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802  (mirrors the cv2 API)
        return True

    def write(self, img) -> None:
        self.frames.append(img.copy())

    def release(self) -> None:
        self.released = True


def _encode_with_recorder(monkeypatch, tmp_path, frames, ref_size):
    """Run ``_write_video_opencv`` over ``frames``, return what it wrote."""
    rec = _RecordingWriter()
    monkeypatch.setattr(cv2, "VideoWriter", lambda *a, **k: rec)
    paths = []
    for i, img in enumerate(frames):
        p = tmp_path / f"f{i:03d}.jpg"
        cv2.imwrite(str(p), img)
        paths.append(p)
    builder = TimelapseBuilder(tmp_path / "storage")
    builder._write_video_opencv(paths, tmp_path / "out.mp4", 10.0, ref_size)
    return rec.frames


def test_an_off_size_frame_is_letterboxed_by_the_opencv_fallback(monkeypatch, tmp_path):
    """A 2:1 frame in a 4:3 box keeps its aspect and gains black bars."""
    odd = np.full((50, 100, 3), 255, dtype=np.uint8)  # 2:1, all white
    written = _encode_with_recorder(monkeypatch, tmp_path, [odd], (64, 48))

    assert written, "the fallback encoder wrote no frame at all"
    out = written[0]
    assert out.shape[:2] == (48, 64), f"output box is {out.shape[:2]}, expected (48, 64)"

    top_bar = out[0:8]
    bottom_bar = out[40:48]
    middle = out[8:40]
    assert middle.max() > 200, "the scaled content is missing from the middle of the box"
    assert top_bar.max() == 0, "no black bar on top — the off-size frame was stretched, not fitted"
    assert bottom_bar.max() == 0, "no black bar at the bottom — the frame was stretched"


def test_a_matching_frame_is_untouched_by_the_opencv_fallback(monkeypatch, tmp_path):
    """The letterbox must not add bars to a frame that already fits."""
    exact = np.full((48, 64, 3), 255, dtype=np.uint8)
    written = _encode_with_recorder(monkeypatch, tmp_path, [exact], (64, 48))

    assert written, "the fallback encoder wrote no frame at all"
    out = written[0]
    assert out.shape[:2] == (48, 64)
    assert out.min() > 200, "a correctly sized frame gained padding it does not need"
