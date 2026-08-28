"""Post-inference plausibility gates.

Everything here runs on model output that already cleared the
confidence threshold, and drops what the scene makes implausible. Kept
apart from the inference tiers because the two answer different
questions — "what did the model see" versus "which of those do we
believe" — and only the second one is tuned by the operator.

Every gate reports a machine-readable reason, which `_decision_log`
turns into the German one-liner an operator reads in `docker logs`. A
silent drop is the hardest kind of detection bug to chase.
"""

from __future__ import annotations

import numpy as np

from ._types import Detection

# Per-label minimum bounding-box constraints. Surveillance cameras at
# fixed positions almost never see a real person at <15% frame height
# or <2% frame area — a small "person" box is overwhelmingly a false
# positive (wood grain, shadow, distant silhouette). Keys are COCO
# labels; values are (min_height_frac, min_area_frac).
#
# Module-level, not private to the mixin, because the two LIVE paths do
# not reach the mixin at all: both the alarm loop and the Simulieren
# panel call ``detect_frame_raw``, which runs no label filters. The
# guard sat unreachable for months as a result. ``detect_setup``
# re-arms it for both by calling ``size_floor_reason`` directly.
LABEL_MIN_BBOX: dict[str, tuple[float, float]] = {
    "person": (0.15, 0.02),
}


def size_floor_reason(label: str, bbox, frame_w: int, frame_h: int) -> str | None:
    """Machine-readable drop reason when ``bbox`` is under the label's
    size floor, else ``None``.

    Fractions are measured against the frame the box is expressed in,
    so callers must pass the FULL frame dimensions for a box that has
    already been projected out of a tile.
    """
    min_h_frac, min_area_frac = LABEL_MIN_BBOX.get(label, (0.0, 0.0))
    if min_h_frac <= 0.0 and min_area_frac <= 0.0:
        return None
    h = float(max(1, frame_h))
    frame_area = float(max(1, frame_w * frame_h))
    x1, y1, x2, y2 = bbox
    bb_h = max(0, y2 - y1)
    bb_area = max(0, (x2 - x1) * (y2 - y1))
    if bb_h < min_h_frac * h:
        return f"size_floor (h_frac={bb_h / h:.2f} < {min_h_frac:.2f})"
    if bb_area < min_area_frac * frame_area:
        return f"size_floor (area_frac={bb_area / frame_area:.3f} < {min_area_frac:.3f})"
    return None


class LabelFilterMixin:
    """Per-label confidence and size gates applied after inference.

    Host contract: the class mixing this in must provide `min_score`,
    which the back-compat `_apply_label_filters` alias falls back to.
    """

    # Alias onto the module-level table so the mixin path and the two
    # live paths can never gate on different numbers.
    _LABEL_MIN_BBOX: dict[str, tuple[float, float]] = LABEL_MIN_BBOX

    def _apply_label_filters_with_reasons(
        self,
        dets: list[Detection],
        frame: np.ndarray,
        label_thresholds: dict[str, float] | None,
        global_threshold: float,
    ) -> tuple[list[Detection], list[tuple[Detection, str]]]:
        """Same gates as _apply_label_filters but also returns a parallel
        list of (detection, drop_reason) for the diagnostic logger. Hot
        path: the reason-string formatting only happens for dropped
        detections — the kept-list path is one append per kept det."""
        out: list[Detection] = []
        drops: list[tuple[Detection, str]] = []
        if not dets:
            return out, drops
        h, w = frame.shape[:2]
        for d in dets:
            # Per-label confidence override.
            if label_thresholds:
                t = label_thresholds.get(d.label)
                if t is not None and d.score < float(t):
                    drops.append((d, f"label_threshold({d.label})={t} (got {d.score:.2f})"))
                    continue
            # Per-label size floor (currently only "person") — same
            # function the live paths call via detect_setup.
            reason = size_floor_reason(d.label, d.bbox, w, h)
            if reason:
                drops.append((d, reason))
                continue
            out.append(d)
        return out, drops

    # Back-compat alias — anything that historically called
    # _apply_label_filters keeps the old single-return-value semantics.
    def _apply_label_filters(self, dets, frame, label_thresholds):
        kept, _ = self._apply_label_filters_with_reasons(
            dets,
            frame,
            label_thresholds,
            self.min_score,
        )
        return kept
