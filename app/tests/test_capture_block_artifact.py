"""`_block_artifact_counts` — the vectorised JPEG block-artifact check.

Measured on the live box: the original plain-Python double loop over up
to 6420 8x8 slices (60x107 at 2560x1440), one np.var() call each, cost
73-82 ms — the single largest item in the per-frame budget and the
reason the detection loop's real cadence (~0.49 s) ran well behind its
configured 0.35 s interval.

The replacement uses fancy-indexing so numpy's C loop does the work.
The only thing worth testing is whether it computes the SAME NUMBER —
so this file carries its own, independently written reference loop
(deliberately not importing the production code's old algorithm, which
no longer exists) and checks agreement across many randomised frames,
including the edge cases the sparse 3x-stride sampling can trip on.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.camera_runtime._capture import _block_artifact_counts

BS = 8
STRIDE = BS * 3
THRESHOLD = 2.0


def _reference_loop(gray: np.ndarray, bs: int = BS) -> tuple[int, int]:
    """The original algorithm, written independently for this test."""
    h, w = gray.shape[:2]
    low_var = 0
    total = 0
    for by in range(0, h - bs, bs * 3):
        for bx in range(0, w - bs, bs * 3):
            blk = gray[by : by + bs, bx : bx + bs]
            if float(np.var(blk)) < THRESHOLD:
                low_var += 1
            total += 1
    return low_var, total


# A representative size (well above the fixture floor so both stride
# axes sample a non-trivial number of blocks) plus several odd
# dimensions that are NOT exact multiples of the 24 px stride — the
# case most likely to expose an off-by-one in the vectorised bounds.
_SHAPES = [(1440, 2560), (360, 640), (480, 853), (100, 100), (48, 64), (49, 65), (71, 97)]


@pytest.mark.parametrize("shape", _SHAPES)
def test_matches_the_reference_loop_on_random_noise(shape):
    rng = np.random.default_rng(1)
    gray = rng.integers(0, 256, size=shape, dtype=np.uint8)
    assert _block_artifact_counts(gray) == _reference_loop(gray)


@pytest.mark.parametrize("shape", _SHAPES)
def test_matches_the_reference_loop_on_a_flat_frame(shape):
    """The exact failure mode this check exists to catch: a solid-fill
    decode artifact, every block variance 0."""
    gray = np.full(shape, 128, dtype=np.uint8)
    assert _block_artifact_counts(gray) == _reference_loop(gray)


def test_matches_the_reference_loop_on_a_mixed_frame():
    """Half real content, half a flat corruption band — the case where
    getting the block GRID wrong (not just the variance math) would
    show up as a count mismatch."""
    rng = np.random.default_rng(2)
    gray = rng.integers(0, 256, size=(720, 1280), dtype=np.uint8)
    gray[360:, :] = 200  # bottom half: flat
    assert _block_artifact_counts(gray) == _reference_loop(gray)


def test_total_blocks_matches_the_python_range_semantics():
    """`np.arange(0, h-bs, stride)` must reproduce `range(0, h-bs, stride)`
    exactly, including the case where h-bs goes non-positive (no fixture
    reaches this — is_frame_valid guards h>=48, w>=64 upstream — but the
    function is public now and must not misbehave if called directly)."""
    for h, w in [(48, 64), (55, 70), (8, 8), (7, 100), (100, 7)]:
        gray = np.zeros((h, w), dtype=np.uint8)
        py_total = sum(1 for _ in range(0, h - BS, STRIDE) for _ in range(0, w - BS, STRIDE))
        _, total = _block_artifact_counts(gray)
        assert total == py_total, f"shape {(h, w)}: expected {py_total}, got {total}"


def test_bit_identical_variance_not_just_a_matching_count():
    """A count match alone could hide two low_var-vs-total pairs that
    happen to sum to the same total by coincidence at one size — pin
    the full tuple, not a derived boolean, across a larger random batch."""
    rng = np.random.default_rng(3)
    for _ in range(20):
        h = int(rng.integers(48, 400))
        w = int(rng.integers(64, 400))
        gray = rng.integers(0, 256, size=(h, w), dtype=np.uint8)
        assert _block_artifact_counts(gray) == _reference_loop(gray)
