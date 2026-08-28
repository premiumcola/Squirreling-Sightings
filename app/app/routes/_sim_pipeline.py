"""The Simulieren panel's detection pass, run on production's setup.

Everything the panel does between "here is a frame" and "here are the
boxes with their verdicts" lives here. It is deliberately the SAME
sequence the alarm loop runs (``camera_runtime/_main_loop``), built from
the same :class:`~app.detect_setup.DetectionSetup`:

    bottom crop → detect_frame_raw(threshold=floor) → [tiling]
    → size floor → object_filter → exclusion masks → inclusion zones
    → tracker → spawn-threshold split

The panel differs from the loop in exactly one way, and it is the
panel's entire reason to exist: it KEEPS the boxes each gate removed and
labels them with the gate that removed them. A box that simply vanishes
is indistinguishable from a detector that missed it, which is how the
operator's 11-vertex exclusion mask could sit inert in the panel for
months without anyone being able to tell.

State that must NOT be shared with production lives here too — see
``get_test_tracker``.
"""

from __future__ import annotations

import collections
import logging
import time as _time
from dataclasses import dataclass, field

from ..detect_setup import (
    DetectionSetup,
    apply_object_filter,
    apply_size_floor,
    split_by_identity,
)
from ..tracker_core import LiveTracker
from ._sim_tiling import motion_bbox, prep_gray, tiled_detect

log = logging.getLogger(__name__)

# C3 · per-camera cached previous grayscale frame for the sim's Motion-ROI
# mode. SIM-LOCAL only — the production motion gate (camera_runtime/_motion)
# keeps its own state and is untouched. Keyed by cam_id; bounded by the
# small number of cameras.
_SIM_PREV_GRAY: dict[str, object] = {}

# SIMU-02e · per-camera tracker state for the test-detection endpoint.
_TEST_TRACKERS: dict[str, dict] = {}
# Idle threshold — drop tracker state after 5 min of no test-detection
# calls for this camera so a stale session doesn't keep stretching
# display numbers across a fresh user open.
_TEST_TRACKER_IDLE_S = 300.0

# SIMU-05h · cluster-evidence ring-buffer window.
EVIDENCE_WINDOW_S = 60.0

# Bounds on the measured tick cadence. The panel polls over HTTP at
# roughly 1 Hz; a single slow tick must not be allowed to claim 0.02 Hz
# and stretch the tracker's grace into minutes, nor a burst to claim
# 200 Hz and collapse it to nothing.
_TICK_FPS_MIN = 0.2
_TICK_FPS_MAX = 15.0
_TICK_FPS_ALPHA = 0.4

# German one-liners per gate. The verdict token is what the frontend
# styles on; the reason is what the operator reads.
VERDICT_PASS = "pass"
VERDICT_TENTATIVE = "tentative"
VERDICT_NO_TRACK = "no_track"
VERDICT_SIZE_FLOOR = "size_floor"
VERDICT_FILTERED = "filtered"
VERDICT_MASKED = "masked"
VERDICT_OUTSIDE_ZONE = "outside_zone"


@dataclass
class SimPass:
    """One tick's result: rows for the overlay plus the gate trace."""

    rows: list = field(default_factory=list)
    gate_lines: list = field(default_factory=list)
    raw_count: int = 0
    invokes: int = 1
    inference_ms: int = 0
    sahi_diag: dict = field(default_factory=dict)
    tick_fps: float = 1.0
    frame_w: int = 0
    frame_h: int = 0

    @property
    def pass_rows(self) -> list:
        return [r for r in self.rows if r["verdict"] == VERDICT_PASS]

    def count(self, verdict: str) -> int:
        return sum(1 for r in self.rows if r["verdict"] == verdict)


def get_test_tracker(cam_id: str, setup: DetectionSetup) -> dict:
    """The panel's OWN tracker for this camera, on production's config.

    Configuration is shared with the alarm pipeline (both resolve through
    ``DetectionSetup``); STATE is not, and must not be. A diagnostic view
    that stepped ``rt._tracker`` would inject its ~1 Hz ticks into the
    live association: real track ids would shift, real miss-grace windows
    would be consumed by sim frames, and the events the operator gets on
    Telegram would change because they opened a panel to look at them.
    Same numbers, different object — that is the whole rule.
    """
    now = _time.monotonic()
    entry = _TEST_TRACKERS.get(cam_id)
    if entry and (now - float(entry.get("last_call_ts", 0))) < _TEST_TRACKER_IDLE_S:
        tracker = entry["tracker"]
        # Pick up a settings change without dropping the display numbers.
        tracker.configure(
            spawn_default=setup.spawn_default,
            floor=setup.floor,
            grace_seconds=setup.grace_seconds,
            iou_threshold=setup.iou_threshold,
        )
        return entry
    entry = {
        "tracker": LiveTracker(
            cam_id,
            spawn_default=setup.spawn_default,
            floor=setup.floor,
            grace_seconds=setup.grace_seconds,
            iou_threshold=setup.iou_threshold,
        ),
        "display_nums": {},
        "track_labels": {},
        "dead_reported": set(),
        "next_num": 0,
        "last_call_ts": now,
        "last_tick_ts": 0.0,
        "tick_fps": 1.0,
        # SIMU-05h · ring-buffer of (wall_ts, kind, track_num, label,
        # score, iou, extra).
        "events": collections.deque(maxlen=1024),
        # Per-class (wall_ts, label, verdict) for the 60-s aggregate.
        "class_log": collections.deque(maxlen=2048),
        "drops_session": 0,
    }
    _TEST_TRACKERS[cam_id] = entry
    return entry


def trackers() -> dict:
    """The per-camera tracker-state map (debug-snapshot reads it)."""
    return _TEST_TRACKERS


def measure_tick_fps(entry: dict) -> float:
    """Cadence the panel's ticks ACTUALLY arrive at, as an EMA.

    The tracker's miss-grace is wall-clock seconds converted to a sample
    count, so it needs the rate of the samples it is fed. The panel used
    to hand it ``1000 / frame_interval_ms`` — the camera's configured
    rate, 6.7 Hz on Garten — while its own ticks arrived at about 1 Hz.
    An 8 s grace therefore became 53 samples ≈ 53 s: a subject that left
    the scene kept its box and its ``#N`` for the better part of a
    minute, and the panel's own shadow DEATH emitter (deleted with this
    change) disagreed with the tracker about when it had gone.
    """
    now = _time.monotonic()
    prev = float(entry.get("last_tick_ts") or 0.0)
    entry["last_tick_ts"] = now
    fps = float(entry.get("tick_fps") or 1.0)
    if prev > 0:
        dt = now - prev
        if dt > 0:
            observed = min(_TICK_FPS_MAX, max(_TICK_FPS_MIN, 1.0 / dt))
            fps = _TICK_FPS_ALPHA * observed + (1.0 - _TICK_FPS_ALPHA) * fps
    entry["tick_fps"] = fps
    return fps


def sim_motion_box(cam_id: str, frame):
    """Motion bbox for ``roi`` mode, from the panel's PREVIOUS tick.

    Best-effort and sim-local: production feeds ``roi`` from the D1
    coherent-blob tracker over consecutive ~150 ms frames, which no HTTP
    poll can reproduce. Reported as such in the trace.
    """
    try:
        gray_now = prep_gray(frame)
        h, w = frame.shape[:2]
        box = motion_bbox(_SIM_PREV_GRAY.get(cam_id), gray_now, float(w * h))
        _SIM_PREV_GRAY[cam_id] = gray_now
        return box
    except Exception:  # noqa: BLE001 — ROI is best-effort, never fatal
        return None


def detect(detector, frame, setup: DetectionSetup, det_mode: str, motion_box):
    """Full-frame pass at the tracker floor, plus tiles when a mode is on.

    Two parity fixes in one call: the threshold is the tracker's
    continuation floor (the panel used a hard-coded 0.20, identical only
    by coincidence at defaults), and the full-frame pass is handed to
    ``tiled_detect`` via ``full_dets=`` exactly as the production rescue
    does — so a 2×2 tick costs 1+4 inferences, not 1+1+4, and the number
    the panel reports is the number production would pay.
    """
    full = list(detector.detect_frame_raw(frame, threshold=setup.floor))
    if det_mode == "off":
        return full, {"mode": "off", "tiles": 0}, 1
    merged, diag = tiled_detect(
        detector,
        frame,
        det_mode,
        threshold=setup.floor,
        motion_box=motion_box,
        full_dets=full,
    )
    return merged, diag, 1 + int(diag.get("tiles") or 0)


def run_gates(rt, proc_frame, raw: list, setup: DetectionSetup):
    """Production's gate sequence, keeping what each gate removed.

    Order is the loop's order and the ordering itself is a fix: the panel
    used to run ``object_filter`` AFTER the tracker, as a display verdict
    only, so filtered boxes still entered the association and consumed
    track ids — the ``#N`` badges drifted against production's identities
    for boxes production never tracked.

    Masks and zones are the runtime's OWN methods, not a re-implementation
    here: ``self.cfg`` inside them is the config production runs, and the
    mask/zone raster caches they populate are the same ones the loop uses.
    """
    drops: list = []
    h_px, w_px = proc_frame.shape[:2]

    kept, size_drops = apply_size_floor(list(raw), w_px, h_px)
    for d, reason in size_drops:
        drops.append((d, VERDICT_SIZE_FLOOR, f"Größenfilter: {reason}"))

    kept, filter_drops = apply_object_filter(kept, setup.object_filter)
    for d, reason in filter_drops:
        drops.append((d, VERDICT_FILTERED, reason))

    before = kept
    kept = rt._filter_masked_detections(proc_frame, list(kept))
    for d, reason in split_by_identity(before, kept, "von einer Ausschluss-Maske abgedeckt"):
        drops.append((d, VERDICT_MASKED, reason))

    before = kept
    kept = rt._filter_zoned_detections(proc_frame, list(kept))
    for d, reason in split_by_identity(before, kept, "außerhalb jeder Erkennungszone"):
        drops.append((d, VERDICT_OUTSIDE_ZONE, reason))

    return kept, drops


def run_tracker(entry: dict, survivors: list, setup: DetectionSetup, w_px, h_px, tick_fps):
    """Step the panel's tracker and return (num_by_det, no_track, events).

    ``step_matches`` is the same entry point the alarm loop's ``step``
    wraps, so the panel no longer pokes ``_frame_idx`` by hand or builds
    its own ``compute_miss_grace_samples`` call.
    """
    tracker = entry["tracker"]
    display_nums = entry["display_nums"]
    track_labels = entry["track_labels"]
    wall_now = _time.time()
    events = entry["events"]
    try:
        matches = tracker.step_matches(
            survivors,
            t_s=_time.monotonic(),
            fps=tick_fps,
            spawn_for=setup.spawn_for,
            frame_w=int(w_px),
            frame_h=int(h_px),
        )
    except Exception as exc:  # noqa: BLE001 — a diagnostic must not 500
        log.warning("[test-detection] %s tracker step failed: %s", setup.camera_id, exc)
        matches = []

    num_by_det: dict[int, int] = {}
    for det, tr in matches:
        tid = tr.track_id
        num = display_nums.get(tid)
        is_new = num is None
        if is_new:
            entry["next_num"] = int(entry.get("next_num") or 0) + 1
            num = entry["next_num"]
            display_nums[tid] = num
        track_labels[tid] = getattr(det, "label", "") or track_labels.get(tid, "")
        num_by_det[id(det)] = num
        try:
            score_v = round(float(det.score), 4)
        except (TypeError, ValueError):
            score_v = 0.0
        events.append((wall_now, "spawn" if is_new else "cont", num, det.label, score_v, None, ""))
    # DEATH comes from the tracker's OWN state — a track that is no
    # longer active has been closed by the association step. The panel
    # used to run a second, independent emitter on a wall-clock grace,
    # which reported deaths the tracker had not performed.
    _emit_deaths(entry, events, wall_now)
    matched = {id(d) for d, _ in matches}
    no_track = [d for d in survivors if id(d) not in matched]
    return num_by_det, no_track


def _emit_deaths(entry: dict, events, wall_now: float) -> None:
    """One DEATH event per display-numbered track the tracker has closed."""
    tracker = entry["tracker"]
    active = {t.track_id for t in tracker.state.active}
    reported = entry["dead_reported"]
    for tid, num in list(entry["display_nums"].items()):
        if tid in active or tid in reported:
            continue
        reported.add(tid)
        events.append(
            (
                wall_now,
                "death",
                num,
                entry["track_labels"].get(tid, ""),
                None,
                None,
                "Track vom Tracker geschlossen",
            )
        )
    # Keep the two bookkeeping maps from growing across a long session:
    # once a track is both closed and reported, its display number can
    # never be handed out again.
    if len(reported) > 512:
        for tid in list(reported):
            if tid not in active:
                reported.discard(tid)
                entry["display_nums"].pop(tid, None)
                entry["track_labels"].pop(tid, None)


def build_rows(survivors, drops, num_by_det, no_track, setup: DetectionSetup) -> list:
    """Serialise every box — kept and dropped — with its verdict.

    The panel's job is to show the boxes production discards. The bug was
    never that it showed them; it was that it showed them labelled
    ``pass``. Every row now carries the gate that decided its fate.
    """
    no_track_ids = {id(d) for d in no_track}
    rows: list = []
    for d in survivors:
        spawn = setup.spawn_for(d.label)
        if id(d) in no_track_ids:
            verdict = VERDICT_NO_TRACK
            reason = "Tracker: kein Treffer — verworfen (tentativ, ohne Partner)"
        elif float(d.score) >= spawn:
            verdict = VERDICT_PASS
            reason = ""
        else:
            verdict = VERDICT_TENTATIVE
            reason = (
                f"hält den Track, zählt aber nicht zur Bestätigung "
                f"(unter Spawn-Schwelle {int(round(spawn * 100))} %)"
            )
        rows.append(_row(d, verdict, reason, num_by_det.get(id(d))))
    for d, verdict, reason in drops:
        rows.append(_row(d, verdict, reason, None))
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def _row(d, verdict: str, reason: str, track_num) -> dict:
    x1, y1, x2, y2 = d.bbox
    return {
        "label": d.label,
        "score": round(float(d.score), 4),
        "bbox": [int(x1), int(y1), int(max(0, x2 - x1)), int(max(0, y2 - y1))],
        "verdict": verdict,
        "reason": reason,
        "track_num": track_num,
    }
