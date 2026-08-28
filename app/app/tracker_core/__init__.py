"""Pure two-tier object-tracking algorithm shared by the post-clip
worker AND the live camera-runtime path.

Carved out of ``tracking_worker.py`` so both callers reach the same
ByteTrack-style logic — confirmed detections spawn / extend tracks,
tentative (sub-spawn, above-floor) detections may only extend an
existing IoU-matched track. The motion model in :mod:`._motion`
predicts each track forward before the overlap test, so a subject
that moves further than its own bbox between samples still matches
itself; a miss-grace window keeps a track alive across short
occlusions.

Module scope is intentionally tight: NO file I/O, NO queue, NO event
store, NO Flask app state. Both callers wrap this module with their
own orchestration — see ``tracking_worker.TrackingWorker`` (post-clip)
and ``camera_runtime._main_loop`` (live).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from ..bbox_utils import bbox_centroid_dist, iou
from ._consts import (  # noqa: F401 — public API re-export
    BOOTSTRAP_DIST_FACTOR,
    BOOTSTRAP_MAX_ELAPSED,
    EDGE_GRACE_SAMPLES,
    EDGE_MARGIN_PX,
    IOU_MATCH_THRESHOLD,
    MERGE_IOU,
    MERGE_SUSTAIN,
    MISS_GRACE_DEFAULT_SECONDS,
    NMS_IOU,
    PRED_DECAY_CAP_SAMPLES,
    PRED_DECAY_FULL_SAMPLES,
    PRED_MAX_STEP_FRAC,
    PRED_MAX_TOTAL_FRAC,
    PRED_VELOCITY_WINDOW,
    REID_OCCUPIED_IOU,
    SAMPLE_BBOX_DELTA_PX,
    SPAWN_BLOCK_IOU,
    STATIONARY_SPEED_FRAC,
    TRACK_FLOOR_SCORE,
    TRACK_MISS_WINDOWS,
    TRACK_REID_DIST_FACTOR,
    TRACK_REID_MAX_SECONDS,
    TRACK_REID_SIZE_RATIO,
    TRACK_SPAWN_SCORE,
)
from ._adopt import nearby_track, spawn_blocking_track, try_reidentify
from ._merge import merge_active_duplicates
from ._motion import (  # noqa: F401 — public API re-export
    bootstrap_gate,
    bootstrap_match_score,
    predicted_bbox,
    recent_observed_samples,
    velocity_estimate,
)

log = logging.getLogger(__name__)


# ── ID + colour helpers ─────────────────────────────────────────────────────
def short_id() -> str:
    """6-hex-char id for a track. Stable across the clip but not globally
    unique — the (event_id, track_id) pair is what callers index on."""
    return uuid.uuid4().hex[:6]


def color_for_track(track_id: str) -> str:
    """Deterministic 6-char hex colour from the track id. The lightbox
    overlay uses this to keep each subject visually distinct without a
    server-side palette table. Picks from a hue-spread set of saturated
    colours so two adjacent tracks never collide."""
    palette = [
        "#22c55e",
        "#3b82f6",
        "#f59e0b",
        "#ef4444",
        "#a855f7",
        "#14b8a6",
        "#ec4899",
        "#84cc16",
        "#f97316",
        "#06b6d4",
        "#eab308",
        "#8b5cf6",
        "#10b981",
        "#f43f5e",
        "#0ea5e9",
    ]
    h = sum(ord(c) for c in track_id) % len(palette)
    return palette[h]


def classify_tier(score: float, spawn_score: float) -> str:
    """Map a detection score to ``"confirmed"`` (≥ spawn) or
    ``"tentative"`` (< spawn). Below-floor detections are expected to
    be filtered out by the caller BEFORE this function — we don't gate
    on the floor here because the live and post-clip floors are
    consumed at different points (post-clip: detect_frame_raw
    threshold; live: same)."""
    return "confirmed" if float(score) >= float(spawn_score) else "tentative"


def compute_miss_grace_samples(seconds: float, fps: float) -> int:
    """Translate a wall-clock grace period into a sample-count grace
    that ``associate_detections`` consumes. Same intent at every
    cadence — 4 s × 1 Hz = 4 samples, 4 s × 3 Hz = 12 samples. Returns
    ``TRACK_MISS_WINDOWS`` as a safe default when the inputs aren't
    usable (zero or negative)."""
    try:
        secs = float(seconds)
        rate = float(fps)
    except (TypeError, ValueError):
        return TRACK_MISS_WINDOWS
    if secs <= 0 or rate <= 0:
        return TRACK_MISS_WINDOWS
    return max(1, int(round(secs * rate)))


# ── Per-camera threshold resolver ───────────────────────────────────────────
def resolve_track_thresholds(
    cam_cfg_getter, camera_id, label: str | None = None
) -> tuple[float, float, float, float]:
    """Pull the camera's spawn / continue / miss-grace / IoU overrides.

    Returns ``(spawn_score, floor_score, miss_grace_seconds,
    iou_threshold)``. A camera that hasn't customised these fields
    (or has them set to 0.0, the schema's "use module default"
    sentinel) falls back to the module-level defaults so an
    unconfigured install behaves identically to before the per-camera
    fields existed.

    Floor is clamped up to spawn — letting `floor > spawn` would
    allow tentative samples to spawn tracks, defeating the two-tier
    design. IoU is clamped to [0.0, 0.95] so a typo or extreme value
    can't break the matcher entirely.

    P4 · when ``label`` is given, the floor is clamped against the
    PER-LABEL spawn from the ladder rather than against the camera-wide
    ``track_spawn_min_score``. Those two are different numbers, and the
    difference had teeth: a camera-wide 0.50 with ``bird`` at 0.45 let
    the floor sit above the label's own spawn, so a bird track could be
    continued at a score its own spawn would never have started. The
    import is function-local because ``thresholds._ladder`` reads
    ``tracker_core._consts`` — a module-level import here would close
    the cycle.
    """
    spawn = TRACK_SPAWN_SCORE
    floor = TRACK_FLOOR_SCORE
    grace_s = MISS_GRACE_DEFAULT_SECONDS
    iou_t = IOU_MATCH_THRESHOLD
    try:
        cfg = cam_cfg_getter(camera_id) or {}
    except Exception:
        cfg = {}
    try:
        s = float(cfg.get("track_spawn_min_score") or 0.0)
        if s > 0.0:
            spawn = s
    except (TypeError, ValueError):
        pass
    try:
        f = float(cfg.get("track_continue_min_score") or 0.0)
        if f > 0.0:
            floor = f
    except (TypeError, ValueError):
        pass
    try:
        g = float(cfg.get("track_miss_grace_seconds") or 0.0)
        if g > 0.0:
            grace_s = g
    except (TypeError, ValueError):
        pass
    try:
        i = float(cfg.get("track_iou_match_threshold") or 0.0)
        if i > 0.0:
            iou_t = max(0.0, min(0.95, i))
    except (TypeError, ValueError):
        pass
    clamp_against = spawn
    if label:
        from ..thresholds import resolve_effective
        from ..thresholds._apply import adapted_layer

        clamp_against = resolve_effective(cfg, None, label, adapted=adapted_layer(cfg, label)).spawn
    if floor > clamp_against:
        floor = clamp_against
    return spawn, floor, grace_s, iou_t


# ── Track + state ───────────────────────────────────────────────────────────
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

    def add_sample(
        self,
        frame_idx: int,
        t_s: float,
        bbox_dict: dict,
        score: float | None,
        source: str,
        label: str | None = None,
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
        # J5 · sliding-window majority vote on the dominant label.
        # Only DETECT samples vote (predicted ones inherit and would
        # feed back on themselves). Window of 5 lets the track
        # correctly relabel after a misclassified spawn-frame once
        # the truth wins majority, while a single off-label blip on
        # a long track never overturns the established label. Tie
        # breaks TOWARD the current label so a 1-frame flip can't
        # ever relabel: we only switch when strictly more frames
        # vote for the new label than for the current one.
        if source in ("detect", "track"):
            recent_labels: list[str] = []
            for s in reversed(self.samples):
                if s.get("source") not in ("detect", "track"):
                    continue
                recent_labels.append(s.get("label") or self.label)
                if len(recent_labels) >= 5:
                    break
            if recent_labels:
                counts: dict[str, int] = {}
                for lbl in recent_labels:
                    counts[lbl] = counts.get(lbl, 0) + 1
                max_count = max(counts.values())
                current_count = counts.get(self.label, 0)
                if max_count > current_count:
                    self.label = max(counts.items(), key=lambda kv: kv[1])[0]

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


@dataclass
class TrackerState:
    """Per-run mutable state shared across the per-frame helpers. The
    live runtime uses ONE instance per camera (lives the session); the
    post-clip worker creates ONE instance per clip."""

    active: list = field(default_factory=list)  # list[Track]
    closed: list = field(default_factory=list)  # list[Track]
    samples_emitted: int = 0
    best_top: dict | None = None


# ── Algorithm ───────────────────────────────────────────────────────────────
# The motion model (velocity estimate, bbox prediction, velocity
# bootstrap gate) lives in :mod:`._motion` and is imported above.


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
) -> list[tuple[object, Track]]:
    """Two-tier greedy IoU pairing + spawn + age-out for one frame.

    Rules:

    * Phase 1 — *confirmed* detections (score ≥ resolved-spawn) are
      matched to active tracks of the same label by descending IoU.
      Targets use the track's predicted bbox.
    * Phase 2 — *tentative* detections (score < resolved-spawn) may
      ONLY extend a still-unmatched active track via the same IoU
      rule.
    * Phase 2b — both tiers get a second look against tracks that are
      too young to have a velocity estimate, matched on centroid
      distance instead of overlap (T1 · ``_motion.bootstrap_gate``).
    * Phase 3 — unmatched confirmed detections spawn fresh tracks.
      Unmatched tentative detections are dropped entirely.

    ``spawn_for`` is an optional callable ``label -> spawn_score`` so
    callers with per-label thresholds (the live runtime's
    label_thresholds dict) classify each detection against ITS label's
    spawn floor instead of the global one. ``spawn_score`` is the
    fallback when ``spawn_for`` is None or returns None.

    Returns ``[(detection, track), …]`` for every detection that matched
    OR spawned a track. The live caller forwards those detections to the
    rest of the pipeline (confirmer + classifiers + event triggers). The
    post-clip caller ignores the return value (it queries state.closed at
    the end of the clip instead).

    The first element is the **detection object**, never its index. NMS
    runs at the entry of this function and returns a new list regrouped
    by label, so a positional index is only meaningful inside this
    function — callers hold the pre-NMS list and would resolve such an
    index to a different detection entirely.
    """
    spawn_lookup: Callable[[str], float]
    if spawn_for is None:
        spawn_lookup = lambda _lbl: float(spawn_score)
    else:

        def _resolve(lbl: str) -> float:
            try:
                v = spawn_for(lbl)
            except Exception:
                v = None
            return float(v) if v is not None else float(spawn_score)

        spawn_lookup = _resolve

    # J1 · NMS at the entry so every later stage works on a deduped
    # detection stream. Same-label boxes whose IoU exceeds NMS_IOU
    # collapse to the highest-score one — kills the SSD-internal
    # duplicate cluster that used to spawn parallel tracks on a
    # single subject. Caller's `dets` list is left untouched (helper
    # returns a new list).
    dets = nms_per_label(dets, NMS_IOU)

    confirmed: list[tuple[int, object]] = []
    tentative: list[tuple[int, object]] = []
    for di, d in enumerate(dets):
        if float(d.score) >= spawn_lookup(d.label):
            confirmed.append((di, d))
        else:
            tentative.append((di, d))

    predicted: list[tuple[int, int, int, int]] = [
        predicted_bbox(tr, frame_idx, frame_w=frame_w, frame_h=frame_h) for tr in state.active
    ]
    # T1 · per-track velocity-bootstrap gate, computed once per frame
    # alongside the predictions. Non-None only for a track that still
    # has a single observed sample — see ``_motion.bootstrap_gate``.
    gates = [bootstrap_gate(tr, frame_idx) for tr in state.active]
    taken_tracks: set[int] = set()
    # (detection object, track) — deliberately NOT (index, track): `di`
    # indexes the post-NMS list built above, and every caller holds the
    # pre-NMS list. Returning the object removes the whole class of
    # mismatch. See test_tracker_nms_index.py.
    matches: list[tuple[object, Track]] = []

    def _iou_score(ti, d):
        """Overlap of the detection with the track's PREDICTED bbox,
        or None below the match threshold."""
        v = iou(predicted[ti], d.bbox)
        return v if v >= iou_threshold else None

    def _gate_score(ti, d):
        """T1 · distance match for a track too young to have a
        velocity. None for every established track — those match on
        prediction overlap alone."""
        gate = gates[ti]
        return None if gate is None else bootstrap_match_score(gate, d.bbox)

    def _pair_pass(pool, scorer):
        """Greedy best-first pairing for one tier; returns
        [(di, ti), …] and the set of di's that matched. ``scorer``
        returns a comparable strength in [0, 1] or None for "no
        match" — highest strength claims its track first."""
        candidates: list[tuple[int, int, float]] = []
        for di, d in pool:
            for ti, tr in enumerate(state.active):
                if not tr.active or tr.label != d.label or not tr.samples:
                    continue
                if ti in taken_tracks:
                    continue
                score_v = scorer(ti, d)
                if score_v is not None:
                    candidates.append((di, ti, score_v))
        candidates.sort(key=lambda p: p[2], reverse=True)
        taken_dets_local: set[int] = set()
        out = []
        for di, ti, _iou_v in candidates:
            if di in taken_dets_local or ti in taken_tracks:
                continue
            taken_dets_local.add(di)
            taken_tracks.add(ti)
            out.append((di, ti))
        return out, taken_dets_local

    def _record_match(di_ti_pairs, pool_by_di):
        for di, ti in di_ti_pairs:
            d = pool_by_di[di]
            tr = state.active[ti]
            bbox_dict = {
                "x1": int(d.bbox[0]),
                "y1": int(d.bbox[1]),
                "x2": int(d.bbox[2]),
                "y2": int(d.bbox[3]),
            }
            tr.add_sample(frame_idx, t_s, bbox_dict, float(d.score), "detect", d.label)
            state.samples_emitted += 1
            update_best_top(state, d, frame_idx, t_s)
            matches.append((d, tr))

    # Phase 1 — confirmed dets fight for tracks first.
    confirmed_by_di = {di: d for di, d in confirmed}
    pairs1, taken_confirmed = _pair_pass(confirmed, _iou_score)
    _record_match(pairs1, confirmed_by_di)

    # Phase 2 — tentative dets extend whatever's still unmatched.
    tentative_by_di = {di: d for di, d in tentative}
    pairs2, taken_tentative = _pair_pass(tentative, _iou_score)
    _record_match(pairs2, tentative_by_di)

    # Phase 2b (T1) — same two tiers again, but for newborn tracks the
    # prediction can't help yet: with one observed sample there is no
    # velocity, so a subject that outran its own bbox since spawning
    # has IoU 0 against it. Distance-gated, one frame wide, and always
    # AFTER the overlap passes so a real overlap never loses to it.
    pairs3, taken3 = _pair_pass(
        [(di, d) for di, d in confirmed if di not in taken_confirmed], _gate_score
    )
    _record_match(pairs3, confirmed_by_di)
    taken_confirmed = taken_confirmed | taken3
    pairs4, _taken4 = _pair_pass(
        [(di, d) for di, d in tentative if di not in taken_tentative], _gate_score
    )
    _record_match(pairs4, tentative_by_di)

    # Snapshot the pre-spawn track count so the age-out loop below
    # can skip tracks that are about to be created on this same
    # frame. Without this, a freshly spawned track is not in
    # `taken_tracks` and immediately gets missed_windows += 1 on its
    # birth frame — halving the intended grace period.
    original_count = len(state.active)

    # Phase 3 — unmatched confirmed dets. The flow is:
    #
    #   1. SPAWN-BLOCK check (J2). If the det's bbox strongly
    #      overlaps an active track's predicted or last-observed
    #      bbox (any label, IoU > SPAWN_BLOCK_IOU), the det is either
    #      a same-label duplicate or a cross-label misclassification
    #      of an already-tracked subject. Either way it ATTACHES to
    #      that track and no fresh id spawns.
    #   2. PROXIMITY check (J6). No overlap, but a same-label track
    #      with no detection of its own this frame sits within a
    #      bbox dimension of the det — the subject moved further
    #      than the prediction expected (a direction reversal is the
    #      classic case). Attach rather than spawn beside it.
    #   3. RE-ID against recently-closed same-label tracks for
    #      "person walked back in after grace expired".
    #   4. Fallback: spawn a fresh id.
    #
    # Unmatched tentative dets are still dropped (no spawn) so a
    # flicker of low-conf noise can't seed a new track id.
    for di, d in confirmed:
        if di in taken_confirmed:
            continue
        bbox_dict = {
            "x1": int(d.bbox[0]),
            "y1": int(d.bbox[1]),
            "x2": int(d.bbox[2]),
            "y2": int(d.bbox[3]),
        }
        blocker = spawn_blocking_track(state.active, predicted, d)
        if blocker is None:
            # J6 · only tracks that existed at frame entry are
            # candidates, so `predicted` stays index-aligned and a
            # track spawned earlier in this very loop can't adopt the
            # next detection of the same frame.
            blocker = nearby_track(state.active[: len(predicted)], predicted, d, taken_tracks)
        if blocker is not None:
            # J5 · attach the det to the blocker REGARDLESS of label.
            # The per-sample label is preserved on the new sample and
            # the track's dominant label re-votes inside add_sample;
            # a single off-label frame (the SSD's occasional "Vogel"
            # on a person) gets absorbed into the same track and the
            # majority "person" wins, so no parallel cross-label
            # ghost ever materialises.
            blocker.add_sample(frame_idx, t_s, bbox_dict, float(d.score), "detect", d.label)
            blocker.missed_windows = 0
            state.samples_emitted += 1
            update_best_top(state, d, frame_idx, t_s)
            matches.append((d, blocker))
            try:
                ti = state.active.index(blocker)
                taken_tracks.add(ti)
            except ValueError:
                pass
            continue
        revived = try_reidentify(state, d, t_s)
        if revived is not None:
            with contextlib.suppress(ValueError):
                state.closed.remove(revived)
            revived.active = True
            revived.end_reason = None
            revived.missed_windows = 0
            revived.add_sample(frame_idx, t_s, bbox_dict, float(d.score), "detect", d.label)
            state.active.append(revived)
            state.samples_emitted += 1
            update_best_top(state, d, frame_idx, t_s)
            matches.append((d, revived))
            continue
        tid = short_id()
        tr = Track(tid, d.label, frame_idx)
        tr.add_sample(frame_idx, t_s, bbox_dict, float(d.score), "detect", d.label)
        state.active.append(tr)
        state.samples_emitted += 1
        update_best_top(state, d, frame_idx, t_s)
        matches.append((d, tr))

    # Age out tracks that didn't get a hit this window. After
    # ``miss_grace_samples`` misses they close. Restricted to indices
    # < original_count so newly-spawned tracks (appended above) skip
    # this pass and get their first miss-check on the NEXT frame.
    # Each miss also emits ONE ``source="predicted"`` sample at the
    # already-computed predicted bbox — the IoU matcher already uses
    # the prediction internally; this just stops hiding it from the
    # downstream consumers. The Mediathek swimlane renders these as
    # the dashed tail of the track bar so the operator sees that
    # tracking is still alive across short occlusions instead of a
    # hard gap. Scoring is conservative: the last detect score
    # scaled to 0.7 (floor 0.05) — a coarse "still tracking, lower
    # confidence" signal that doesn't invent fresh evidence.
    grace = max(1, int(miss_grace_samples))

    # K4 · helper — is a bbox touching/exceeding the frame edge?
    def _at_frame_edge(bb):
        if frame_w <= 0 or frame_h <= 0:
            return False
        return (
            bb["x1"] <= EDGE_MARGIN_PX
            or bb["y1"] <= EDGE_MARGIN_PX
            or bb["x2"] >= frame_w - EDGE_MARGIN_PX
            or bb["y2"] >= frame_h - EDGE_MARGIN_PX
        )

    for ti, tr in enumerate(state.active[:original_count]):
        if ti in taken_tracks:
            continue
        # K4 · the predicted bbox is already clamped to frame bounds
        # by predicted_bbox, so a subject whose extrapolated position
        # would land off-frame is held at the visible boundary — for
        # the overlay AND for the IoU matcher that reads the same
        # tuple.
        px1, py1, px2, py2 = predicted[ti]
        bbox_dict = {"x1": px1, "y1": py1, "x2": px2, "y2": py2}
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
        tr.add_sample(frame_idx, t_s, bbox_dict, pred_score, "predicted")
        state.samples_emitted += 1
        tr.missed_windows += 1
        # K4 · short grace when the track's LAST OBSERVED bbox sits
        # at the frame edge. The subject most likely walked out of
        # frame — continuing to extrapolate "behind" the boundary
        # for 8 s pins a stale box on the video and floods the
        # timeline with a long predicted tail. Cap effective grace
        # at EDGE_GRACE_SAMPLES so the track closes promptly.
        last_detect_bb = next(
            (s["bbox"] for s in reversed(tr.samples) if s.get("source") in ("detect", "track")),
            None,
        )
        effective_grace = grace
        if last_detect_bb is not None and _at_frame_edge(last_detect_bb):
            effective_grace = min(grace, EDGE_GRACE_SAMPLES)
        if tr.missed_windows >= effective_grace:
            tr.close("timeout", frame_w, frame_h)
    state.closed.extend([t for t in state.active if not t.active])
    state.active = [t for t in state.active if t.active]
    # J3 · per-frame dedup pass — fold parallel duplicate active
    # tracks (sustained co-location over the last MERGE_SUSTAIN
    # detect samples) into one canonical id. Conservative gates
    # (same-label + sustained overlap) keep two crossing people
    # safely separate. Runs AFTER age-out so a track about to be
    # closed by miss-grace doesn't get re-merged on its way out.
    merge_active_duplicates(state)
    return matches


# ── Live runtime convenience wrapper ────────────────────────────────────────
class LiveTracker:
    """Per-camera tracker — one instance per :class:`CameraRuntime`.

    Wraps a ``TrackerState`` plus the cadence-aware miss-grace logic so
    the live runtime's per-frame loop reads as a one-liner:
        survivors = self.tracker.step(detections, t_s=time.monotonic(),
                                      fps=self._main_fps,
                                      spawn_for=spawn_for_label)

    Returns the subset of input detections that should continue down
    the pipeline (every detection that either matched an existing
    track or spawned a fresh one). Tentative detections that found no
    IoU partner are dropped here — the second-stage classifiers
    (bird species / wildlife) and DetectionConfirmer see only the
    tracker's output.
    """

    __slots__ = (
        "camera_id",
        "state",
        "_frame_idx",
        "spawn_default",
        "floor",
        "grace_seconds",
        "iou_threshold",
    )

    def __init__(
        self,
        camera_id: str,
        *,
        spawn_default: float = TRACK_SPAWN_SCORE,
        floor: float = TRACK_FLOOR_SCORE,
        grace_seconds: float = MISS_GRACE_DEFAULT_SECONDS,
        iou_threshold: float = IOU_MATCH_THRESHOLD,
    ):
        self.camera_id = camera_id
        self.state = TrackerState()
        self._frame_idx = 0
        self.spawn_default = float(spawn_default)
        self.floor = float(floor)
        self.grace_seconds = float(grace_seconds)
        self.iou_threshold = float(iou_threshold)

    def configure(
        self,
        *,
        spawn_default: float,
        floor: float,
        grace_seconds: float,
        iou_threshold: float | None = None,
    ) -> None:
        """Replace the per-camera thresholds. Called on settings reload
        so a tweaked spawn / continue / grace / iou value takes effect
        without rebuilding the runtime. ``iou_threshold`` defaults to
        the module constant when omitted so older callers that pass
        only the three legacy fields keep working."""
        self.spawn_default = float(spawn_default)
        self.floor = float(floor)
        self.grace_seconds = float(grace_seconds)
        if iou_threshold is not None:
            self.iou_threshold = float(iou_threshold)

    def step(
        self,
        detections,
        *,
        t_s: float,
        fps: float,
        spawn_for: Callable[[str], float] | None = None,
        frame_w: int = 0,
        frame_h: int = 0,
    ) -> list:
        """Run one tracker step and return the surviving detections.

        ``fps`` is the camera's effective per-frame inference rate —
        the LiveTracker turns it into a sample-count grace via
        ``compute_miss_grace_samples`` so the configured
        ``grace_seconds`` (wall-clock) lands at the right sample count
        regardless of cadence.

        ``spawn_for`` defaults to a callable that returns this
        tracker's ``spawn_default`` for every label — pass a richer
        callable to honour the camera's label_thresholds dict.

        ``frame_w`` / ``frame_h`` are the frame dimensions. They are not
        cosmetic: without them the motion model's prediction clamp and
        the edge-grace rule both short-circuit, because 0 reads as
        "unknown". The live path used to omit them entirely, so both
        features were inert there while working fine in the post-clip
        worker, which does pass them.
        """
        self._frame_idx += 1
        grace = compute_miss_grace_samples(self.grace_seconds, fps)
        if spawn_for is None:
            spawn_for = lambda _lbl: self.spawn_default  # noqa: E731
        matches = associate_detections(
            self.state,
            list(detections),
            frame_idx=self._frame_idx,
            t_s=float(t_s),
            spawn_score=self.spawn_default,
            spawn_for=spawn_for,
            miss_grace_samples=grace,
            iou_threshold=self.iou_threshold,
            frame_w=frame_w,
            frame_h=frame_h,
        )
        # Unwrap the (detection, track) pairs so downstream pipeline
        # stages see a clean list of detections. Order follows the
        # tracker's match order, not the caller's input order — the two
        # differ because NMS regroups by label, and honouring the input
        # order was exactly the bug that handed classifiers the wrong
        # crop.
        return [d for d, _tr in matches]

    def active_count(self) -> int:
        return len(self.state.active)
