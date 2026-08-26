"""Primitives over a track's sample list and over sample bboxes.

A ``tracks.json`` sample is a plain dict — ``{"f", "t", "bbox",
"score", "source"}`` — and half the package's helpers used to re-open
that shape inline. One definition each, here, so the static-FP sweep,
the stitcher, the ghost prune and the achievement aggregator all agree
on what "observed" means and how a bbox dict is read.

Centre-to-centre distance is deliberately NOT redefined here —
``bbox_utils.bbox_centroid_dist`` already takes the sample bbox dict
shape and is what every call site uses.
"""

from __future__ import annotations

# Sample sources that count as an OBSERVATION rather than the tracker's
# own extrapolation. Mirrors ``tracker_core._motion.OBSERVED_SOURCES``
# — same tracks.json vocabulary seen from the consumer side; not
# imported from there because that name is private to the algorithm
# package.
OBSERVED_SOURCES = ("detect", "track")


def observed_samples(track) -> list[dict]:
    """Every observed (non-predicted) sample of ``track``, in order."""
    return [s for s in (track.samples or []) if s.get("source") in OBSERVED_SOURCES]


def detect_samples(samples) -> list[dict]:
    """The strictly detector-sourced subset of a sample list.

    Narrower than :func:`observed_samples`: ``"track"``-source samples
    are IoU continuations, not fresh detections, so the confirmation
    logic must not count them."""
    return [s for s in (samples or []) if s.get("source") == "detect"]


def confirmed_in_window(samples, n: int, secs: float) -> bool:
    """Sliding-window N-of-window confirmation check on detect samples.

    Mirrors what the live ``detection_confirmer`` would have decided:
    is there any anchor sample whose following ``secs`` seconds contain
    at least ``n`` detect samples in total (the anchor included)?
    """
    det = detect_samples(samples)
    for i, s in enumerate(det):
        t0 = float(s.get("t", 0))
        in_win = 1
        for j in range(i + 1, len(det)):
            if float(det[j].get("t", 0)) - t0 > secs:
                break
            in_win += 1
        if in_win >= n:
            return True
    return False


def bb_tuple(bb) -> tuple[int, int, int, int]:
    """Sample bbox dict → the ``(x1, y1, x2, y2)`` tuple bbox_utils wants."""
    return (int(bb["x1"]), int(bb["y1"]), int(bb["x2"]), int(bb["y2"]))


def bb_dims(bb) -> tuple[float, float]:
    """Sample bbox dict → ``(width, height)``."""
    return (bb["x2"] - bb["x1"], bb["y2"] - bb["y1"])
