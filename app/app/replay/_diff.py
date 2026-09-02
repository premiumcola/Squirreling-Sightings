"""Pure comparison of two detection sets. No I/O, no config, no cv2.

This is the piece a future optimisation sweep leans on: run a clip N
times with N tunings, diff each result against the baseline, keep the
tuning whose diff reads best. Everything here is a pure function of its
arguments so that loop can run without a Flask app or a camera.

The matching is SPATIAL, not by label — that is the whole point. If the
two sets were matched by label first, an object whose class flipped
(bird -> squirrel) could only ever show up as one disappearance plus one
appearance, and "the tuning changed what this thing is called" is
exactly the finding an optimisation run is looking for. Matching by box
overlap first, then comparing labels within a matched pair, names it.
"""

from __future__ import annotations

from ._consts import MATCH_IOU_THRESHOLD, SCORE_EPSILON


def bbox_tuple(bbox) -> tuple[float, float, float, float] | None:
    """Normalise the three bbox spellings this codebase carries into one
    ``(x1, y1, x2, y2)`` tuple, or None when there is no usable box.

    ``Detection.to_dict`` serialises a dict, ``tracker_core`` samples
    carry the same dict, and the Coral test panel emits a plain list.
    A replay compares data from all three, so the reader accepts all
    three rather than making each call site remember which is which.
    """
    if bbox is None:
        return None
    if isinstance(bbox, dict):
        keys = ("x1", "y1", "x2", "y2")
        if not all(k in bbox for k in keys):
            return None
        try:
            return tuple(float(bbox[k]) for k in keys)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return tuple(float(v) for v in bbox)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def iou(a, b) -> float:
    """Intersection-over-union of two boxes. 0.0 when either box is
    missing or degenerate, so a box-less detection never matches by
    accident — it falls through to the label-only pass instead."""
    ba, bb = bbox_tuple(a), bbox_tuple(b)
    if ba is None or bb is None:
        return 0.0
    ax1, ay1, ax2, ay2 = ba
    bx1, by1, bx2, by2 = bb
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = ix2 - ix1, iy2 - iy1
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def normalise_detection(det: dict) -> dict:
    """One detection reduced to what a comparison can use: label, score,
    box. Anything unreadable becomes a safe default rather than raising —
    a replay must still produce a report when one archived event carries
    a malformed row."""
    if not isinstance(det, dict):
        return {"label": "?", "score": 0.0, "bbox": None}
    try:
        score = float(det.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "label": str(det.get("label") or "?"),
        "score": round(score, 4),
        "bbox": bbox_tuple(det.get("bbox")),
    }


def track_to_detection(track: dict) -> dict:
    """Collapse one track to the single detection that best represents
    it — its best-scoring frame.

    A track is a time series; a detection is a moment. Comparing an
    event's ``detections`` list against a replay's tracks needs both
    sides in the same shape, and the best frame is the one the rest of
    the app already treats as the track's representative (it is what
    the Telegram best-frame picker and the thumbnail both use).
    """
    if not isinstance(track, dict):
        return {"label": "?", "score": 0.0, "bbox": None}
    samples = track.get("samples") or []
    best_frame = track.get("best_frame")
    chosen = None
    for s in samples:
        if isinstance(s, dict) and s.get("f") == best_frame:
            chosen = s
            break
    if chosen is None and samples:
        # No sample carries the best frame index (a trimmed or hand-
        # edited sidecar). Fall back to the highest-scoring sample so
        # the track still contributes a box rather than dropping out.
        scored = [s for s in samples if isinstance(s, dict)]
        if scored:
            chosen = max(scored, key=lambda s: float(s.get("score") or 0.0))
    try:
        score = float(track.get("best_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "label": str(track.get("label") or "?"),
        "score": round(score, 4),
        "bbox": bbox_tuple((chosen or {}).get("bbox")),
    }


def _match_pairs(before: list[dict], after: list[dict], iou_threshold: float) -> dict[int, int]:
    """Greedy best-first pairing of before-index to after-index.

    Every candidate pair is scored once, sorted by overlap, and taken
    highest-first with each side used at most once. Greedy rather than
    Hungarian on purpose: the lists are a handful of objects, and a
    stable, explainable pairing matters more here than optimality —
    the operator has to be able to look at the diff and agree with it.

    Boxless pairs get a small non-zero score when their labels agree,
    so an archived event with no boxes still pairs up by label instead
    of reporting everything as appeared + disappeared.
    """
    candidates = []
    for i, b in enumerate(before):
        for j, a in enumerate(after):
            overlap = iou(b["bbox"], a["bbox"])
            if overlap >= iou_threshold:
                candidates.append((overlap, i, j))
            elif b["bbox"] is None or a["bbox"] is None:
                if b["label"] == a["label"]:
                    candidates.append((0.0, i, j))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    pairs: dict[int, int] = {}
    used_after: set[int] = set()
    for _overlap, i, j in candidates:
        if i in pairs or j in used_after:
            continue
        pairs[i] = j
        used_after.add(j)
    return pairs


def diff_detections(
    before,
    after,
    *,
    iou_threshold: float = MATCH_IOU_THRESHOLD,
    score_epsilon: float = SCORE_EPSILON,
) -> dict:
    """Compare two detection sets and say what changed.

    Returns five disjoint buckets plus a ``counts`` block. Every input
    detection lands in exactly one bucket, so ``counts`` always
    reconciles: appeared + class_changed + score_changed + unchanged ==
    len(after), and disappeared + the same three == len(before).

      * ``appeared``      — in the replay, not in the original
      * ``disappeared``   — in the original, gone from the replay
      * ``class_changed`` — same object, different label
      * ``score_changed`` — same object and label, confidence moved by
        more than ``score_epsilon``
      * ``unchanged``     — same object, same label, same confidence
    """
    norm_before = [normalise_detection(d) for d in (before or [])]
    norm_after = [normalise_detection(d) for d in (after or [])]
    pairs = _match_pairs(norm_before, norm_after, iou_threshold)

    appeared, disappeared = [], []
    class_changed, score_changed, unchanged = [], [], []

    for i, b in enumerate(norm_before):
        j = pairs.get(i)
        if j is None:
            disappeared.append(b)
            continue
        a = norm_after[j]
        if a["label"] != b["label"]:
            class_changed.append({"before": b, "after": a})
        elif abs(a["score"] - b["score"]) > score_epsilon:
            score_changed.append(
                {"before": b, "after": a, "delta": round(a["score"] - b["score"], 4)}
            )
        else:
            unchanged.append({"before": b, "after": a})

    matched_after = set(pairs.values())
    for j, a in enumerate(norm_after):
        if j not in matched_after:
            appeared.append(a)

    return {
        "appeared": appeared,
        "disappeared": disappeared,
        "class_changed": class_changed,
        "score_changed": score_changed,
        "unchanged": unchanged,
        "counts": {
            "before": len(norm_before),
            "after": len(norm_after),
            "appeared": len(appeared),
            "disappeared": len(disappeared),
            "class_changed": len(class_changed),
            "score_changed": len(score_changed),
            "unchanged": len(unchanged),
        },
    }
