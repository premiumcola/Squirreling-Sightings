"""Bird-species classification while walking a stored clip.

WHAT THIS CLOSES
----------------
A replay used to answer "how many birds are in this clip" and stop
there. `_run.py` runs detector → tracker → clean → payload, and no
stage in that chain is the second-stage species classifier the live
loop runs at camera_runtime/_main_loop.py. A batch replay could
therefore prove a clip held two birds and still not name either of
them — which is the half of the operator's question that was missing.

NOT A SECOND CLASSIFIER PATH
----------------------------
The per-detection work is `detectors.stamp_species`, the very function
the live loop calls: same classifier object, same `classify_crop`
invocation, same four fields written, same STAGE_BIRD attribution. A
detection named by a replay is therefore shaped exactly like one named
at capture time. What lives here is only what a replay needs and a live
frame does not — a spend limit, and an accumulator that survives across
frames.

WHOLE-CLIP AGGREGATION IS THE POINT
-----------------------------------
The advantage a replay has over the event it re-examines is that it
sees the WHOLE clip, not the single frame
camera_runtime/_loop_stages.py:127 froze at recording start. That
advantage only survives if the species results survive: one frame's
crop is a blurred tail, the next one's is the same bird in profile.
`SpeciesTally` therefore keeps every classified crop and ranks the
distinct species by their best score, so a clip holding a Blaumeise
and an Amsel reports both, and one poor crop cannot outvote a good one.

Species are keyed by LATIN BINOMIAL, not by display name. The German
name is what the operator reads, but the binomial is what the model
actually decided and what the dossier and achievement subsystems key
on (see bird_species_rank.py). Two iNat labels that map to one German
name are one species and must not be counted as two.

WHERE IT DIFFERS FROM LIVE, DELIBERATELY
----------------------------------------
The live loop classifies AFTER the tracker has stepped, so it only
ever pays for detections that survived association. A replay cannot do
that: the tracker's verdict for a sampled frame is not available while
that frame's pixels are still in hand, and decoding the clip a second
time to classify only the survivors would cost more than the
classification it would save. So this classifies every bird box in
every sampled frame and bounds the total spend instead — see
`max_crops` and REPLAY_MAX_CROPS.

COST
----
Classification is the expensive half of the pass. The detector runs
once per sampled frame; this runs once per bird box within that frame,
against a 224×224 iNat classifier rather than one SSD pass. The tally
counts what it actually spent, so a report can say how much of a clip
was NAMED rather than merely decoded.
"""

from __future__ import annotations

from ..bird_species_backfill import crop_bbox
from ..detectors import BIRD_LABEL, stamp_species


def _bbox_dict(bbox) -> dict:
    """`Detection.bbox` is a 4-tuple; `crop_bbox` speaks the event
    JSON's x1/y1/x2/y2 dict. One conversion here rather than a second
    crop helper that speaks tuples."""
    try:
        x1, y1, x2, y2 = bbox
    except (TypeError, ValueError):
        return {}
    return {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}


class SpeciesTally:
    """Every species the second stage named anywhere in one clip.

    Counters are kept separately from results because they answer
    different questions: `result()` says WHAT was found, the counters
    say what it cost and whether the answer is complete.
    """

    def __init__(self, *, max_crops: int):
        self.max_crops = int(max_crops)
        #: Sampled frames on which at least one crop was classified.
        self.frames_classified = 0
        #: Classifier invocations actually spent. The budgeted number —
        #: a crop `crop_bbox` refused costs no inference and is not
        #: counted against it.
        self.crops_classified = 0
        #: Invocations that came back with a name. The gap between this
        #: and `crops_classified` is the classifier's own silence: below
        #: min_score, or a species with no German name.
        self.hits = 0
        #: True when the budget ran out before the clip did, so the
        #: species list is a floor rather than the whole answer.
        self.truncated = False
        self._by_key: dict[str, dict] = {}

    @property
    def exhausted(self) -> bool:
        return self.crops_classified >= self.max_crops

    def add(self, display: str, latin: str | None, score: float | None) -> None:
        """Fold one classified crop into the clip-level result."""
        key = (latin or display or "").strip()
        if not key:
            return
        value = float(score) if score is not None else 0.0
        row = self._by_key.get(key)
        if row is None:
            self._by_key[key] = {
                "species": display,
                "species_latin": latin,
                "best_score": round(value, 4),
                "frames": 1,
            }
            return
        row["frames"] += 1
        if value > row["best_score"]:
            row["best_score"] = round(value, 4)
            row["species"] = display
            row["species_latin"] = latin

    def result(self) -> list[dict]:
        """Distinct species, best-scoring first."""
        return sorted(
            self._by_key.values(),
            key=lambda r: (-r["best_score"], r["species"] or ""),
        )

    def names(self) -> list[str]:
        """Just the display names, in the same order."""
        return [r["species"] for r in self.result() if r["species"]]

    def stats(self) -> dict:
        return {
            "frames_classified": self.frames_classified,
            "crops_classified": self.crops_classified,
            "species_hits": self.hits,
            "classify_truncated": self.truncated,
        }


def make_sample_hook(classifier, tally: SpeciesTally):
    """Build the per-frame hook `sample_clip` calls with each decoded
    sample, or None when there is nothing to classify with.

    Returning None rather than a no-op closure is deliberate: it is what
    lets `sample_clip` skip the hook entirely on a detector-only run,
    and it keeps "the classifier is unavailable" a single check at the
    top of a replay instead of one per frame.
    """
    if classifier is None or not getattr(classifier, "available", False):
        return None

    def hook(frame, dets) -> None:
        classified_here = 0
        for det in dets:
            if det.label != BIRD_LABEL:
                continue
            if tally.exhausted:
                tally.truncated = True
                break
            crop = crop_bbox(frame, _bbox_dict(det.bbox))
            if crop is None:
                continue
            tally.crops_classified += 1
            classified_here += 1
            named = stamp_species(classifier, crop, det)
            if named:
                tally.hits += 1
                tally.add(*named)
        if classified_here:
            tally.frames_classified += 1

    return hook
