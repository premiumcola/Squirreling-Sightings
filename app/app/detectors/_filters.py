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


class LabelFilterMixin:
    """Per-label confidence and size gates applied after inference.

    Self-contained: the gates read nothing off the host beyond what is
    passed in. The confidence floor the model already cleared is the
    caller's business — by the time a detection reaches these gates it
    has passed it, and re-checking it here was never anything the code
    did, only something its signature claimed.
    """

    # Per-label minimum bounding-box constraints. Surveillance cameras at
    # fixed positions almost never see a real person at <15% frame height
    # or <2% frame area — a small "person" box is overwhelmingly a false
    # positive (wood grain, shadow, distant silhouette). Keys are COCO
    # labels; values are (min_height_frac, min_area_frac).
    _LABEL_MIN_BBOX: dict[str, tuple[float, float]] = {
        "person": (0.15, 0.02),
    }

    def _apply_label_filters_with_reasons(
        self,
        dets: list[Detection],
        frame: np.ndarray,
        label_thresholds: dict[str, float] | None,
    ) -> tuple[list[Detection], list[tuple[Detection, str]]]:
        """Apply the gates, returning what survived plus a parallel list
        of (detection, drop_reason) for the diagnostic logger. Hot path:
        the reason-string formatting only happens for dropped detections
        — the kept-list path is one append per kept det."""
        out: list[Detection] = []
        drops: list[tuple[Detection, str]] = []
        if not dets:
            return out, drops
        h, w = frame.shape[:2]
        frame_area = float(max(1, h * w))
        for d in dets:
            # Per-label confidence override.
            if label_thresholds:
                t = label_thresholds.get(d.label)
                if t is not None and d.score < float(t):
                    drops.append((d, f"label_threshold({d.label})={t} (got {d.score:.2f})"))
                    continue
            # Per-label size floor (currently only "person").
            min_h_frac, min_area_frac = self._LABEL_MIN_BBOX.get(d.label, (0.0, 0.0))
            if min_h_frac > 0.0 or min_area_frac > 0.0:
                x1, y1, x2, y2 = d.bbox
                bb_h = max(0, y2 - y1)
                bb_area = max(0, (x2 - x1) * (y2 - y1))
                if bb_h < min_h_frac * h:
                    drops.append((d, f"size_floor (h_frac={bb_h / h:.2f} < {min_h_frac:.2f})"))
                    continue
                if bb_area < min_area_frac * frame_area:
                    drops.append(
                        (
                            d,
                            f"size_floor (area_frac={bb_area / frame_area:.3f} < {min_area_frac:.3f})",
                        )
                    )
                    continue
            out.append(d)
        return out, drops
