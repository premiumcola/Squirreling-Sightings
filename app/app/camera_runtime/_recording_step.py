from __future__ import annotations

import contextlib
import threading
import time

from ._consts import _FFMPEG_AVAILABLE, log


class RecordingStepMixin:
    """The RTSP branch of ``_loop``: pre-buffer, clip start, clip finalise.

    Lifted out of ``_main_loop`` to get that file back under CLAUDE.md's
    500-line ceiling, then split again at the state machine's own seams so
    no method here exceeds the 80-line function budget either. The one
    back-edge into the loop — a ``continue`` when every detection sits in
    a ``save_video: false`` zone — is returned as a flag instead of being
    performed here, so the caller still skips the same two statements it
    always skipped.

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (recording state, pre-buffer, store) which live on the concrete class.
    """

    def _rtsp_recording_step(
        self,
        *,
        proc_frame,
        now_dt,
        has_motion: bool,
        labels: list,
        detections: list,
        drawn,
        effective_bbox,
        cooldown: int,
    ) -> bool:
        """Run one frame through the recording state machine.

        Returns True when the caller must ``continue``.
        """
        # Measure main-stream FPS over a rolling 5 s window.
        self._main_fps_frames += 1
        _fps_el = time.time() - self._main_fps_window_start
        if _fps_el >= 5.0:
            self._main_fps = round(self._main_fps_frames / _fps_el, 1)
            self._main_fps_frames = 0
            self._main_fps_window_start = time.time()
        # Clip boundary knobs (configurable); ffmpeg stream-copy ignores
        # the pre-buffer, so it is only filled on the OpenCV fallback path.
        _proc = self.global_cfg.get("processing") or {}
        _clip_max = int(_proc.get("clip_max_duration_s", 120))
        _post_tail = float(
            self.cfg.get("post_motion_tail_s") or _proc.get("post_motion_tail_s", 3.0)
        )
        if not _FFMPEG_AVAILABLE:
            self._pre_buffer.append((proc_frame.copy(), time.time()))

        if has_motion:
            self._last_motion_ts = now_dt
            if not self._recording and self._start_clip(
                now_dt, labels, detections, drawn, effective_bbox, cooldown
            ):
                return True
            # Append frames only in OpenCV mode — ffmpeg records itself.
            if self._recording and self._ffmpeg_proc is None:
                self._rec_frames.append(proc_frame.copy())
        elif self._recording:
            self._advance_clip(proc_frame, now_dt, labels, detections, _post_tail, _clip_max)
        return False

    def _start_clip(
        self, now_dt, labels: list, detections: list, drawn, effective_bbox, cooldown: int
    ) -> bool:
        """Open a new recording session if the cooldown allows it.

        Returns True when the caller must ``continue`` — every detection
        landed in a ``save_video: false`` zone, so no clip is worth an
        ffmpeg launch.
        """
        has_person = "person" in labels
        elapsed = (now_dt - self.last_event_at).total_seconds()
        if has_person or elapsed >= cooldown:
            rec_meta = self._build_event_meta(now_dt, labels, detections, drawn, effective_bbox)
            # Zone trigger flag: if every detection in
            # this event sits in a zone with save_video
            # turned off, skip recording entirely. Cheap
            # short-circuit before ffmpeg launches.
            if not rec_meta.get("save_video", True):
                log.debug(
                    "[cam:%s] event %s: save_video=False, skipping clip",
                    self.camera_id,
                    rec_meta.get("event_id"),
                )
                # The loop's `continue`: it skips the trailing
                # last_error reset AND the inter-frame sleep, so the
                # next grab happens immediately. Signalled rather than
                # performed, because this is a method now.
                return True
            started = False
            if _FFMPEG_AVAILABLE:
                started = self._start_ffmpeg_recording(now_dt, rec_meta)
            if started:
                self._recording = True
                self._rec_start_time = now_dt
                self._rec_corrupt_frames = 0
                self._rec_event_meta = rec_meta
                self.last_event_at = now_dt
                self.event_counter_today += 1
                # Ticker: tell the operator a clip just
                # started. Diagnostic, not an alert — it
                # deliberately bypasses the push gates,
                # which are often what is being tested.
                self.notify_recording_started(rec_meta.get("labels"), rec_meta.get("event_id"))
            else:
                # OpenCV fallback (legacy path)
                self._recording = True
                self._rec_start_time = now_dt
                self._rec_corrupt_frames = 0
                pre_cutoff = time.time() - 3.0
                self._rec_frames = [f for f, ts in self._pre_buffer if ts >= pre_cutoff]
                self._rec_event_meta = rec_meta
                self.last_event_at = now_dt
                self.event_counter_today += 1
                log.info(
                    "[%s] Motion recording started (OpenCV, labels=%s, prebuf=%d frames)",
                    self.camera_id,
                    labels,
                    len(self._rec_frames),
                )
        return False

    def _advance_clip(
        self, proc_frame, now_dt, labels: list, detections: list, post_tail: float, clip_max: int
    ) -> None:
        """A frame with no motion while a clip is running: fold in late
        confirmations, accumulate the tail, and close the clip once the
        post-motion tail or the maximum duration is reached."""
        # F-2 · fold labels that confirmed AFTER the clip
        # started into the in-flight event. Motion wins the
        # confirmation race almost every time, so without
        # this the event stays "motion" and every downstream
        # gate reads that instead of "person".
        if labels and self._upgrade_event_meta(labels, detections):
            with contextlib.suppress(Exception):
                _eid = (self._rec_event_meta or {}).get("event_id")
                if _eid:
                    _ev = self.store.get_event(self.camera_id, _eid) or {}
                    _ev["labels"] = self._rec_event_meta["labels"]
                    _ev["top_label"] = self._rec_event_meta["top_label"]
                    _ev["alarm_level"] = self._rec_event_meta["alarm_level"]
                    _ev["severity"] = self._rec_event_meta["severity"]
                    self.store.update_event(self.camera_id, _eid, _ev)
        since_last = (
            (now_dt - self._last_motion_ts).total_seconds() if self._last_motion_ts else 999
        )
        since_start = (now_dt - self._rec_start_time).total_seconds() if self._rec_start_time else 0
        # In OpenCV mode we keep accumulating tail frames
        if self._ffmpeg_proc is None:
            self._rec_frames.append(proc_frame.copy())
        if since_last >= post_tail or since_start >= clip_max:
            if self._rec_corrupt_frames > 5:
                log.warning(
                    "[%s] %d corrupt frames rejected in this clip",
                    self.camera_id,
                    self._rec_corrupt_frames,
                )
            if self._ffmpeg_proc is not None:
                # ffmpeg mode: stop subprocess + queue re-encode
                self._stop_ffmpeg_and_queue_reencode()
                self._recording = False
                self._rec_start_time = None
                self._last_motion_ts = None
                self._rec_event_meta = None
                self._rec_corrupt_frames = 0
            else:
                # OpenCV fallback: finalize from frame buffer
                frames_snap = self._rec_frames[:]
                meta_snap = self._rec_event_meta
                measured_fps = (
                    max(5.0, min(30.0, len(frames_snap) / since_start))
                    if since_start > 0.5
                    else (self._main_fps or 10.0)
                )
                self._recording = False
                self._rec_frames = []
                self._rec_start_time = None
                self._last_motion_ts = None
                self._rec_event_meta = None
                self._rec_corrupt_frames = 0
                if meta_snap and len(frames_snap) >= 3:
                    threading.Thread(
                        target=self._finalize_motion_clip,
                        args=(frames_snap, meta_snap, measured_fps),
                        daemon=True,
                    ).start()
