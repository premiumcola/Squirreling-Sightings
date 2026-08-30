"""Per-camera resolution of the tracker's tunable thresholds.

Carved out of ``tracker_core/__init__.py`` (already far past the file
budget) when the containment gate became the fifth tunable axis. The
return type is a FROZEN DATACLASS, not a tuple: the four-tuple it used
to be is exactly why ``track_block_contain`` shipped inert — widening a
positional unpack means touching every call site, so the axis was wired
through the UI, the route and the state payload and then quietly
dropped on the floor. A named field is added here and read by name
there; a call site that forgets one keeps compiling but the axis test
in ``tests/test_netz_axis_reaches_runtime.py`` does not.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._consts import (
    IOU_MATCH_THRESHOLD,
    MISS_GRACE_DEFAULT_SECONDS,
    SPAWN_BLOCK_CONTAIN,
    TRACK_FLOOR_SCORE,
    TRACK_SPAWN_SCORE,
)


@dataclass(frozen=True)
class TrackThresholds:
    """One camera's resolved tracker knobs.

    Frozen for the same reason ``DetectionSetup`` is: a gate that wants a
    different number says so at the call site instead of mutating the
    resolution half-way down a frame.
    """

    spawn: float
    floor: float
    grace_seconds: float
    iou: float
    block_contain: float


def resolve_track_thresholds(
    cam_cfg_getter, camera_id, label: str | None = None
) -> TrackThresholds:
    """Pull the camera's spawn / continue / miss-grace / IoU / containment
    overrides.

    A camera that hasn't customised these fields (or has them set to
    0.0, the schema's "use module default" sentinel) falls back to the
    module-level defaults so an unconfigured install behaves identically
    to before the per-camera fields existed.

    Floor is clamped up to spawn — letting `floor > spawn` would
    allow tentative samples to spawn tracks, defeating the two-tier
    design. IoU is clamped to [0.0, 0.95] and containment to [0.0, 1.0]
    so a typo or extreme value can't break the matcher entirely.

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
    block_contain = SPAWN_BLOCK_CONTAIN
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
    try:
        b = float(cfg.get("track_block_contain") or 0.0)
        if b > 0.0:
            block_contain = min(1.0, b)
    except (TypeError, ValueError):
        pass
    clamp_against = spawn
    if label:
        from ..thresholds import resolve_effective
        from ..thresholds._apply import adapted_layer

        clamp_against = resolve_effective(cfg, None, label, adapted=adapted_layer(cfg, label)).spawn
    if floor > clamp_against:
        floor = clamp_against
    return TrackThresholds(
        spawn=spawn,
        floor=floor,
        grace_seconds=grace_s,
        iou=iou_t,
        block_contain=block_contain,
    )
