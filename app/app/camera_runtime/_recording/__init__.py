from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ._ffmpeg_clip import FfmpegClipMixin
from ._opencv_fallback import OpenCVFallbackMixin
from ._preroll import MotionPrerollMixin
from ._provenance import ProvenanceMixin
from ._publish import PublishMixin
from .._consts import _FFMPEG_AVAILABLE, log


class RecordingMixin(
    PublishMixin, FfmpegClipMixin, OpenCVFallbackMixin, MotionPrerollMixin, ProvenanceMixin
):
    """Motion-clip lifecycle: ffmpeg start/stop + reencode + finalize + adhoc.

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (frame buffers, lock, config, etc.) which live on the concrete class.

    Both finalize paths — the ffmpeg re-encode that production takes
    (``FfmpegClipMixin``, in ``_ffmpeg_clip.py``), and the OpenCV
    frame-buffer fallback (``OpenCVFallbackMixin``, in
    ``_opencv_fallback.py``) — end in ``PublishMixin._publish_finalized_event``.
    They used to diverge, and every consequence of an event (alert,
    first-since, achievement, quest, dossier) lived only in the fallback.
    See _publish.py.

    ``MotionPrerollMixin`` (``_preroll.py``) is the pre-roll ring +
    splice step the ffmpeg path uses at finalize time; the shared
    snapshot/achievement helpers and the Telegram-menu adhoc clip stay
    here since neither finalize path owns them exclusively.
    """

    def _enqueue_tracks_for_clip(
        self, event_id: str, video_path: Path, snapshot_path: Path | None
    ) -> None:
        """Hand the freshly-finalized clip to the post-clip tracking worker so
        the next Mediathek open finds a populated <video>.tracks.json sidecar.

        Called from BOTH finalize paths (ffmpeg re-encode AND OpenCV
        fallback) so every recorded clip ships with a sidecar — the
        Lightbox's reindex banner is meant for genuinely missing/corrupt
        sidecars, not for every fresh recording.
        """
        if not video_path or not video_path.exists():
            return
        try:
            from ...tracking_worker import TrackingJob, singleton as _tw_singleton

            worker = _tw_singleton()
            if worker is None:
                return
            worker.enqueue(
                TrackingJob(
                    event_id=event_id,
                    video_path=video_path,
                    snapshot_path=snapshot_path,
                    camera_id=self.camera_id,
                )
            )
        except Exception as _te:
            log.debug("[%s] tracking enqueue failed: %s", self.camera_id, _te)

    def _build_recording_settings_snapshot(self) -> dict:
        """Capture the detection config active at clip-finalize time.

        Stored under event["recording_settings"] so the lightbox can
        replay "what config produced this clip" without having to
        guess at the camera's current state when the user reviews it
        weeks later. Pure read of self.cfg + tiny normalisation; no
        side effects.
        """
        cw_global = (self.cfg.get("confirmation_window") or {}).get("global") or {}
        obj_filter = self.cfg.get("object_filter") or []
        return {
            "conf_thresh_general": float(self.cfg.get("detection_min_score") or 0.0),
            "conf_thresh_per_class": dict(self.cfg.get("label_thresholds") or {}),
            # null when the filter is empty — distinguishes "no filter
            # configured" from "filter has zero allowed classes" on
            # the frontend without a sentinel value.
            "object_filter": list(obj_filter) if obj_filter else None,
            "confirm_n": int(cw_global.get("n", 3)),
            "confirm_seconds": int(cw_global.get("seconds", 5)),
            "sample_interval_ms": int(self.cfg.get("frame_interval_ms") or 350),
            # Raw 0..1 float (same units as the schema). The frontend
            # multiplies by 100 for display so the rest of the API
            # surface — settings.json, /api/cameras — keeps the same
            # representation it has used since the wizard shipped.
            "motion_pretrigger_sensitivity": float(self.cfg.get("motion_sensitivity") or 0.5),
            # Pre-roll window — a PROVISIONAL value, only correct for the
            # OpenCV-fallback path (_finalize_motion_clip, which reads this
            # snapshot directly): 3.0 s is what its in-memory pre-buffer
            # actually captures (hard-coded in _main_loop's pre_cutoff).
            #
            # The ffmpeg stream-copy path is different: its stub write
            # (_write_recording_event_stub, in _ffmpeg_clip.py) overrides
            # this to 0 the moment the clip starts recording — honest,
            # because nothing has been spliced yet — and then
            # _reencode_motion_clip overwrites it AGAIN with the REAL
            # number of seconds actually spliced in from the main-stream
            # pre-roll ring (camera_runtime._recording._preroll.MotionPreroll)
            # once the clip reaches "ready". A splice that fails, or a ring
            # that had too few buffered frames (camera just started, or
            # pre_motion_seconds configured to 0), leaves the final value
            # at 0 — this snapshot's "3" never survives to a finished
            # ffmpeg-path clip.
            "pre_motion_seconds": 3,
            "post_motion_seconds": int(self.cfg.get("post_motion_tail_s") or 0),
        }

    def _build_achievement_snapshot(self) -> dict:
        """Capture "what the configured settings actually produced"
        at finalize time. Only fields we can compute cheaply here go
        in synchronously — the post-hoc tracks.json-derived stats
        (tracks_by_class, peak_score_by_class, confirm_hits_by_track)
        are added by tracking_worker once it finishes its pass over
        the clip. Missing fields are intentionally omitted; the
        frontend renders "—" for what isn't there.

        Inference status mirrors the cam-edit Erkennung status strip:
          coral mode + low ms      → "ok"
          coral mode + ≥ 50 ms avg → "elevated"
          cpu fallback             → "cpu_emergency"
        """
        ach: dict = {}
        # inference_avg_ms — rolling mean from the runtime's deque.
        try:
            ms = getattr(self, "_inference_times_ms", None)
            if ms:
                ach["inference_avg_ms"] = round(sum(ms) / len(ms), 1)
        except Exception:
            pass
        # inference_status from detector.mode + average.
        try:
            det_mode = getattr(self.detector, "mode", "motion_only")
            avg = ach.get("inference_avg_ms")
            if det_mode == "cpu":
                ach["inference_status"] = "cpu_emergency"
            elif det_mode == "coral":
                ach["inference_status"] = "elevated" if avg is not None and avg >= 50.0 else "ok"
            # "motion_only" / "off" → no inference, omit the field.
        except Exception:
            pass
        # The very fact that we're in _finalize_motion_clip means the
        # pre-trigger fired. Peak motion score isn't tracked in the
        # current motion pipeline (contour-area thresholding has no
        # 0..1 score), so we intentionally omit it.
        ach["motion_pretrigger_fired"] = True
        return ach

    def record_adhoc_clip(self, seconds: int) -> str | None:
        """Capture a `seconds`-long mp4 from the live RTSP stream.

        Used by the Telegram menu's "Clip 5/15/30 s". Stream-copies the
        camera's H.264 directly into mp4 — no transcode, fast, ~1× wallclock.
        Returns the absolute path on success, None on failure.
        """
        import subprocess as _subprocess

        if seconds <= 0 or seconds > 60:
            return None
        rtsp = self.cfg.get("rtsp_url")
        if not rtsp:
            return None
        if not _FFMPEG_AVAILABLE:
            log.warning("[%s] adhoc clip: ffmpeg unavailable", self.camera_id)
            return None
        out_dir = Path(self.global_cfg["storage"]["root"]) / "adhoc_clips" / self.camera_id
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"adhoc-{ts}-{seconds}s.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp,
            "-t",
            str(int(seconds)),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        try:
            # Generous timeout: allow seconds + 5s startup + 5s flush.
            proc = _subprocess.run(cmd, capture_output=True, timeout=int(seconds) + 10)
            if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
                log.warning(
                    "[%s] adhoc clip ffmpeg rc=%s stderr=%s",
                    self.camera_id,
                    proc.returncode,
                    proc.stderr.decode("utf-8", "replace")[-300:],
                )
                return None
            log.info(
                "[%s] adhoc clip recorded: %s (%d bytes)",
                self.camera_id,
                out_path.name,
                out_path.stat().st_size,
            )
            return str(out_path)
        except Exception as e:
            log.warning("[%s] adhoc clip failed: %s", self.camera_id, e)
            return None
