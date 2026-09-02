"""``Track`` — one subject's mutable state for the length of a run.

Lives in its own module because both the sample-squelch rule and the
sliding-window label vote are behaviour, not bookkeeping: they decide
what ends up in tracks.json and what the swimlane renders, and they
deserve to be readable without scrolling past the association loop.
"""

from __future__ import annotations

from ..bbox_utils import bbox_centroid_dist
from ._consts import SAMPLE_BBOX_DELTA_PX
from ._helpers import color_for_track


class Track:
    """Mutable track state held during one tracking run. Used by both
    the post-clip worker (a track lives the length of a clip, then
    gets serialised into tracks.json) and the live runtime (a track
    lives the camera's whole session, ages out via the miss-grace
    window when motion stops).

    The end-state diagnostic fields (``end_reason`` / ``last_*``) are
    sidecar-only — the live runtime doesn't write them anywhere. They
    stay on the class so the post-clip worker can call ``close()``
    and ``to_dict()`` without conditional branches."""

    __slots__ = (
        "track_id",
        "label",
        "color",
        "samples",
        "first_frame",
        "last_frame",
        "best_score",
        "best_frame_idx",
        "active",
        "missed_windows",
        "end_reason",
        "last_score",
        "last_bbox_w_px",
        "last_bbox_h_px",
        "last_bbox_frac_h",
        "last_bbox_frac_area",
        "model",
        "last_iou",
    )

    def __init__(self, track_id: str, label: str, frame_idx: int):
        self.track_id = track_id
        self.label = label
        self.color = color_for_track(track_id)
        self.samples: list[dict] = []
        self.first_frame = frame_idx
        self.last_frame = frame_idx
        self.best_score: float = 0.0
        self.best_frame_idx: int = frame_idx
        self.active = True
        self.missed_windows = 0
        # End-state diagnostics — populated by close() before
        # serialisation. None means "track never closed cleanly" and
        # the consumer should treat it as missing.
        self.end_reason: str | None = None
        self.last_score: float | None = None
        self.last_bbox_w_px: int | None = None
        self.last_bbox_h_px: int | None = None
        self.last_bbox_frac_h: float | None = None
        self.last_bbox_frac_area: float | None = None
        # Cascade stage that produced the most recent detect sample —
        # a ``detectors.STAGE_*`` constant, None until the first one.
        self.model: str | None = None
        # Overlap with the PREDICTED bbox that won this track its most
        # recent match. In-memory only — deliberately not in to_dict(),
        # which is the tracks.json contract. None means the last match
        # came from the newborn distance gate (no velocity to predict
        # from yet), which is a different answer from "0.0 overlap".
        self.last_iou: float | None = None

    def _revote_label(self) -> None:
        """J5 · sliding-window majority vote on the dominant label.

        Only DETECT samples vote (predicted ones inherit and would
        feed back on themselves). Window of 5 lets the track
        correctly relabel after a misclassified spawn-frame once
        the truth wins majority, while a single off-label blip on
        a long track never overturns the established label. Tie
        breaks TOWARD the current label so a 1-frame flip can't
        ever relabel: we only switch when strictly more frames
        vote for the new label than for the current one.
        """
        recent_labels: list[str] = []
        for s in reversed(self.samples):
            if s.get("source") not in ("detect", "track"):
                continue
            recent_labels.append(s.get("label") or self.label)
            if len(recent_labels) >= 5:
                break
        if not recent_labels:
            return
        counts: dict[str, int] = {}
        for lbl in recent_labels:
            counts[lbl] = counts.get(lbl, 0) + 1
        max_count = max(counts.values())
        current_count = counts.get(self.label, 0)
        if max_count > current_count:
            self.label = max(counts.items(), key=lambda kv: kv[1])[0]

    def add_sample(
        self,
        frame_idx: int,
        t_s: float,
        bbox_dict: dict,
        score: float | None,
        source: str,
        label: str | None = None,
        model: str | None = None,
    ):
        # Squelch micro-jitter samples — only emit when the bbox moved
        # by ≥ SAMPLE_BBOX_DELTA_PX pixels at the centroid OR this is a
        # detection sample (always kept so score history is preserved).
        # `predicted` samples are NEVER squelched — every miss-grace
        # tick should be visible in the bar so the swimlane's dashed
        # tail renders without gaps even when the predicted position
        # barely moved.
        if source == "track" and self.samples:
            last = self.samples[-1]["bbox"]
            if bbox_centroid_dist(last, bbox_dict) < SAMPLE_BBOX_DELTA_PX:
                return
        sample_label = label if label else self.label
        self.samples.append(
            {
                "f": frame_idx,
                "t": round(t_s, 3),
                "bbox": bbox_dict,
                "score": (round(float(score), 4) if score is not None else None),
                "source": source,
                "label": sample_label,
            }
        )
        self.last_frame = frame_idx
        if model and source == "detect":
            self.model = model
        if score is not None and score > self.best_score:
            self.best_score = float(score)
            self.best_frame_idx = frame_idx
        # Reset the miss counter ONLY on positive evidence — a real
        # `detect` or a `track`-source interpolation between detect
        # frames. `predicted` samples are emitted EXACTLY during the
        # miss-grace window; resetting on them would prevent the
        # track from ever timing out.
        if source != "predicted":
            self.missed_windows = 0
        if source in ("detect", "track"):
            self._revote_label()

    def close(self, reason: str, frame_w: int, frame_h: int) -> None:
        """Mark the track inactive and capture diagnostic fields from
        the LAST detect sample (falls back to last sample of any
        source when no detect samples exist — happens for tracks that
        only ever got `track`-source extrapolations). `reason` is one
        of "timeout" or "ended_at_clip" today; the worker's pipeline
        doesn't run per-track conf_drop / class_filter / bbox_too_small
        gates after the detector so those reasons aren't emitted from
        here.
        """
        self.active = False
        self.end_reason = reason
        last_detect = next(
            (s for s in reversed(self.samples) if s.get("source") == "detect"),
            None,
        )
        last = last_detect or (self.samples[-1] if self.samples else None)
        if not last:
            return
        if last.get("score") is not None:
            self.last_score = float(last["score"])
        bb = last.get("bbox") or {}
        try:
            bw = max(0, int(bb["x2"]) - int(bb["x1"]))
            bh = max(0, int(bb["y2"]) - int(bb["y1"]))
        except Exception:
            return
        self.last_bbox_w_px = bw
        self.last_bbox_h_px = bh
        if frame_h > 0:
            self.last_bbox_frac_h = round(bh / frame_h, 4)
        if frame_w > 0 and frame_h > 0:
            self.last_bbox_frac_area = round((bw * bh) / (frame_w * frame_h), 5)

    def to_dict(self) -> dict:
        d = {
            "track_id": self.track_id,
            "label": self.label,
            "color": self.color,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "best_score": round(self.best_score, 4),
            "best_frame": self.best_frame_idx,
            "model": self.model,
            "samples": self.samples,
        }
        if self.end_reason is not None:
            d["end_reason"] = self.end_reason
        if self.last_score is not None:
            d["last_score"] = round(self.last_score, 4)
        if self.last_bbox_w_px is not None and self.last_bbox_h_px is not None:
            d["last_bbox_size_px"] = [self.last_bbox_w_px, self.last_bbox_h_px]
        if self.last_bbox_frac_h is not None:
            d["last_bbox_frac_h"] = self.last_bbox_frac_h
        if self.last_bbox_frac_area is not None:
            d["last_bbox_frac_area"] = self.last_bbox_frac_area
        return d
