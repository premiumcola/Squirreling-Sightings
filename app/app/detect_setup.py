"""One resolution of the detection configuration, for BOTH live paths.

The alarm pipeline (``camera_runtime/_main_loop``) and the Simulieren
panel (``routes/coral_test_detection``) used to resolve the same
settings independently, and drifted: the panel tiled on a URL query arg
while the camera ran ``roi_mode``, inferred at a hard-coded 0.20 while
the loop inferred at the tracker's continuation floor, never applied
``bottom_crop_px``, and treated ``detection_min_score`` as a hard
cutoff the live loop stopped using. Every one of those made the panel
answer a question about a pipeline that does not exist.

This module owns the resolution once. Both paths build a
:class:`DetectionSetup` from the camera config and read the numbers off
it; neither re-derives them. The gate helpers below are the same
functions on both paths too, so "the panel applies the mask" and "the
loop applies the mask" cannot mean two different things again.

What this module does NOT own: tracker STATE. The sim keeps its own
``LiveTracker`` instance — see ``routes/_sim_pipeline`` — because a
diagnostic view that mutated the live tracker would shift real track
ids and real grace windows and therefore real events. Configuration is
shared; state is not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .detection_tiling import normalise_mode
from .detectors._filters import size_floor_reason
from .tracker_core import resolve_track_thresholds

log = logging.getLogger(__name__)

# Default global confidence floor when neither the camera nor
# processing.detection.min_score says otherwise. Reported by both paths,
# applied as a live cutoff by NEITHER — see DetectionSetup.min_score.
DEFAULT_MIN_SCORE = 0.55


def make_spawn_for(label_thresholds: dict | None, spawn_default: float) -> Callable[[str], float]:
    """``label -> spawn floor`` closure used by the tracker and the
    confirmation gate.

    Both paths built this lambda themselves, with subtly different
    fallbacks (the loop fell back to the tracker's spawn_default, the
    sim to the same value via a dict ``get``). One owner so a per-label
    override can never mean two things.
    """
    if not label_thresholds:
        return lambda _lbl: float(spawn_default)
    table = {str(k): float(v) for k, v in dict(label_thresholds).items()}
    default = float(spawn_default)
    return lambda lbl: table.get(lbl, default)


@dataclass(frozen=True)
class DetectionSetup:
    """Everything both detection paths need, resolved once.

    Frozen: a gate that wants a different number has to say so at the
    call site rather than mutating the setup half-way down a frame.
    """

    camera_id: str
    det_mode: str
    bottom_crop_px: int
    object_filter: frozenset
    label_thresholds: dict
    spawn_default: float
    floor: float
    grace_seconds: float
    iou_threshold: float
    trigger_mode: str
    confirmation_window: dict
    # The GLOBAL confidence floor. Kept here so the panel can report it,
    # NOT so anything applies it: the two-tier tracker made
    # detection_min_score stop being the live cutoff (see
    # _main_loop's detect_frame_raw call). The sim used to apply it as a
    # hard reject, which is how a 0.52 person could read "REJECTED
    # (unter Schwelle 55 %)" in the panel and alert in production.
    min_score: float

    def spawn_for(self, label: str) -> float:
        """Per-label spawn floor — the tracker's promotion bar and the
        confirmation window's score gate."""
        return make_spawn_for(self.label_thresholds, self.spawn_default)(label)


def build_detection_setup(
    camera_id: str,
    cam_cfg: dict,
    *,
    roi_mode: str | None = None,
    global_cfg: dict | None = None,
) -> DetectionSetup:
    """Resolve the camera's detection configuration.

    ``roi_mode`` lets the live loop hand in the value its own
    warn-once cache already normalised (``_effective_roi_mode``) so the
    per-frame call doesn't re-log a typo several times a second. Left
    unset, the mode is normalised here.
    """
    cfg = cam_cfg or {}
    spawn, floor, grace, iou = resolve_track_thresholds(lambda _cid: cfg, camera_id)
    mode = normalise_mode(cfg.get("roi_mode")) if roi_mode is None else roi_mode
    min_score = float(cfg.get("detection_min_score") or 0.0)
    if min_score <= 0:
        proc = ((global_cfg or {}).get("processing") or {}).get("detection") or {}
        min_score = float(proc.get("min_score") or DEFAULT_MIN_SCORE)
    try:
        crop_px = int(cfg.get("bottom_crop_px", 0) or 0)
    except (TypeError, ValueError):
        crop_px = 0
    return DetectionSetup(
        camera_id=camera_id,
        det_mode=mode,
        bottom_crop_px=max(0, crop_px),
        object_filter=frozenset(cfg.get("object_filter") or ()),
        label_thresholds=dict(cfg.get("label_thresholds") or {}),
        spawn_default=float(spawn),
        floor=float(floor),
        grace_seconds=float(grace),
        iou_threshold=float(iou),
        trigger_mode=str(cfg.get("detection_trigger") or "motion_and_objects"),
        confirmation_window=dict(cfg.get("confirmation_window") or {}),
        min_score=min_score,
    )


# ── Gates shared by both paths ──────────────────────────────────────────
# Each returns ``(kept, dropped)`` where ``dropped`` is a list of
# ``(detection, german_reason)``. The live loop throws the reasons away;
# the panel renders them, which is the whole point — a box that simply
# vanishes is indistinguishable from a detector that missed it.


def apply_bottom_crop(frame, bottom_crop_px: int):
    """Strip the camera's configured bottom band before inference.

    The loop has always done this (corrupt H.264 bottom strip on the
    Reolinks); the panel never did, so detections inside the cropped-away
    band showed up only in the panel and every bbox y-coordinate was
    offset against production by the crop height.
    """
    if bottom_crop_px > 0 and frame is not None and frame.shape[0] > bottom_crop_px:
        return frame[:-bottom_crop_px, :, :]
    return frame


def apply_size_floor(
    dets: list, frame_w: int, frame_h: int, camera_id: str = ""
) -> tuple[list, list]:
    """Per-label bbox size floor — the ``_LABEL_MIN_BBOX`` guard.

    Written for the small-false-person case (wood grain, shadow, distant
    silhouette at twilight) and dead on both live paths for months: it
    lived inside ``CoralObjectDetector.detect_frame``, and neither the
    loop nor the panel calls that — both go through
    ``detect_frame_raw``. Hoisted here so it applies ONCE, to both.

    Fractions are measured against the FULL frame, so a tile-projected
    box is judged by the size it has in the scene, not in its crop.

    ``camera_id`` turns on the DEBUG trace. The panel renders its drops,
    the loop cannot — and a silent drop is the hardest kind of detection
    bug to chase, so the loop gets a line it can switch on.
    """
    kept: list = []
    dropped: list = []
    for d in dets:
        reason = size_floor_reason(d.label, d.bbox, frame_w, frame_h)
        if reason:
            dropped.append((d, reason))
        else:
            kept.append(d)
    if camera_id and dropped and log.isEnabledFor(logging.DEBUG):
        log.debug(
            "[det][cam:%s] Größenfilter verwarf %d Box(en): %s",
            camera_id,
            len(dropped),
            ", ".join(f"{d.label} {r}" for d, r in dropped),
        )
    return kept, dropped


def apply_object_filter(dets: list, allowed) -> tuple[list, list]:
    """Class allow-list. Empty set means "every class passes"."""
    if not allowed:
        return list(dets), []
    kept: list = []
    dropped: list = []
    for d in dets:
        if d.label in allowed:
            kept.append(d)
        else:
            dropped.append((d, f"Klasse '{d.label}' nicht im Objektfilter"))
    return kept, dropped


def split_by_identity(before: list, after: list, reason: str) -> list:
    """``(detection, reason)`` for everything in ``before`` that a gate
    removed on its way to ``after``.

    Keyed by ``id()``, not by index or equality: the mask/zone filters
    return the surviving objects unchanged, so identity is exact, while
    two detections of the same label and score are legitimately equal.
    """
    survived = {id(d) for d in after}
    return [(d, reason) for d in before if id(d) not in survived]
