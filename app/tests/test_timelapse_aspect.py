"""The timelapse output aspect follows the majority of the frames.

Reported from the running system: the Squirrel-Town timelapse came out
"komisch" in format while the Werkstatt one, from a camera of the same
16:9 family, looked right.

Cause: `ref_size` latched the FIRST valid frame's dimensions and every
encoder then forced every frame to exactly that box — `scale=w:h` in the
ffmpeg path, `cv2.resize` in the OpenCV fallback. Neither preserves
aspect. So one odd frame (a camera answering a single snapshot at a
different resolution after a reconnect, a leftover frame from before a
resolution change) set the geometry for the whole film, and every other
frame was stretched to match it.

Two independent fixes, both pinned here: the reference size is now the
MODAL frame size rather than the first, and an off-size frame is
letterboxed into the output box instead of distorted.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "app" / "timelapse.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    start = _SRC.index(f"def {name}(")
    return _SRC[start : _SRC.index("\n    def ", start + 1)]


def test_every_frame_size_is_counted_not_just_the_first():
    assert "size_counts" in _SRC, "no tally of frame sizes — the first frame still decides"
    build = _SRC[_SRC.index("size_counts: dict") :]
    assert "size_counts[_sz] = size_counts.get(_sz, 0) + 1" in build


def test_the_reference_size_is_the_majority_before_encoding():
    """The pick must happen BEFORE the encoders are called, or they
    receive the first frame's size regardless of the tally."""
    pick = _SRC.index("majority = max(size_counts.items()")
    encode = _SRC.index("path = self._write_video_ffmpeg(")
    assert pick < encode, "the majority size is chosen after the encoder already ran"


def test_the_majority_pick_is_deterministic_on_a_tie():
    """`max` on counts alone returns whichever key the dict happens to
    yield first — two builds of the same folder could then differ."""
    seg = _SRC[_SRC.index("majority = max(size_counts.items()") :][:200]
    assert "(kv[1], kv[0])" in seg, "tie-break missing — the pick is not reproducible"


def test_an_off_size_frame_is_letterboxed_not_stretched():
    """`scale=w:h` alone distorts. The aspect-preserving pair is
    force_original_aspect_ratio=decrease plus pad."""
    vf = _fn("_write_video_ffmpeg")
    assert "force_original_aspect_ratio=decrease" in vf, "off-size frames are still stretched"
    assert "pad=" in vf, "no padding — the scaled frame will not fill the output box"
    assert "setsar=1" in vf, "without setsar the player may re-apply a stale pixel aspect"


def test_the_scale_and_pad_targets_agree():
    """A pad box smaller than the scale box crops; larger adds a second
    letterbox. They have to be the same numbers."""
    vf = _fn("_write_video_ffmpeg")
    scale = re.search(r"scale=\{out_w\}:\{out_h\}", vf)
    pad = re.search(r"pad=\{out_w\}:\{out_h\}", vf)
    assert scale and pad, "scale/pad no longer both target (out_w, out_h)"


def test_the_majority_choice_is_logged():
    """When the two disagree the operator has to be able to see it in
    the log — that is the only trace of a camera changing resolution."""
    seg = _SRC[_SRC.index("if size_counts:") :][:900]
    assert "majority frame size" in seg
    assert "log.info" in seg
