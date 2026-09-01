"""Wildlife second-stage classification, carved out of `_main_loop._loop`.

Catches fox / squirrel / hedgehog — none of which have a COCO class, so
the first-stage detector can never name them. Extracted because `_loop`
had grown to a single ~826-line method (CLAUDE.md budget: 80), and this
block is a self-contained concern with one input and one output.

The extraction also fixed the stage's central weakness: it used to hand
the classifier the **entire frame**. `WildlifeClassifier` wraps an
ImageNet MobileNet — a whole-image classifier that expects one dominant
subject. On a 2560x1440 feeder scene a squirrel occupies a few percent
of the pixels, and squeezing that into 224x224 dilutes it into the
background. The offline Coral test panel always cropped first
(`routes/coral.py`), which is why its accuracy never transferred to the
live path. See `_wildlife_crop`.
"""

from __future__ import annotations

import logging

from ..detectors import STAGE_WILDLIFE, Detection
from ._consts import _refine_wildlife_bbox, _suppress_overlap

log = logging.getLogger(__name__)

# COCO labels that mean "do not bother with the wildlife stage" — these
# animals genuinely look like themselves to COCO.
_HARD_SKIP_LABELS = ("bird", "dog", "person")

# A COCO "cat" at or above this score is taken at face value. Below it,
# the detection is a "soft cat" — COCO emits that a lot on frontal,
# upright squirrels — and the wildlife stage is allowed to overrule it.
_HARD_CAT_SCORE = 0.92

# Wildlife confidence needed to overrule a soft cat / to suppress
# overlapping COCO misreads on the same patch.
_OVERRULE_SOFT_CAT = 0.45
_SUPPRESS_OVERLAP = 0.55

# Padding applied around the motion box before classification. A tight
# motion box often clips ears, tail or head; a little context measurably
# helps a whole-image classifier without reintroducing the full-frame
# dilution problem.
_CROP_PAD_FRAC = 0.30

# Never crop below this many pixels per side — a 20px motion blob
# upscaled to 224x224 is mush, and the surrounding context is what makes
# the difference between "squirrel" and "leaf".
_CROP_MIN_PX = 96

# How much of a blocking detection must lie inside the crop before it
# counts as "in the way". A quarter is enough to matter, and low enough
# that a bird perched at the edge of the crop still blocks.
_SKIP_OVERLAP_FRAC = 0.25


class WildlifeStageMixin:
    def _wildlife_crop(self, frame, motion_bbox):
        """Return the region to classify: padded motion box, else the frame.

        `motion_bbox` is ``(x, y, w, h)`` as produced by the motion
        stage, or None when motion was not confirmed. Falling back to the
        whole frame preserves the previous behaviour for that case
        instead of inventing a guess.
        """
        h0, w0 = frame.shape[:2]
        if not motion_bbox:
            return frame, None
        try:
            mx, my, mw, mh = (int(v) for v in motion_bbox)
        except (TypeError, ValueError):
            return frame, None
        if mw <= 0 or mh <= 0:
            return frame, None

        pad_x = int(mw * _CROP_PAD_FRAC)
        pad_y = int(mh * _CROP_PAD_FRAC)
        x1 = mx - pad_x
        y1 = my - pad_y
        x2 = mx + mw + pad_x
        y2 = my + mh + pad_y

        # Grow a too-small box around its own centre before clamping, so
        # the subject keeps its position in the crop.
        if (x2 - x1) < _CROP_MIN_PX:
            cx = (x1 + x2) // 2
            x1, x2 = cx - _CROP_MIN_PX // 2, cx + _CROP_MIN_PX // 2
        if (y2 - y1) < _CROP_MIN_PX:
            cy = (y1 + y2) // 2
            y1, y2 = cy - _CROP_MIN_PX // 2, cy + _CROP_MIN_PX // 2

        x1 = max(0, min(x1, w0 - 1))
        y1 = max(0, min(y1, h0 - 1))
        x2 = max(x1 + 1, min(x2, w0))
        y2 = max(y1 + 1, min(y2, h0))

        crop = frame[y1:y2, x1:x2]
        if crop is None or crop.size == 0:
            return frame, None
        return crop, (x1, y1, x2, y2)

    @staticmethod
    def _covers(box, region, min_frac: float = _SKIP_OVERLAP_FRAC) -> bool:
        """True when `min_frac` of `box` lies inside `region`.

        Both are ``(x1, y1, x2, y2)``. Deliberately an asymmetric
        containment fraction rather than IoU: a small bird inside a large
        crop has a low IoU but is very much "in the way", and that is the
        case the caller cares about.
        """
        if not box or not region:
            return False
        ax1, ay1, ax2, ay2 = box
        bx1, by1, bx2, by2 = region
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        if ix2 <= ix1 or iy2 <= iy1:
            return False
        box_area = float(max(1, (ax2 - ax1) * (ay2 - ay1)))
        return ((ix2 - ix1) * (iy2 - iy1)) / box_area >= min_frac

    def _wildlife_gate_open(
        self, detections, *, motion_confirmed, wildlife_motion_only, crop_box=None
    ):
        """Whether the wildlife stage should run for this frame.

        `crop_box` is the region that would actually be classified. When
        given, a blocking label only blocks if it OVERLAPS that region.

        This matters at a feeder. The stage used to skip the whole frame
        whenever a bird was detected anywhere in it — but a bird at the
        feeder and a squirrel on the ground below is the normal case
        there, and the squirrel was being discarded because of a bird
        several hundred pixels away that the classifier would never have
        seen. The same reasoning applies to a person crossing the far
        side of the garden. Passing crop_box=None keeps the old
        frame-wide behaviour for callers that have no crop.
        """
        if not (motion_confirmed or wildlife_motion_only):
            return False
        if not self.wildlife_classifier.available:
            return False

        blockers = [d for d in detections if d.label in _HARD_SKIP_LABELS]
        hard_cats = [d for d in detections if d.label == "cat" and d.score >= _HARD_CAT_SCORE]
        if crop_box is None:
            return not blockers and not hard_cats
        return not any(
            self._covers(getattr(d, "bbox", None), crop_box) for d in blockers + hard_cats
        )

    def _apply_wildlife_stage(
        self,
        proc_frame,
        detections: list,
        labels: list,
        *,
        motion_confirmed: bool,
        wildlife_motion_only: bool,
        allowed,
        effective_bbox,
    ) -> tuple[list, list]:
        """Run the wildlife classifier and fold its verdict into the frame.

        Returns the (possibly rewritten) ``detections`` and ``labels``.
        Both are returned rather than mutated in place because the
        cat-vs-squirrel override REPLACES the lists.
        """
        # Crop first: the gate needs to know WHICH region would be
        # classified before it can decide whether a bird or a person is
        # actually in the way, or merely elsewhere in the frame.
        crop, crop_box = self._wildlife_crop(proc_frame, effective_bbox)
        if not self._wildlife_gate_open(
            detections,
            motion_confirmed=motion_confirmed,
            wildlife_motion_only=wildlife_motion_only,
            crop_box=crop_box,
        ):
            return detections, labels

        soft_cat = next(
            (d for d in detections if d.label == "cat" and d.score < _HARD_CAT_SCORE),
            None,
        )
        try:
            wl_min = self.cfg.get("wildlife_min_score") or None
            cat, raw_lbl, wscore = self.wildlife_classifier.classify_crop(crop, min_score=wl_min)
        except Exception:
            cat, raw_lbl, wscore = None, None, None
        if not cat or (allowed and cat not in allowed):
            return detections, labels

        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "[%s] wildlife: %s %.2f (crop=%s)",
                self.camera_id,
                cat,
                float(wscore or 0),
                "full frame" if crop_box is None else f"{crop.shape[1]}x{crop.shape[0]}",
            )

        h0, w0 = proc_frame.shape[:2]
        # Localise the animal: re-run COCO at a low threshold and pick the
        # bbox of any animal-shaped class (cat/dog/bear/sheep/cow). The
        # label is wrong but the geometry is right — we only borrow the
        # bbox. Falls back to the motion bbox, then the full frame.
        bb = _refine_wildlife_bbox(self.detector, proc_frame, effective_bbox, (w0, h0))
        wl_det = Detection(
            label=cat,
            score=float(wscore) if wscore is not None else 0.5,
            bbox=bb,
            species=raw_lbl,
            species_score=float(wscore) if wscore is not None else None,
            model=STAGE_WILDLIFE,
        )
        survivors = self._filter_masked_detections(proc_frame, [wl_det])
        survivors = self._filter_zoned_detections(proc_frame, survivors)
        if not survivors:
            return detections, labels

        score = float(wscore or 0)
        # Cat-vs-squirrel override: COCO often calls a frontal squirrel
        # "cat" with moderate confidence. If wildlife is sure enough,
        # drop the soft-cat detection and let squirrel win.
        if cat == "squirrel" and soft_cat is not None and score >= _OVERRULE_SOFT_CAT:
            log.info(
                "[%s] cat→squirrel override: cat %.2f replaced by wildlife squirrel %.2f",
                self.camera_id,
                soft_cat.score,
                score,
            )
            detections = [d for d in detections if d is not soft_cat]
            labels = [lbl for lbl in labels if lbl != "cat"]

        # Confident squirrel → suppress overlapping COCO false-positives
        # so the event isn't double-labelled. Once the wildlife model is
        # sure, COCO's misreads on the same patch are noise.
        if cat == "squirrel" and score >= _SUPPRESS_OVERLAP:
            drop = ("cat", "dog", "bear", "teddy bear")
            pre = len(detections)
            detections = _suppress_overlap(detections, bb, drop_labels=drop, iou_min=0.3)
            if len(detections) != pre:
                labels = [
                    lbl
                    for lbl in labels
                    if lbl not in drop or any(d.label == lbl for d in detections)
                ]

        detections.append(wl_det)
        labels.append(cat)
        return detections, labels
