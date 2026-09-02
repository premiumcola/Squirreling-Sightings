"""The per-frame association step: two-tier greedy IoU pairing, spawn,
adopt, re-id and age-out.

``associate_detections`` is the entry point; everything else in this
module is one phase of it. The phases, in the order they run:

* **Phase 1** — *confirmed* detections (score ≥ resolved-spawn) are
  matched to active tracks of the same label by descending IoU.
  Targets use the track's predicted bbox.
* **Phase 2** — *tentative* detections (score < resolved-spawn) may
  ONLY extend a still-unmatched active track via the same IoU rule.
* **Phase 2b** — both tiers get a second look against tracks that are
  too young to have a velocity estimate, matched on centroid distance
  instead of overlap (T1 · ``_motion.bootstrap_gate``). Always AFTER
  the overlap passes so a real overlap never loses to it.
* **Phase 3** — unmatched confirmed detections spawn-block, adopt by
  proximity, re-identify, or spawn a fresh track, in that order.
  Unmatched tentative detections are dropped entirely, so a flicker of
  low-confidence noise can never seed a new track id.
* **Age-out** — tracks with no hit this frame emit one ``predicted``
  sample and advance their miss counter; past the grace window they
  close. A short edge grace applies at the frame boundary.
* **Merge** — J3 folds sustained parallel duplicates into one id.

``associate_detections`` returns ``[(detection, track), …]`` for every
detection that matched OR spawned a track. The first element is the
**detection object**, never its index: NMS runs at the entry and
returns a new list regrouped by label, so a positional index is only
meaningful inside this module — callers hold the pre-NMS list and would
resolve such an index to a different detection entirely. See
``tests/test_tracker_nms_index.py``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field

from ..bbox_utils import iou
from ._adopt import nearby_track, spawn_blocking_track, try_reidentify
from ._consts import (
    EDGE_GRACE_SAMPLES,
    EDGE_MARGIN_PX,
    IOU_MATCH_THRESHOLD,
    NMS_IOU,
    SPAWN_BLOCK_CONTAIN,
    TRACK_MISS_WINDOWS,
    TRACK_SPAWN_SCORE,
)
from ._helpers import short_id
from ._merge import merge_active_duplicates
from ._motion import bootstrap_gate, bootstrap_match_score, predicted_bbox
from ._nms import nms_per_label
from ._state import TrackerState
from ._track import Track


def update_best_top(state: TrackerState, det, frame_idx: int, t_s: float) -> None:
    """Bump state.best_top when det.score beats the current best."""
    score = float(det.score)
    if state.best_top is None or score > state.best_top["score"]:
        state.best_top = {
            "f": frame_idx,
            "t": round(t_s, 3),
            "score": round(score, 4),
            "label": det.label,
        }


def _bbox_dict(det) -> dict:
    """The tracker's sample bbox shape, from a detection's tuple."""
    return {
        "x1": int(det.bbox[0]),
        "y1": int(det.bbox[1]),
        "x2": int(det.bbox[2]),
        "y2": int(det.bbox[3]),
    }


@dataclass
class _Frame:
    """Per-frame working set threaded through the phases.

    Holds only what more than one phase needs. ``predicted`` and
    ``gates`` are index-aligned with ``state.active`` AS IT WAS AT FRAME
    ENTRY — phase 3 appends to ``state.active``, so anything indexing
    into them must stay below ``len(predicted)``.
    """

    state: TrackerState
    frame_idx: int
    t_s: float
    frame_w: int
    frame_h: int
    predicted: list[tuple[int, int, int, int]]
    gates: list
    iou_threshold: float
    taken_tracks: set[int] = field(default_factory=set)
    matches: list[tuple[object, Track]] = field(default_factory=list)

    def iou_score(self, ti, d):
        """Overlap of the detection with the track's PREDICTED bbox,
        or None below the match threshold."""
        v = iou(self.predicted[ti], d.bbox)
        return v if v >= self.iou_threshold else None

    def gate_score(self, ti, d):
        """T1 · distance match for a track too young to have a
        velocity. None for every established track — those match on
        prediction overlap alone."""
        gate = self.gates[ti]
        return None if gate is None else bootstrap_match_score(gate, d.bbox)

    def pair_pass(self, pool, scorer):
        """Greedy best-first pairing for one tier; returns
        [(di, ti, strength), …] and the set of di's that matched.
        ``scorer`` returns a comparable strength in [0, 1] or None for
        "no match" — highest strength claims its track first."""
        candidates: list[tuple[int, int, float]] = []
        for di, d in pool:
            for ti, tr in enumerate(self.state.active):
                if not tr.active or tr.label != d.label or not tr.samples:
                    continue
                if ti in self.taken_tracks:
                    continue
                score_v = scorer(ti, d)
                if score_v is not None:
                    candidates.append((di, ti, score_v))
        candidates.sort(key=lambda p: p[2], reverse=True)
        taken_dets_local: set[int] = set()
        out = []
        for di, ti, strength in candidates:
            if di in taken_dets_local or ti in self.taken_tracks:
                continue
            taken_dets_local.add(di)
            self.taken_tracks.add(ti)
            out.append((di, ti, strength))
        return out, taken_dets_local

    def record_match(self, di_ti_pairs, pool_by_di, *, overlap: bool):
        """``overlap`` says whether the strength IS an IoU — the newborn
        distance gate produces a comparable number that is not one, and
        recording it as an overlap would misreport why a track lived."""
        for di, ti, strength in di_ti_pairs:
            d = pool_by_di[di]
            tr = self.state.active[ti]
            tr.last_iou = float(strength) if overlap else None
            tr.add_sample(
                self.frame_idx,
                self.t_s,
                _bbox_dict(d),
                float(d.score),
                "detect",
                d.label,
                getattr(d, "model", None),
            )
            self.state.samples_emitted += 1
            update_best_top(self.state, d, self.frame_idx, self.t_s)
            self.matches.append((d, tr))

    def attach(self, track, d) -> None:
        """Add a detect sample to an existing track outside the pairing
        passes (spawn-block, proximity adopt, re-id, fresh spawn)."""
        track.add_sample(
            self.frame_idx,
            self.t_s,
            _bbox_dict(d),
            float(d.score),
            "detect",
            d.label,
            getattr(d, "model", None),
        )
        self.state.samples_emitted += 1
        update_best_top(self.state, d, self.frame_idx, self.t_s)
        self.matches.append((d, track))


def _pairing_phases(fr: _Frame, confirmed, tentative) -> set[int]:
    """Phases 1, 2 and 2b. Returns the set of confirmed di's that found
    a track, which is what phase 3 skips over."""
    confirmed_by_di = {di: d for di, d in confirmed}
    tentative_by_di = {di: d for di, d in tentative}

    pairs1, taken_confirmed = fr.pair_pass(confirmed, fr.iou_score)
    fr.record_match(pairs1, confirmed_by_di, overlap=True)

    pairs2, taken_tentative = fr.pair_pass(tentative, fr.iou_score)
    fr.record_match(pairs2, tentative_by_di, overlap=True)

    # Phase 2b (T1) — for newborn tracks the prediction can't help yet:
    # with one observed sample there is no velocity, so a subject that
    # outran its own bbox since spawning has IoU 0 against it.
    pairs3, taken3 = fr.pair_pass(
        [(di, d) for di, d in confirmed if di not in taken_confirmed], fr.gate_score
    )
    fr.record_match(pairs3, confirmed_by_di, overlap=False)
    pairs4, _taken4 = fr.pair_pass(
        [(di, d) for di, d in tentative if di not in taken_tentative], fr.gate_score
    )
    fr.record_match(pairs4, tentative_by_di, overlap=False)
    return taken_confirmed | taken3


def _spawn_phase(fr: _Frame, confirmed, taken_confirmed: set[int], block_contain: float) -> None:
    """Phase 3 — every unmatched confirmed detection, in order:

    1. SPAWN-BLOCK (J2). Strong overlap with an active track's
       predicted or last-observed bbox (ANY label) means duplicate or
       misclassification of an already-tracked subject: attach, don't
       spawn.
    2. PROXIMITY (J6). No overlap, but a same-label track with no
       detection of its own this frame sits within a bbox dimension —
       the subject moved further than the prediction expected.
    3. RE-ID against recently-closed same-label tracks ("person walked
       back in after grace expired").
    4. Fallback: spawn a fresh id.
    """
    state = fr.state
    for di, d in confirmed:
        if di in taken_confirmed:
            continue
        blocker = spawn_blocking_track(state.active, fr.predicted, d, block_contain)
        if blocker is None:
            # J6 · only tracks that existed at frame entry are
            # candidates, so `predicted` stays index-aligned and a
            # track spawned earlier in this very loop can't adopt the
            # next detection of the same frame.
            blocker = nearby_track(
                state.active[: len(fr.predicted)], fr.predicted, d, fr.taken_tracks
            )
        if blocker is not None:
            # J5 · attach the det to the blocker REGARDLESS of label.
            # The per-sample label is preserved on the new sample and
            # the track's dominant label re-votes inside add_sample; a
            # single off-label frame (the SSD's occasional "Vogel" on a
            # person) gets absorbed into the same track and the majority
            # "person" wins, so no parallel cross-label ghost ever
            # materialises.
            fr.attach(blocker, d)
            blocker.missed_windows = 0
            with contextlib.suppress(ValueError):
                fr.taken_tracks.add(state.active.index(blocker))
            continue
        revived = try_reidentify(state, d, fr.t_s)
        if revived is not None:
            with contextlib.suppress(ValueError):
                state.closed.remove(revived)
            revived.active = True
            revived.end_reason = None
            revived.missed_windows = 0
            fr.attach(revived, d)
            state.active.append(revived)
            continue
        tr = Track(short_id(), d.label, fr.frame_idx)
        fr.attach(tr, d)
        state.active.append(tr)


def _at_frame_edge(bb, frame_w: int, frame_h: int) -> bool:
    """K4 · is a bbox touching/exceeding the frame edge?"""
    if frame_w <= 0 or frame_h <= 0:
        return False
    return (
        bb["x1"] <= EDGE_MARGIN_PX
        or bb["y1"] <= EDGE_MARGIN_PX
        or bb["x2"] >= frame_w - EDGE_MARGIN_PX
        or bb["y2"] >= frame_h - EDGE_MARGIN_PX
    )


def _age_out(fr: _Frame, original_count: int, grace: int) -> None:
    """Advance the miss counter of every track that got no hit this
    frame and close the ones past their grace window.

    Each miss also emits ONE ``source="predicted"`` sample at the
    already-computed predicted bbox — the IoU matcher already uses the
    prediction internally; this just stops hiding it from downstream
    consumers. The Mediathek swimlane renders these as the dashed tail
    of the track bar so the operator sees that tracking is still alive
    across short occlusions instead of a hard gap. Scoring is
    conservative: the last detect score scaled to 0.7 (floor 0.05).

    Restricted to indices < ``original_count`` so tracks spawned on this
    very frame skip the pass and get their first miss-check on the NEXT
    frame — without that they'd be docked a miss on their birth frame,
    halving the intended grace period.
    """
    state = fr.state
    for ti, tr in enumerate(state.active[:original_count]):
        if ti in fr.taken_tracks:
            continue
        # K4 · the predicted bbox is already clamped to frame bounds by
        # predicted_bbox, so a subject whose extrapolated position would
        # land off-frame is held at the visible boundary — for the
        # overlay AND for the IoU matcher that reads the same tuple.
        px1, py1, px2, py2 = fr.predicted[ti]
        last_detect_score = next(
            (
                s.get("score")
                for s in reversed(tr.samples)
                if s.get("source") == "detect" and s.get("score") is not None
            ),
            None,
        )
        pred_score = (
            max(0.05, float(last_detect_score) * 0.7) if last_detect_score is not None else 0.05
        )
        tr.add_sample(
            fr.frame_idx,
            fr.t_s,
            {"x1": px1, "y1": py1, "x2": px2, "y2": py2},
            pred_score,
            "predicted",
        )
        state.samples_emitted += 1
        tr.missed_windows += 1
        # K4 · short grace when the track's LAST OBSERVED bbox sits at
        # the frame edge. The subject most likely walked out of frame —
        # continuing to extrapolate "behind" the boundary for 8 s pins a
        # stale box on the video and floods the timeline with a long
        # predicted tail.
        last_detect_bb = next(
            (s["bbox"] for s in reversed(tr.samples) if s.get("source") in ("detect", "track")),
            None,
        )
        effective_grace = grace
        if last_detect_bb is not None and _at_frame_edge(last_detect_bb, fr.frame_w, fr.frame_h):
            effective_grace = min(grace, EDGE_GRACE_SAMPLES)
        if tr.missed_windows >= effective_grace:
            tr.close("timeout", fr.frame_w, fr.frame_h)


def _spawn_lookup(spawn_for, spawn_score: float) -> Callable[[str], float]:
    """Resolve a per-label spawn threshold. ``spawn_for`` may be absent
    or raise; ``spawn_score`` is the fallback in both cases."""
    if spawn_for is None:
        return lambda _lbl: float(spawn_score)

    def _resolve(lbl: str) -> float:
        try:
            v = spawn_for(lbl)
        except Exception:
            v = None
        return float(v) if v is not None else float(spawn_score)

    return _resolve


def associate_detections(
    state: TrackerState,
    dets,
    frame_idx: int,
    t_s: float,
    *,
    frame_w: int = 0,
    frame_h: int = 0,
    spawn_score: float = TRACK_SPAWN_SCORE,
    spawn_for: Callable[[str], float] | None = None,
    miss_grace_samples: int = TRACK_MISS_WINDOWS,
    iou_threshold: float = IOU_MATCH_THRESHOLD,
    block_contain: float = SPAWN_BLOCK_CONTAIN,
) -> list[tuple[object, Track]]:
    """Two-tier greedy IoU pairing + spawn + age-out for one frame.

    The phase order and the reasoning behind it are in this module's
    docstring. ``spawn_for`` is an optional ``label -> spawn_score``
    callable so callers with per-label thresholds (the live runtime's
    label_thresholds dict) classify each detection against ITS label's
    spawn floor; ``spawn_score`` is the fallback when it is None or
    returns None.

    Returns ``[(detection, track), …]`` — the live caller forwards those
    detections to the rest of the pipeline, the post-clip caller ignores
    the return value and queries state.closed at the end of the clip.
    """
    spawn_lookup = _spawn_lookup(spawn_for, spawn_score)
    # J1 · NMS at the entry so every later stage works on a deduped
    # detection stream. Caller's `dets` list is left untouched.
    dets = nms_per_label(dets, NMS_IOU)

    confirmed: list[tuple[int, object]] = []
    tentative: list[tuple[int, object]] = []
    for di, d in enumerate(dets):
        if float(d.score) >= spawn_lookup(d.label):
            confirmed.append((di, d))
        else:
            tentative.append((di, d))

    fr = _Frame(
        state=state,
        frame_idx=frame_idx,
        t_s=t_s,
        frame_w=frame_w,
        frame_h=frame_h,
        predicted=[
            predicted_bbox(tr, frame_idx, frame_w=frame_w, frame_h=frame_h) for tr in state.active
        ],
        # T1 · per-track velocity-bootstrap gate, computed once per
        # frame alongside the predictions. Non-None only for a track
        # that still has a single observed sample.
        gates=[bootstrap_gate(tr, frame_idx) for tr in state.active],
        iou_threshold=iou_threshold,
    )

    taken_confirmed = _pairing_phases(fr, confirmed, tentative)
    # Snapshot the pre-spawn track count so the age-out loop can skip
    # tracks created on this same frame.
    original_count = len(state.active)
    _spawn_phase(fr, confirmed, taken_confirmed, block_contain)
    _age_out(fr, original_count, max(1, int(miss_grace_samples)))

    state.close_tracks([t for t in state.active if not t.active])
    state.active = [t for t in state.active if t.active]
    # J3 · per-frame dedup pass — fold parallel duplicate active tracks
    # (sustained co-location over the last MERGE_SUSTAIN detect samples)
    # into one canonical id. Conservative gates (same-label + sustained
    # overlap) keep two crossing people safely separate. Runs AFTER
    # age-out so a track about to be closed by miss-grace doesn't get
    # re-merged on its way out.
    merge_active_duplicates(state)
    return fr.matches
