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
camera_runtime/_motion.py:446 froze at recording start. That advantage
only survives if the species results survive: one frame's crop is a
blurred tail, the next one's is the same bird in profile.
`SpeciesTally` therefore keeps every classified crop and ranks the
distinct species by their best score, so a clip holding a Blaumeise
and an Amsel reports both, and one poor crop cannot outvote a good one.

`SpeciesTally` itself now lives in `species_tally.py`, because the
live recording path aggregates the same way over the frames of a clip
it is recording (`camera_runtime/_clip_tally.py`) and the two answers
have to be the same answer. Imported and re-exported here so this
module stays the replay's one entry point for species work.

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
from ..species_tally import SpeciesTally

__all__ = ["SpeciesTally", "make_sample_hook"]


def _bbox_dict(bbox) -> dict:
    """`Detection.bbox` is a 4-tuple; `crop_bbox` speaks the event
    JSON's x1/y1/x2/y2 dict. One conversion here rather than a second
    crop helper that speaks tuples."""
    try:
        x1, y1, x2, y2 = bbox
    except (TypeError, ValueError):
        return {}
    return {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}


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
