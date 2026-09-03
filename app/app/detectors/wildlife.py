"""WildlifeClassifier — ImageNet MobileNetV2 second-stage classifier
for mammals the COCO detector cannot name (fox, squirrel, hedgehog).

Carved out of `_legacy_classes.py` during R02.3. With this commit the
legacy single-file home is gone — every detector class now lives in
its own module.

What is where:

* :mod:`._wildlife_rules` — label → category rules, both label spaces
* :mod:`._wildlife_load`  — the two three-tier model ladders
* :mod:`._wildlife_infer` — the tensor plumbing both interpreters share
* this file               — the decision: what the two models add up to
"""

from __future__ import annotations

import logging

import numpy as np

from ._timing import InferenceTimingMixin
from ._wildlife_infer import collect_floor, run_coral, run_tflite, top_k_labels
from ._wildlife_load import WILDLIFE_MIN_SCORE_DEFAULT, WildlifeLoadMixin
from ._wildlife_rules import (
    _inat_wildlife_category,
    _is_sciuridae_inat,
    _is_squirrel_likely,
    _wildlife_category,
)

log = logging.getLogger(__name__)

__all__ = ["WILDLIFE_MIN_SCORE_DEFAULT", "WildlifeClassifier"]


class WildlifeClassifier(WildlifeLoadMixin, InferenceTimingMixin):
    """ImageNet MobileNetV2 (1000 classes) second-stage classifier used for
    mammals the COCO detector cannot name — fox, squirrel, hedgehog.

    Same three-tier fallback as BirdSpeciesClassifier:
      1. pycoral + EdgeTPU  → mode="coral"
      2. tflite-runtime CPU → mode="cpu"
      3. disabled           → mode="none"

    classify_crop() returns (category, imagenet_label, score) where
    `category` is one of "fox" / "squirrel" / "hedgehog" or None when the
    top-1 doesn't map to any wildlife class we track.
    """

    def __init__(self, cfg: dict, inat_cfg: dict | None = None):
        self.cfg = dict(cfg or {})
        self.enabled = bool(self.cfg.get("enabled"))
        self.available = False
        self.reason = "disabled"
        self.mode = "none"  # "coral" | "cpu" | "none"
        self._resolve_paths()
        self._init_backend_fields(inat_cfg)
        if not self.enabled:
            return
        model_path = self.cfg.get("model_path")
        if not model_path:
            self.reason = "missing model_path"
            return
        if not self._model_file_reachable(model_path):
            return
        self._load_primary(model_path)

    def classify_crop(
        self, crop: np.ndarray, min_score: float | None = None
    ) -> tuple[str | None, str | None, float | None]:
        """Return (category, raw_label, score).

        category ∈ {"fox", "squirrel", "hedgehog", None}. None means
        neither MobileNet nor the iNat secondary classifier matched any
        wildlife rule we track. `raw_label` is the most informative
        diagnostic string (top-1 of MobileNet for misses; the matched
        rule's label for hits).

        Pipeline:
          1. Collect top-3 from MobileNet + (optionally) top-3 from iNat.
          2. Walk MobileNet top-3 → if any direct rule match, return it.
          3. Walk iNat top-3 → if any direct rule match, return it.
          4. Cross-validation: if MobileNet has a "squirrel-likely" label
             (hare / mongoose / mink / …) AND iNat has a Sciuridae genus,
             classify as squirrel with avg(score_a, score_b).
          5. Otherwise: no category, but return the MobileNet top-1 as a
             diagnostic label so the UI shows what the model "saw".
        """
        if not self.available or crop is None or crop.size == 0:
            return None, None, None
        # Per-camera min_score override — applied for the duration of the
        # call, restored in finally. Safe without locking because each
        # WildlifeClassifier instance is camera-scoped.
        saved_thresh = self.min_score
        if min_score is not None and float(min_score) > 0:
            self.min_score = float(min_score)
        try:
            top3_a = self._top3_mobilenet(crop)
            top3_b = self._top3_inat(crop) if self._inat_interpreter is not None else []
        finally:
            self.min_score = saved_thresh
        return self._decide(top3_a, top3_b)

    def _decide(self, top3_a, top3_b) -> tuple[str | None, str | None, float | None]:
        """Steps 2–5 of `classify_crop`, on the two collected top-3 lists.

        Split out so the decision ladder is readable without the
        threshold bookkeeping around it — and testable by handing it two
        lists instead of two interpreters.
        """
        # Step 2: direct MobileNet rule hit on any of top-3.
        for lbl, sc in top3_a:
            cat = _wildlife_category(lbl)
            if cat:
                return cat, lbl, sc
        # Step 3: direct iNat rule hit on any of top-3.
        for lbl, sc in top3_b:
            cat = _inat_wildlife_category(lbl)
            if cat:
                return cat, lbl, sc
        # Step 4: cross-validation. MobileNet contains a squirrel-likely
        # label AND iNat independently confirms with a Sciuridae genus →
        # classify as squirrel with the averaged confidence. The combined
        # raw_label keeps both pieces of evidence visible in the UI/logs.
        likely_a = next(((lbl, sc) for lbl, sc in top3_a if _is_squirrel_likely(lbl)), None)
        sciuridae_b = next(((lbl, sc) for lbl, sc in top3_b if _is_sciuridae_inat(lbl)), None)
        if likely_a and sciuridae_b:
            avg_score = (float(likely_a[1]) + float(sciuridae_b[1])) / 2.0
            combined = f"{likely_a[0]} + {sciuridae_b[0]}"
            log.debug(
                "[wildlife] cross-validated squirrel: mobilenet=%s (%.2f) iNat=%s (%.2f) → %.2f",
                likely_a[0],
                likely_a[1],
                sciuridae_b[0],
                sciuridae_b[1],
                avg_score,
            )
            return "squirrel", combined, avg_score
        # Step 5: nothing matched — return MobileNet's top-1 for UI
        # diagnostics provided it cleared half the threshold. Hides
        # totally junk noise.
        if top3_a:
            top_lbl, top_sc = top3_a[0]
            if top_sc >= self.min_score * 0.5:
                return None, top_lbl, top_sc
        return None, None, None

    def _top3_mobilenet(self, crop: np.ndarray) -> list[tuple[str, float]]:
        """Run MobileNet inference and return up to 3 (label, score) tuples
        sorted by descending score. The collected list always contains the
        top-3 above min_score * 0.5 — half-threshold so the cross-check in
        classify_crop has access to weaker evidence (a squirrel-likely
        label at 0.40 still triggers the cross-check if iNat strongly
        confirms with Sciurus vulgaris)."""
        floor = collect_floor(self.min_score)
        if not self._cpu_mode:
            named, marks = run_coral(
                self.common, self.classify, self.interpreter, crop, self.labels, floor=floor
            )
            self._record_timing(*marks)
            return named
        probs, marks = run_tflite(self.interpreter, crop)
        self._record_timing(*marks)
        # Detect the 1000/1001 background-class mismatch lazily, on the
        # first real output — the labels file alone cannot tell us.
        if self._label_offset == 0 and len(self.labels) == 1000 and probs.shape[0] == 1001:
            self._label_offset = 1
        return top_k_labels(probs, self.labels, floor=floor, label_offset=self._label_offset)

    def _top3_inat(self, crop: np.ndarray) -> list[tuple[str, float]]:
        """Return up to 3 (label, score) tuples from the iNat second-stage
        backend. Same shape as _top3_mobilenet so classify_crop can apply
        rules and the cross-check uniformly."""
        if self._inat_interpreter is None:
            return []
        floor = collect_floor(self._inat_min_score)
        if not self._inat_cpu_mode:
            named, marks = run_coral(
                self._inat_common,
                self._inat_classify,
                self._inat_interpreter,
                crop,
                self._inat_labels,
                floor=floor,
            )
            self._inat_timing._record_timing(*marks)
            return named
        probs, marks = run_tflite(self._inat_interpreter, crop)
        self._inat_timing._record_timing(*marks)
        return top_k_labels(probs, self._inat_labels, floor=floor)
