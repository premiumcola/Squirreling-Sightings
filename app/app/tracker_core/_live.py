"""``LiveTracker`` — the per-camera convenience wrapper around
``TrackerState`` + ``associate_detections``.

Everything cadence-aware lives here: the live runtime ticks at whatever
rate the camera actually delivers, and the configured miss grace is
wall-clock, so the conversion has to happen per step rather than once
at construction.
"""

from __future__ import annotations

from collections.abc import Callable

from ._associate import associate_detections
from ._consts import (
    IOU_MATCH_THRESHOLD,
    LIVE_CLOSED_CAP,
    MISS_GRACE_DEFAULT_SECONDS,
    SPAWN_BLOCK_CONTAIN,
    TRACK_FLOOR_SCORE,
    TRACK_SPAWN_SCORE,
)
from ._helpers import compute_miss_grace_samples
from ._state import TrackerState


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
        "block_contain",
    )

    def __init__(
        self,
        camera_id: str,
        *,
        spawn_default: float = TRACK_SPAWN_SCORE,
        floor: float = TRACK_FLOOR_SCORE,
        grace_seconds: float = MISS_GRACE_DEFAULT_SECONDS,
        iou_threshold: float = IOU_MATCH_THRESHOLD,
        block_contain: float = SPAWN_BLOCK_CONTAIN,
    ):
        self.camera_id = camera_id
        # Bounded — this instance lives the whole camera session. The
        # post-clip worker's own TrackerState() (tracking_worker/_video.py)
        # deliberately leaves closed_cap unset.
        self.state = TrackerState(closed_cap=LIVE_CLOSED_CAP)
        self._frame_idx = 0
        self.spawn_default = float(spawn_default)
        self.floor = float(floor)
        self.grace_seconds = float(grace_seconds)
        self.iou_threshold = float(iou_threshold)
        self.block_contain = float(block_contain)

    def configure(
        self,
        *,
        spawn_default: float,
        floor: float,
        grace_seconds: float,
        iou_threshold: float | None = None,
        block_contain: float | None = None,
    ) -> None:
        """Replace the per-camera thresholds. Called on settings reload
        so a tweaked spawn / continue / grace / iou / containment value
        takes effect without rebuilding the runtime. ``iou_threshold``
        and ``block_contain`` keep whatever the instance already holds
        when omitted, so older callers that pass only the three legacy
        fields keep working."""
        self.spawn_default = float(spawn_default)
        self.floor = float(floor)
        self.grace_seconds = float(grace_seconds)
        if iou_threshold is not None:
            self.iou_threshold = float(iou_threshold)
        if block_contain is not None:
            self.block_contain = float(block_contain)

    def step_matches(
        self,
        detections,
        *,
        t_s: float,
        fps: float,
        spawn_for: Callable[[str], float] | None = None,
        frame_w: int = 0,
        frame_h: int = 0,
    ) -> list:
        """One tracker step, returning the ``(detection, track)`` pairs.

        ``step`` is this with the tracks dropped. The pairs exist for
        callers that need the track identity as well as the survivor —
        the Simulieren panel renders a stable ``#N`` badge per track and
        used to hand-roll its own ``associate_detections`` call to get
        them, which is how it ended up bumping ``_frame_idx`` by hand and
        computing the miss grace against the camera's CONFIGURED frame
        rate instead of the cadence its own ticks arrive on. Same entry
        point for both callers now; only the ``fps`` differs, which is
        the one thing that legitimately does.
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
            block_contain=self.block_contain,
            frame_w=frame_w,
            frame_h=frame_h,
        )
        # Stamp the association onto the detection so it survives the
        # rest of the frame's pipeline. `step()` drops the tracks one
        # line down and every stage after it (species, wildlife, re-id)
        # speaks detections only — so without this the identity the
        # tracker just computed is unreachable by the time an event is
        # built from those same objects. Costs one attribute write per
        # detection and changes nothing about what `step` returns.
        for det, track in matches:
            track_id = getattr(track, "track_id", None)
            if track_id is not None:
                det.track_id = track_id
        return matches

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
        matches = self.step_matches(
            detections,
            t_s=t_s,
            fps=fps,
            spawn_for=spawn_for,
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
