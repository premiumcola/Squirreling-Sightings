"""Per-label non-max suppression on raw detector output.

Sits at the entry of the association step so every later stage works
on a deduped detection stream.
"""

from __future__ import annotations

from ..bbox_utils import iou
from ._consts import NMS_IOU


def nms_per_label(dets, iou_threshold: float = NMS_IOU):
    """Per-label non-max suppression on raw detector output.

    Collapses the SSD's duplicate boxes on a single subject before
    track association runs — without this, every duplicate spawns
    its own track and the parallel copies coexist forever (the user-
    reported "4 boxes stacked on one person, dozens of lanes" symptom).

    Greedy, score-descending: within each label group, keep the
    highest-score bbox, then drop any subsequent bbox whose IoU
    against an already-kept box of the SAME label exceeds the
    threshold. Cross-label overlaps are NOT touched here — they're
    handled by the spawn-block gate in associate_detections so the
    SSD's occasional misclassification (e.g. "Vogel" on a person)
    can never seed a parallel cross-label track on the same subject.

    Returns a NEW list (caller's input is untouched) so the helper
    can sit pure at the entry of the live AND the post-clip path.
    """
    if not dets:
        return list(dets)
    by_label: dict[str, list] = {}
    for d in dets:
        by_label.setdefault(d.label, []).append(d)
    survivors: list = []
    for _lbl, group in by_label.items():
        group_sorted = sorted(group, key=lambda d: float(d.score), reverse=True)
        kept: list = []
        for d in group_sorted:
            if any(iou(d.bbox, k.bbox) > iou_threshold for k in kept):
                continue
            kept.append(d)
        survivors.extend(kept)
    return survivors
