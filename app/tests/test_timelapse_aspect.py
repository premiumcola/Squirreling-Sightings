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
letterboxed into the output box instead of distorted. (The OpenCV
fallback's half of the second fix is pinned separately, in
``test_timelapse_opencv_aspect``.)

These assertions used to read ``timelapse.py`` as a string — which
survived only as long as every line stayed in one file, and could not
tell a live guarantee from a comment. They now drive the real build and
inspect the ffmpeg command line it produces.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.timelapse import TimelapseBuilder  # noqa: E402

# Comfortably above frame_helpers' _MIN_FRAME_W/_MIN_FRAME_H.
_MAJORITY = (640, 480)
_ODD = (800, 400)


def _scene(w: int, h: int, seed: int) -> np.ndarray:
    """A plausible daytime garden frame at an arbitrary size.

    Needs enough colour spread to clear the grey-tone gate and enough
    local texture to clear the dead-area gate, and enough per-frame noise
    that the near-duplicate filter keeps every frame.
    """
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    yy, xx = np.meshgrid(np.arange(h // 2), np.arange(w), indexing="ij")
    img[: h // 2, :, 0] = np.clip(160 + (h // 2 - yy) * 0.3 + xx * 0.05, 0, 255).astype(np.uint8)
    img[: h // 2, :, 1] = np.clip(170 + (h // 2 - yy) * 0.2, 0, 255).astype(np.uint8)
    img[: h // 2, :, 2] = np.clip(150 + (h // 2 - yy) * 0.15, 0, 255).astype(np.uint8)
    img[h // 3 : h // 2, w // 8 : w // 3] = (40, 110, 70)
    img[h // 2 :, w // 2 :] = (90, 130, 165)
    img[h // 2 : h * 2 // 3, w // 3 : w // 2] = (60, 75, 95)
    img[h * 4 // 5 :, : w // 4] = (200, 180, 150)
    noise = rng.integers(-12, 13, size=img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _probe_json() -> bytes:
    return json.dumps(
        {
            "format": {"duration": "5.0", "nb_streams": 1, "size": "60000"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "nb_frames": "5"}],
        }
    ).encode()


def _build(tmp_path, monkeypatch, sizes):
    """Run a real build over frames of the given sizes.

    Returns the list of ffmpeg argv lists the encoder issued.
    """
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(parents=True)
    paths = []
    for i, (w, h) in enumerate(sizes):
        p = frames_dir / f"f{i:03d}.jpg"
        cv2.imwrite(str(p), _scene(w, h, seed=i + 1))
        paths.append(p)

    ffmpeg_calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "ffmpeg":
            ffmpeg_calls.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"\0" * 60_000)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if cmd and cmd[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout=_probe_json(), stderr=b"")
        raise AssertionError(f"unexpected subprocess call: {cmd!r}")

    # The encoder holds the subprocess MODULE, not a bound reference, so
    # patching the attribute on the module object reaches it.
    monkeypatch.setattr(subprocess, "run", _fake_run)

    builder = TimelapseBuilder(tmp_path / "storage")
    out = tmp_path / "storage" / "out.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    builder._write_video(paths, out, target_duration_s=10, target_fps=30)
    return ffmpeg_calls


def _vf(cmd: list[str]) -> str:
    return cmd[cmd.index("-vf") + 1]


# The odd frame goes FIRST — that is the whole point. Latching the first
# frame's size is exactly the defect under test.
_ODD_FIRST = [_ODD] + [_MAJORITY] * 4


def test_every_frame_size_is_counted_not_just_the_first(tmp_path, monkeypatch):
    """The first frame is 800x400; four others are 640x480. The output
    box must be the one four frames actually have."""
    calls = _build(tmp_path, monkeypatch, _ODD_FIRST)
    assert calls, "ffmpeg was never invoked"
    vf = _vf(calls[0])
    assert "scale=640:480" in vf, f"the first frame's size still decided the output box: {vf!r}"


def test_the_reference_size_is_the_majority_before_encoding(tmp_path, monkeypatch):
    """The pick must reach the encoder — choosing a majority and then
    handing the encoder something else would be no fix at all."""
    calls = _build(tmp_path, monkeypatch, _ODD_FIRST)
    vf = _vf(calls[0])
    assert "800:400" not in vf, f"the encoder was handed the odd frame's geometry: {vf!r}"


def test_the_majority_pick_is_deterministic_on_a_tie(tmp_path, monkeypatch):
    """With equal counts the winner must not depend on which size the
    scan happened to meet first, or two builds of the same folder could
    disagree."""
    a = _build(tmp_path / "a", monkeypatch, [_ODD, _ODD, _MAJORITY, _MAJORITY])
    b = _build(tmp_path / "b", monkeypatch, [_MAJORITY, _MAJORITY, _ODD, _ODD])
    assert _vf(a[0]) == _vf(b[0]), "a tie resolves differently depending on frame order"


def test_an_off_size_frame_is_letterboxed_not_stretched(tmp_path, monkeypatch):
    """`scale=w:h` alone distorts. The aspect-preserving pair is
    force_original_aspect_ratio=decrease plus pad."""
    vf = _vf(_build(tmp_path, monkeypatch, _ODD_FIRST)[0])
    assert "force_original_aspect_ratio=decrease" in vf, "off-size frames are still stretched"
    assert "pad=" in vf, "no padding — the scaled frame will not fill the output box"
    assert "setsar=1" in vf, "without setsar the player may re-apply a stale pixel aspect"


def test_the_scale_and_pad_targets_agree(tmp_path, monkeypatch):
    """A pad box smaller than the scale box crops; larger adds a second
    letterbox. They have to be the same numbers."""
    vf = _vf(_build(tmp_path, monkeypatch, _ODD_FIRST)[0])
    scale = re.search(r"scale=(\d+):(\d+)", vf)
    pad = re.search(r"pad=(\d+):(\d+)", vf)
    assert scale and pad, f"scale/pad no longer both carry explicit targets: {vf!r}"
    assert scale.groups() == pad.groups(), f"scale and pad disagree: {vf!r}"


def test_the_majority_choice_is_logged(tmp_path, monkeypatch, caplog):
    """When the majority and the first frame disagree the operator has to
    be able to see it — that is the only trace of a camera changing
    resolution mid-window."""
    with caplog.at_level(logging.INFO):
        _build(tmp_path, monkeypatch, _ODD_FIRST)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "majority frame size" in text, "the geometry override is invisible in the log"
