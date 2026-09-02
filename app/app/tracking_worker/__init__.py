"""Background object-tracking worker.

Phase 1: after every motion clip is finalized, generate a `tracks.json`
sidecar next to the mp4. The sidecar carries per-frame bounding boxes
with stable track IDs so the lightbox can render boxes synced to video
playback (Phase 2).

Design:
- Single daemon thread, low priority. One queue.Queue() of jobs.
- Each job runs detection at ~1 Hz across the clip, associates detections
  to tracks via IoU (>0.3 threshold), and writes a sparse-sample JSON.
- The mp4 is NEVER modified — tracks.json is purely a subtitle-style
  sidecar. Re-indexing overwrites the JSON only.
- Per-frame CSRT tracking between detection samples is intentionally NOT
  implemented in Phase 1. opencv-python-headless 4.10 (the runtime image)
  doesn't ship the contrib tracking modules, and a 1 Hz sample rate plus
  client-side linear interpolation already gives smooth box motion in
  the lightbox without a dependency change. The schema reserves
  `source: "track"` so a future CSRT pass can fill in dense samples
  without breaking compatibility.

The tracking ALGORITHM is not here — it lives in :mod:`tracker_core`
and is shared bit-for-bit with the live camera_runtime path. This
package is the post-clip ORCHESTRATION around it, one concern per
module:

    _consts.py       tuning literals + the tracks.json schema history
    _job.py          TrackingJob + the sidecar path convention
    _samples.py      primitives over sample lists and sample bboxes
    _detect.py       object_filter resolution + one sample's detect pass
    _video.py        clip probing + the sampling loop (the only cv2 users)
    _stitch.py       K3 · offline tracklet stitching
    _static_fp.py    K1 · static-false-positive sweep
    _ghosts.py       L07 · ghost-track filter + threshold resolution
    _payload.py      tracks.json assembly + atomic write
    _achievement.py  tracks-derived aggregates merged into the event JSON

What stays in this file is the thread itself: the queue, the run loop,
the failure ring the UI polls, the lazily-built CPU-pinned detector,
and the orchestration that walks a job through the modules above.
"""

from __future__ import annotations

import collections
import contextlib
import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ..tracker_core import resolve_track_thresholds
from ._achievement import update_event_achievement
from ._clean import clean_tracks
from ._consts import RECENT_FAILURES_CAP, SLOW_JOB_RATIO, TRACKS_SCHEMA
from ._detect import resolve_object_filter
from ._job import TrackingJob, tracks_path_for
from ._payload import build_payload, write_payload_atomic
from ._video import open_video, precision_for, sample_clip

__all__ = [
    "TRACKS_SCHEMA",
    "TrackingJob",
    "TrackingWorker",
    "build_worker",
    "singleton",
    "tracks_path_for",
]

log = logging.getLogger(__name__)


class TrackingWorker(threading.Thread):
    """Single daemon thread that pulls TrackingJob items off a queue and
    writes tracks.json sidecars. Built once at boot via build_worker()
    in this module; access the singleton via `tracking_worker.singleton()`."""

    def __init__(
        self,
        *,
        storage_root: Path,
        detection_cfg_getter: Callable[[], dict] | None = None,
        cam_cfg_getter: Callable[[str], dict] | None = None,
    ):
        super().__init__(name="tracking-worker", daemon=True)
        self._q: queue.Queue[TrackingJob | None] = queue.Queue()
        self._stop = threading.Event()
        self._storage_root = Path(storage_root)
        self._cfg_getter = detection_cfg_getter or (lambda: {})
        # Per-camera live config lookup (typically settings.get_camera).
        # Used to pull each job's object_filter so the worker mirrors the
        # camera_runtime/_main_loop label filter exactly.
        self._cam_cfg_getter = cam_cfg_getter or (lambda _cam_id: {})
        self._detector = None  # built lazily on first job
        self._detector_cfg_id = None  # signature of cfg dict — rebuild on swap
        # Construction guard. Since the clip-replay endpoint borrows this
        # detector from a request thread, two threads can reach
        # _ensure_detector at once; without the lock both would load the
        # model and one instance would be silently discarded mid-use.
        self._detector_lock = threading.Lock()
        self._jobs_done = 0
        self._jobs_failed = 0
        # Bounded ring of recent per-event failures so the UI can tell
        # the user *why* a re-index didn't produce a fresh sidecar.
        # Keyed by event_id; oldest entries fall off when the cap is
        # exceeded.
        self._recent_failures: collections.OrderedDict[str, dict] = collections.OrderedDict()
        self._recent_failures_cap = RECENT_FAILURES_CAP
        self._failures_lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    def enqueue(self, job: TrackingJob):
        """Fire-and-forget — recording finalize must not block on tracking."""
        self._q.put(job)

    def stop(self, timeout: float = 5.0):
        """Drain the queue, give the active job a few seconds to finish."""
        self._stop.set()
        self._q.put(None)
        self.join(timeout=timeout)

    def stats(self) -> dict:
        now = time.time()
        with self._failures_lock:
            # Newest first — OrderedDict preserves insertion order so
            # reversed() is the freshest-to-oldest view.
            recent = [
                {
                    "event_id": eid,
                    "error": entry["error"],
                    "age_seconds": max(0, int(now - entry["ts"])),
                }
                for eid, entry in reversed(self._recent_failures.items())
            ]
        return {
            "queued": self._q.qsize(),
            "done": self._jobs_done,
            "failed": self._jobs_failed,
            "alive": self.is_alive(),
            "recent_failures": recent,
        }

    def _record_failure(self, event_id: str, error: str) -> None:
        """Push a per-event failure into the bounded recent-failures ring.
        Called from the run-loop's exception branch only; the lock keeps
        a concurrent stats() reader from observing a torn dict during
        the popitem/__setitem__ sequence."""
        with self._failures_lock:
            if event_id in self._recent_failures:
                # Re-insert to refresh recency ordering.
                self._recent_failures.pop(event_id)
            self._recent_failures[event_id] = {
                "error": error,
                "ts": time.time(),
            }
            while len(self._recent_failures) > self._recent_failures_cap:
                self._recent_failures.popitem(last=False)

    # ── Thread loop ──────────────────────────────────────────────────────

    def run(self):
        # Lower nice value so this thread doesn't compete with the camera
        # capture loops. Best-effort — Windows/macOS containers ignore
        # this silently which is fine.
        with contextlib.suppress(OSError, AttributeError):
            os.nice(10)
        log.info("[tracking] worker started")
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break  # stop sentinel
            try:
                self._run_one(job)
                self._jobs_done += 1
            except Exception as e:
                self._jobs_failed += 1
                self._record_failure(job.event_id, str(e) or e.__class__.__name__)
                log.error("[tracking] event=%s failed: %s", job.event_id, e, exc_info=True)
            finally:
                self._q.task_done()
        log.info(
            "[tracking] worker stopped (done=%d failed=%d)", self._jobs_done, self._jobs_failed
        )

    # ── Config access ────────────────────────────────────────────────────

    def _cam_cfg(self, camera_id: str) -> dict:
        """The camera's live config, or ``{}`` when the getter is absent
        or raises. Cheap dict read against the settings store."""
        try:
            return self._cam_cfg_getter(camera_id) if self._cam_cfg_getter else {}
        except Exception:
            return {}

    def _detection_cfg(self) -> dict:
        """The effective detection config, or ``{}`` when unavailable."""
        try:
            return self._cfg_getter() or {}
        except Exception:
            return {}

    # ── Detector lifecycle ───────────────────────────────────────────────

    def _ensure_detector(self):
        """Build the detector on first use; rebuild when the cfg dict
        contents change. Uses a content-derived signature rather than
        id() because export_effective_config returns a fresh dict each
        call — id() would force a model reload on every single job.

        The worker runs on CPU to avoid contending with the per-camera
        runtimes for the single Coral TPU device (one process can hold
        the TPU at a time). If TPU acquisition succeeded for the camera
        runtimes, the worker quietly falls back to tflite-runtime CPU
        inference and continues. ~1 Hz sampling on a 30-s clip stays
        well within the time budget on CPU."""
        cfg = self._detection_cfg()
        sig = self._detector_signature(cfg)
        with self._detector_lock:
            if self._detector is None or sig != self._detector_cfg_id:
                from ..detectors import CoralObjectDetector

                # Keep this worker off the TPU. Nulling `device` alone does
                # NOT do that any more: the EdgeTPU delegate (detectors tier
                # 1b) takes the default device when given no device option,
                # so with an `*_edgetpu.tflite` model_path this worker was
                # silently acquiring the TPU it is documented to avoid.
                # prefer_cpu skips both TPU tiers outright.
                worker_cfg = dict(cfg)
                worker_cfg["device"] = None
                worker_cfg["prefer_cpu"] = True
                self._detector = CoralObjectDetector(worker_cfg)
                self._detector_cfg_id = sig
            return self._detector

    def detector(self):
        """The worker's CPU-pinned detector, built on first use.

        Public because the clip-replay endpoint runs on a request
        thread and must NOT build a detector of its own: a second
        instance would either double the model memory or, worse, pick
        up the TPU that the live camera runtimes own. Borrowing this
        one inherits the prefer_cpu pinning above, and
        `CoralObjectDetector` serialises its own invokes on a per-
        instance lock, so a replay and a queued sidecar job interleave
        safely instead of corrupting each other's tensors.
        """
        return self._ensure_detector()

    @staticmethod
    def _detector_signature(cfg: dict) -> tuple:
        """Tuple of the cfg fields that materially affect detection
        output. Anything outside this list (e.g. region_filter_enabled
        on by default) is fine to ignore — a tweak there doesn't justify
        a model reload."""
        return (
            cfg.get("mode"),
            cfg.get("model_path"),
            cfg.get("cpu_model_path"),
            cfg.get("labels_path"),
            float(cfg.get("min_score") or 0.55),
        )

    # ── Per-job processing ───────────────────────────────────────────────

    def _run_one(self, job: TrackingJob):
        t_start = time.time()
        if not job.video_path.exists():
            log.warning("[tracking] event=%s video missing: %s", job.event_id, job.video_path)
            return

        cap, meta = open_video(
            job.video_path,
            precision=precision_for(self._cam_cfg_getter, job.camera_id),
        )
        if cap is None:
            log.warning(
                "[tracking] event=%s unreadable (fps=%.1f frames=%d)",
                job.event_id,
                meta.get("fps", 0.0),
                meta.get("frame_count", 0),
            )
            return

        try:
            detector = self._ensure_detector()
            allowed = resolve_object_filter(self._cam_cfg_getter, job.camera_id)
            thr = resolve_track_thresholds(self._cam_cfg_getter, job.camera_id)
            spawn_score = thr.spawn
            floor_score = thr.floor
            grace_s = thr.grace_seconds
            # The live runtime needs spawn=0.5 to suppress false-trigger
            # notifications. The post-clip worker only writes a
            # visualization sidecar — every detection above the raw
            # floor is worth recording so the user sees WHAT the model
            # found, even at moderate confidence. CPU-fallback on
            # main-stream 4K frames frequently sits in [0.20, 0.50]
            # for clearly-visible subjects (the model is shape-trained
            # for 320×320 inputs); the live spawn threshold would
            # discard those entirely and produce tracks=[] sidecars.
            # Detections are still tagged via score so the renderer
            # can paint sub-original-spawn samples as tentative.
            state = sample_clip(
                cap,
                meta,
                detector,
                allowed,
                floor_score=floor_score,
                spawn_score=floor_score,
                iou_threshold=thr.iou,
                block_contain=thr.block_contain,
            )
            cam_cfg = self._cam_cfg(job.camera_id)
            clean_tracks(
                state,
                camera_id=job.camera_id,
                cam_cfg=cam_cfg,
                spawn_score=spawn_score,
            )

            # gates.min_confidence reflects the LIVE spawn threshold so
            # the timeline panel's "<spawn>% Spuren bestätigt" copy
            # stays aligned with what the runtime would have notified
            # on. The worker's permissive effective spawn (== floor) is
            # an internal detail; surfacing it would make the gate
            # values misleading.
            payload = build_payload(
                state,
                meta["fps"],
                meta["frame_count"],
                meta["duration_s"],
                allowed,
                job.video_path,
                self._storage_root,
                spawn_score=spawn_score,
                floor_score=floor_score,
                grace_s=grace_s,
            )
            write_payload_atomic(tracks_path_for(job.video_path), payload)
            self._report_done(job, payload, state, time.time() - t_start, meta["duration_s"])
            self._merge_achievement(job, payload, cam_cfg)
        finally:
            cap.release()

    def _report_done(self, job: TrackingJob, payload: dict, state, elapsed: float, clip_s: float):
        """One INFO line per finished job, plus a WARN when processing
        took more than SLOW_JOB_RATIO of the clip duration AND was
        longer than 5 s in absolute terms."""
        best = payload["best_frame"]
        log.info(
            "[tracking] event=%s dur=%.1fs tracks=%d samples=%d %s",
            job.event_id,
            elapsed,
            len(payload["tracks"]),
            state.samples_emitted,
            f"best={best['score']:.2f}" if best else "best=—",
        )
        if clip_s > 0 and elapsed > clip_s * SLOW_JOB_RATIO and elapsed > 5.0:
            log.warning(
                "[tracking] event=%s SLOW: processing %.1fs for clip %.1fs",
                job.event_id,
                elapsed,
                clip_s,
            )

    def _merge_achievement(self, job: TrackingJob, payload: dict, cam_cfg: dict) -> None:
        """Update the event JSON with the achievement aggregates now that
        the tracks pass is complete. Best-effort — a missing event store
        or a failed write is logged but doesn't trash the tracks.json we
        just produced."""
        try:
            from .. import app_state
        except Exception:
            return
        store = getattr(app_state, "store", None)
        if store is None:
            return
        update_event_achievement(
            store,
            job.camera_id,
            job.event_id,
            payload.get("tracks", []) or [],
            cam_cfg,
        )


# ── Module-level singleton ───────────────────────────────────────────────
# Built and started by server.py's bootstrap; everything else reaches the
# worker through `singleton()` so the camera_runtime enqueue path doesn't
# need an explicit handle.
_worker: TrackingWorker | None = None
_worker_lock = threading.Lock()


def build_worker(
    *,
    storage_root: Path,
    detection_cfg_getter: Callable[[], dict] | None = None,
    cam_cfg_getter: Callable[[str], dict] | None = None,
) -> TrackingWorker:
    """Construct and start the singleton. Idempotent — second call
    returns the existing instance even if different getters are provided
    (both are captured on first build)."""
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return _worker
        _worker = TrackingWorker(
            storage_root=storage_root,
            detection_cfg_getter=detection_cfg_getter,
            cam_cfg_getter=cam_cfg_getter,
        )
        _worker.start()
        return _worker


def singleton() -> TrackingWorker | None:
    """Return the running worker if any. None until build_worker() runs."""
    return _worker
