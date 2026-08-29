"""J3 · fold parallel duplicate active tracks into one canonical id.

Two tracks that drift along the SAME subject are the visible symptom of
every association failure upstream: the operator sees two boxes and two
lanes where there is one animal. This pass is the last line of defence
— it merges two same-label active tracks once their recent observed
bboxes have sat on top of each other for ``MERGE_SUSTAIN`` samples in a
row.

Deliberately conservative, and deliberately narrow: the sustained gate
means it can only ever catch duplicates that are BOTH still receiving
detections. A duplicate whose original has stopped matching (the
fragmentation case) never qualifies — the dying track's observed tail
freezes at the moment it lost the subject while the new track's tail
moves on, so the pairwise comparison is between bboxes from different
moments. That case has to be prevented at association time; see
:mod:`._adopt`.
"""

from __future__ import annotations

from ..bbox_utils import iou
from ._consts import MERGE_IOU, MERGE_SUSTAIN
from ._motion import recent_observed_samples


def last_n_detect_bboxes(track, n: int):
    """Return up to the last ``n`` observed sample bboxes as
    (x1,y1,x2,y2) tuples in original order. Used by the merge pass
    to test SUSTAINED overlap between two active tracks."""
    out: list[tuple[int, int, int, int]] = []
    for s in recent_observed_samples(track, n):
        bb = s["bbox"]
        out.append((int(bb["x1"]), int(bb["y1"]), int(bb["x2"]), int(bb["y2"])))
    return out


def track_quality_score(track) -> float:
    """Heuristic ordering for "which track to KEEP when merging two
    duplicates". Higher score wins. Ranks on: number of detect
    samples first (longer history = canonical), then best_score
    (stronger evidence). Ties broken by first_frame (earlier id
    keeps the id the operator already learned)."""
    detect_n = sum(1 for s in (track.samples or []) if s.get("source") in ("detect", "track"))
    return detect_n * 100.0 + float(track.best_score or 0.0) * 10.0


def _absorb(winner, loser) -> None:
    """Fold ``loser``'s samples into ``winner`` and refresh the
    aggregates. Frame-deduplicated, so an overlapping frame keeps the
    winner's own bbox."""
    existing_frames = {s.get("f") for s in (winner.samples or [])}
    for s in loser.samples or []:
        if s.get("f") in existing_frames:
            continue
        winner.samples.append(s)
    winner.samples.sort(key=lambda s: int(s.get("f", 0)))
    winner.first_frame = min(winner.first_frame, loser.first_frame)
    winner.last_frame = max(winner.last_frame, loser.last_frame)
    for s in winner.samples or []:
        sc = s.get("score")
        if sc is not None and float(sc) > float(winner.best_score):
            winner.best_score = float(sc)
            winner.best_frame_idx = int(s.get("f", 0))
    loser.active = False
    loser.end_reason = "merged"


def merge_active_duplicates(state) -> None:
    """One-pass merge for parallel duplicate active tracks. Scans
    every (i, j) pair of active tracks; merges j into i when:
      * same label
      * both have at least MERGE_SUSTAIN detect samples
      * their last MERGE_SUSTAIN detect bboxes pairwise overlap
        above MERGE_IOU on EVERY pair (= "sustained co-location")

    The winner is picked via track_quality_score so the operator's
    canonical id (the one with more history) keeps living. The loser
    is absorbed (samples merged in chronological order then re-sorted
    by frame index) and moved to ``state.closed`` with end_reason
    ``"merged"`` so the post-clip diagnostics can audit the merge.

    Conservative-by-design — the sustained-overlap requirement
    avoids merging two genuinely distinct people who briefly cross
    paths.
    """
    active = state.active
    if len(active) < 2:
        return
    # Pre-compute tail bboxes once per track per pass.
    tails: dict[int, list] = {}
    for ti, tr in enumerate(active):
        tails[ti] = last_n_detect_bboxes(tr, MERGE_SUSTAIN)
    absorbed: set[int] = set()
    for i in range(len(active)):
        if i in absorbed:
            continue
        if len(tails[i]) < MERGE_SUSTAIN:
            continue
        for j in range(i + 1, len(active)):
            if j in absorbed:
                continue
            if active[i].label != active[j].label:
                continue
            if len(tails[j]) < MERGE_SUSTAIN:
                continue
            # Sustained pairwise overlap across the last MERGE_SUSTAIN
            # detect samples. Compare position-by-position (oldest to
            # newest) so two tracks that overlap NOW but didn't earlier
            # don't get merged on a single-frame coincidence.
            if any(iou(tails[i][k], tails[j][k]) < MERGE_IOU for k in range(MERGE_SUSTAIN)):
                continue
            # Pick the winner / loser.
            qi = track_quality_score(active[i])
            qj = track_quality_score(active[j])
            if qj > qi or (qj == qi and active[j].first_frame < active[i].first_frame):
                winner, loser = active[j], active[i]
                absorbed.add(i)
            else:
                winner, loser = active[i], active[j]
                absorbed.add(j)
            _absorb(winner, loser)
            # Refresh winner's tail cache so subsequent comparisons in
            # this same pass see the post-merge state. If the winner was
            # j, the outer loop skips i anyway — it is in `absorbed`.
            tails[active.index(winner)] = last_n_detect_bboxes(winner, MERGE_SUSTAIN)
    if not absorbed:
        return
    # Move absorbed tracks to closed.
    survivors = []
    for idx, tr in enumerate(active):
        if idx in absorbed:
            state.close_track(tr)
        else:
            survivors.append(tr)
    state.active = survivors
