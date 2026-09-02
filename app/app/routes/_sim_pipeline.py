"""The Simulieren panel's detection pass, run on production's setup.

Everything the panel does between "here is a frame" and "here are the
boxes with their verdicts" lives here. It is deliberately the SAME
sequence the alarm loop runs (``camera_runtime/_main_loop``), built from
the same :class:`~app.detect_setup.DetectionSetup`:

    bottom crop → detect_frame_raw(threshold=floor) → [tiling]
    → object_filter → exclusion masks → inclusion zones
    → tracker → spawn-threshold split

There is deliberately no per-label size floor in that sequence, because
there is none in the loop either — see the note in ``detect_setup``.

The panel differs from the loop in exactly one way, and it is the
panel's entire reason to exist: it KEEPS the boxes each gate removed and
labels them with the gate that removed them. A box that simply vanishes
is indistinguishable from a detector that missed it, which is how the
operator's 11-vertex exclusion mask could sit inert in the panel for
months without anyone being able to tell.

State that must NOT be shared with production lives here too: the
tracker (``get_test_tracker``) and the compiled mask/zone rasters
(``_SIM_MASK_ZONES``). Both take production's numbers and keep their own
objects — a diagnostic that writes into the alarm loop's state is not a
diagnostic.
"""

from __future__ import annotations

import collections
import logging
import time as _time
from dataclasses import dataclass, field

from .. import mask_zones
from ..detect_setup import (
    DetectionSetup,
    apply_object_filter,
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

# Per-camera mask/zone raster cache, SIM-LOCAL for the same reason as the
# tracker below. The panel used to call ``rt._filter_masked_detections`` on
# the LIVE runtime, which rebuilds ``rt._mask_image`` / ``rt._zone_image``
# in place — and publishes the config signature before the raster it
# describes. A diagnostic tick landing in that window left the alarm loop
# reading "cache current" beside an unbuilt mask, i.e. the operator's
# exclusion mask switched off in production for as long as it took to fill
# in. Same polygons, own rasters.
_SIM_MASK_ZONES: dict[str, mask_zones.MaskZoneCache] = {}

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
VERDICT_FILTERED = "filtered"
VERDICT_MASKED = "masked"
VERDICT_OUTSIDE_ZONE = "outside_zone"


@dataclass
class SimPass:
    """One tick's result: rows for the overlay plus the gate trace."""

    rows: list = field(default_factory=list)
    gate_lines: list = field(default_factory=list)
    #: The full-frame pass exactly as the detector returned it, before
    #: any gate. In debug mode that reaches under the tracker floor.
    #: Reporting only — ``rows`` is what the pipeline acted on.
    full_scan: list = field(default_factory=list)
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
            block_contain=setup.block_contain,
        )
        return entry
    entry = {
        "tracker": LiveTracker(
            cam_id,
            spawn_default=setup.spawn_default,
            floor=setup.floor,
            grace_seconds=setup.grace_seconds,
            iou_threshold=setup.iou_threshold,
            block_contain=setup.block_contain,
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


def detect(
    detector,
    frame,
    setup: DetectionSetup,
    det_mode: str,
    motion_box,
    raw_threshold: float | None = None,
):
    """Full-frame pass at the tracker floor, plus tiles when a mode is on.

    Returns ``(merged, diag, invokes, full_scan)``. ``full_scan`` is the
    full-frame pass as the detector returned it; it reaches below the
    tracker floor only when ``raw_threshold`` asked it to — see the note
    at the score cut below.

    The parity fix here is the THRESHOLD: the panel used a hard-coded 0.20
    where the loop uses the tracker's continuation floor — identical only
    by coincidence at the shipped defaults.

    The cost, measured against a 2560×1440 frame with a counting stub
    detector, is ``1 + len(regions)`` invokes per tick:

        off  1   ·  2×2  5   ·  3×3  10   ·  roi  1–5

    ``roi`` varies because ``roi_regions`` splits the crop until it really
    magnifies: 1 for no motion box, 2 for a small blob, up to 5 for a blob
    spanning most of the frame.

    Passing the full-frame pass into ``tiled_detect`` via ``full_dets=``
    does NOT reduce that, and an earlier version of this docstring claimed
    it did ("1+4 rather than 1+1+4"). It never was 1+1+4: the previous sim
    called ``tiled_detect`` with no ``full_dets=`` and no separate
    full-frame pass of its own, so ``tiled_detect`` ran the one full pass
    internally — 1+4 then, 1+4 now, for every mode. The reuse buys the
    panel a full-frame detection list it can report against, nothing more.

    What this change DID make more expensive is the default. The panel
    used to default to ``off`` (1 invoke/tick, ~1 Hz over HTTP) and only
    tiled when the operator picked a mode from the switch; it now defaults
    to the camera's configured ``roi_mode``. On a camera left at the
    schema default of ``off`` nothing changes; on one configured to 3×3
    an open panel costs 10 invokes/tick on a TPU that has exactly one
    owner and three live cameras queueing behind it. That is what the
    admission gate in ``routes/_sim_guard`` prices, and why it must keep
    pricing the resolved mode rather than the requested one.
    """
    floor = float(setup.floor)
    # ``raw_threshold`` lowers the score cut on the ONE full-frame pass
    # this tick already pays for — pycoral applies it after inference, so
    # a lower cut adds boxes and can never remove one. Everything at or
    # above the floor is then exactly the list production would have
    # seen: the extra boxes are split off here and never reach the
    # gates, the tracker or ``merged``. Zero extra invokes, and the flag
    # cannot change what the pipeline decides. See ``routes/_sim_debug``.
    cut = floor if raw_threshold is None else min(floor, float(raw_threshold))
    scanned = list(detector.detect_frame_raw(frame, threshold=cut))
    full = [d for d in scanned if float(d.score) >= floor] if cut < floor else scanned
    # ``off`` still goes through tiled_detect: it returns the full ``_diag``
    # (raw / merged / tile_hits / magnification / crop_px), and a
    # hand-rolled ``{"mode": "off", "tiles": 0}`` silently dropped every
    # one of those keys from the Diagnose panel. With ``full_dets=`` the
    # call spends no inference of its own.
    merged, diag = tiled_detect(
        detector,
        frame,
        det_mode,
        threshold=floor,
        motion_box=motion_box,
        full_dets=full,
    )
    return merged, diag, 1 + int(diag.get("tiles") or 0), scanned


def sim_mask_zones(cam_id: str) -> mask_zones.MaskZoneCache:
    """The panel's OWN mask/zone raster cache for this camera."""
    cache = _SIM_MASK_ZONES.get(cam_id)
    if cache is None:
        cache = mask_zones.MaskZoneCache()
        _SIM_MASK_ZONES[cam_id] = cache
    return cache


def run_gates(cam_cfg: dict, proc_frame, raw: list, setup: DetectionSetup):
    """Production's gate sequence, keeping what each gate removed.

    Order is the loop's order and the ordering itself is a fix: the panel
    used to run ``object_filter`` AFTER the tracker, as a display verdict
    only, so filtered boxes still entered the association and consumed
    track ids — the ``#N`` badges drifted against production's identities
    for boxes production never tracked.

    Masks and zones run through :mod:`app.mask_zones`, the same functions
    the alarm loop's ``ZonesMixin`` calls, on the same polygons out of the
    same camera config — but against the panel's own compiled rasters. The
    previous version called the LIVE runtime's bound filter methods, which
    made this read-only view a writer of the alarm loop's cache; see
    ``_SIM_MASK_ZONES``.
    """
    drops: list = []
    cache = sim_mask_zones(setup.camera_id)
    cfg = cam_cfg or {}

    kept, filter_drops = apply_object_filter(list(raw), setup.object_filter, setup.excluded_classes)
    for d, reason in filter_drops:
        drops.append((d, VERDICT_FILTERED, reason))

    before = kept
    kept = cache.masked(list(kept), proc_frame, cfg.get("masks") or [], setup.camera_id)
    for d, reason in split_by_identity(before, kept, "von einer Ausschluss-Maske abgedeckt"):
        drops.append((d, VERDICT_MASKED, reason))

    before = kept
    kept = cache.zoned(list(kept), proc_frame, cfg.get("zones") or [], setup.camera_id)
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


def bbox_xywh(d) -> list:
    """``[x, y, w, h]`` in frame pixels — the one bbox shape every
    payload out of this panel uses, overlay rows and debug rows alike."""
    x1, y1, x2, y2 = d.bbox
    return [int(x1), int(y1), int(max(0, x2 - x1)), int(max(0, y2 - y1))]


def _row(d, verdict: str, reason: str, track_num) -> dict:
    return {
        "label": d.label,
        "score": round(float(d.score), 4),
        "bbox": bbox_xywh(d),
        "verdict": verdict,
        "reason": reason,
        "track_num": track_num,
    }
