from __future__ import annotations

import subprocess as _subprocess
import threading
from datetime import datetime
from pathlib import Path


from .._consts import log

# camera_runtime/_recording/ is two levels under app/app/, so
# ``...media_encode`` resolves to app.app.media_encode.
from ._finalize import FinalizeClipMixin
from ._stages import (
    STAGE_QUEUED,
    STAGE_RECORDING,
    set_clip_stage,
)


class FfmpegClipMixin(FinalizeClipMixin):
    """The ffmpeg stream-copy motion-clip RECORDING lifecycle — the path
    production actually takes (ffmpeg ships in the image): write the
    stub, start the stream copy, and hand the finished raw file to a
    background thread.

    Everything after that hand-off lives in ``_finalize.py`` and is
    inherited from :class:`FinalizeClipMixin` — the same split this file
    already implied, made real once it crossed CLAUDE.md's 500-line
    ceiling. Every call site is unchanged: ``FfmpegClipMixin`` still
    exposes the whole chain.

    Mixin for CameraRuntime (via RecordingMixin). Methods access shared
    state via `self.*` (recording state, store, motion_preroll) which
    live on the concrete class.
    """

    def _set_clip_stage(self, event_id: str, stage: str) -> None:
        """Announce which phase this clip is in. See ``_stages.py``."""
        set_clip_stage(self.store, self.camera_id, event_id, stage)

    def _write_recording_event_stub(
        self, event_id: str, meta: dict, start_time: datetime, status: str = "recording"
    ):
        """Write the event JSON for a clip whose encode is still in flight.
        Video fields are null; the frontend shows a 'recording'/'processing' state."""
        event = {
            "event_id": event_id,
            "camera_id": self.camera_id,
            "camera_name": self.cfg.get("name", self.camera_id),
            "armed": bool(self.cfg.get("armed", True)),
            "after_hours": meta["after_hours"],
            "alarm_level": meta["alarm_level"],
            "time": start_time.isoformat(timespec="seconds"),
            "labels": meta["labels"],
            "top_label": meta["top_label"],
            "bird_species": meta["bird_species"],
            "cat_name": meta["cat_name"],
            "person_name": meta["person_name"],
            "whitelisted": meta["whitelisted"],
            "detections": meta["detections"],
            "whole_clip": meta.get("whole_clip"),
            "snapshot_url": None,
            "snapshot_relpath": None,
            "thumb_url": None,
            "video_url": None,
            "video_relpath": None,
            "duration_s": 0.0,
            "file_size_bytes": 0,
            "status": status,
            # Fine stage + the moment it started, so the library can say
            # WHICH phase this clip is in and how long it has been there
            # instead of a bare "wird verarbeitet". stage_since is also
            # the only handle on a stub whose runtime died mid-clip.
            "stage": STAGE_RECORDING,
            "stage_since": start_time.isoformat(timespec="seconds"),
            "recording_settings": self._build_recording_settings_snapshot(),
            "provenance": self._build_provenance_snapshot(),
        }
        # The ffmpeg stream-copy path (this caller) starts the encoder at
        # trigger time — no in-memory pre-buffer covers the gap between
        # "motion confirmed" and "ffmpeg connected". Whatever pre-roll
        # this clip ends up with is only known once the splice at
        # finalize time (_reencode_motion_clip → _splice_preroll_onto_clip)
        # either succeeds or doesn't, so the stub honestly reports 0 s
        # while the clip is still "recording" — _reencode_motion_clip
        # overwrites this with the REAL achieved value once the clip
        # reaches "ready".
        event["recording_settings"]["pre_motion_seconds"] = 0
        self.store.add_event(self.camera_id, event)

    def _start_ffmpeg_recording(self, start_time: datetime, meta: dict) -> bool:
        """Launch an ffmpeg subprocess that stream-copies the RTSP feed to disk.
        Returns True on success, False to let the caller fall back to OpenCV."""
        storage_root = Path(self.global_cfg["storage"]["root"])
        day_dir = (
            storage_root / "motion_detection" / self.camera_id / start_time.strftime("%Y-%m-%d")
        )
        day_dir.mkdir(parents=True, exist_ok=True)
        event_id = start_time.strftime("%Y%m%d-%H%M%S-%f")
        raw_path = day_dir / f"{event_id}.raw.mp4"
        rtsp_url = self.cfg.get("rtsp_url")
        if not rtsp_url:
            return False
        # `-c copy` carries WHATEVER streams the RTSP feed offers, audio
        # included — this command has always written the camera's sound
        # into the raw file and it is `_transcode_raw_to_mp4` that decides
        # whether it survives. Deliberately NOT gated on `record_audio`:
        # gating it here would change the raw file (the fallback the event
        # exposes when the re-encode fails) for cameras that never turned
        # audio on, and this argv runs on the capture path where an extra
        # decision is an extra way to break a recording.
        cmd = [
            'ffmpeg',
            '-y',
            '-rtsp_transport',
            'tcp',
            '-i',
            rtsp_url,
            '-c',
            'copy',
            '-movflags',
            '+frag_keyframe+empty_moov',
            str(raw_path),
        ]
        try:
            proc = _subprocess.Popen(
                cmd,
                stdin=_subprocess.PIPE,
                stdout=_subprocess.DEVNULL,
                stderr=_subprocess.PIPE,
            )
        except FileNotFoundError:
            log.warning(
                "[%s] ffmpeg not found — using OpenCV frame buffer "
                "(playback speed may be incorrect)",
                self.camera_id,
            )
            return False
        except Exception as e:
            log.error("[%s] ffmpeg spawn failed: %s", self.camera_id, e)
            return False
        self._ffmpeg_proc = proc
        self._ffmpeg_out_path = raw_path
        self._ffmpeg_start_time = start_time
        self._rec_event_id = event_id
        # Snapshot the pre-roll ring right as the clip actually starts —
        # everything in it right now is genuinely BEFORE this trigger.
        # A camera that just started (ring empty) or has pre-roll turned
        # off (capacity_s <= 0) both hand back [] here, which the splice
        # step at finalize time already treats as "nothing to splice".
        ring = getattr(self, "motion_preroll", None)
        self._rec_preroll_frames = ring.snapshot() if ring is not None else []
        # Persist a 'recording' stub so the dashboard can show the clip immediately
        try:
            self._write_recording_event_stub(event_id, meta, start_time, status="recording")
        except Exception as e:
            log.warning("[%s] recording stub write failed: %s", self.camera_id, e)
        log.info("[%s] Recording started via ffmpeg (%s)", self.camera_id, raw_path.name)
        return True

    def _await_ffmpeg_exit(self, proc) -> None:
        """Ask the stream-copy to finish, then wait for it.

        Up to 8 s of waiting lives here (5 s on the 'q', 3 s more after a
        terminate), and it used to run INLINE ON THE CAPTURE LOOP. For
        that whole window the camera analysed no frames at all — it was
        blind in the seconds immediately after a motion event ended,
        which is exactly when a second animal walks into the same shot.
        The caller now hands this to the finalize thread instead.
        """
        try:
            if proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.write(b'q\n')
                    proc.stdin.flush()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except _subprocess.TimeoutExpired:
                log.warning("[%s] ffmpeg did not exit on 'q', terminating", self.camera_id)
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except _subprocess.TimeoutExpired:
                    proc.kill()
        except Exception as e:
            log.warning("[%s] ffmpeg stop error: %s", self.camera_id, e)

    def _stop_ffmpeg_and_queue_reencode(self):
        """Hand the finished recording to a background thread — and return.

        NOTHING BLOCKING HAPPENS HERE ANY MORE. This runs on the camera's
        capture loop (_recording_step.py calls it mid-tick), so every
        second spent here is a second the camera cannot see. The ffmpeg
        stop moved into the finalize thread with the rest of the chain;
        what is left is resetting the state so the next recording can
        start and spawning the thread.

        Two ffmpeg processes can now briefly overlap — the one being
        wound down and one a fresh trigger started. They write different
        files under different event ids and each holds its own RTSP
        connection, so the overlap costs a moment of bandwidth and buys
        back the blind window.
        """
        proc = self._ffmpeg_proc
        raw_path = self._ffmpeg_out_path
        event_id = self._rec_event_id
        meta = self._rec_event_meta
        start_time = self._ffmpeg_start_time
        preroll_frames = self._rec_preroll_frames
        # Reset state so a new recording can start immediately
        self._ffmpeg_proc = None
        self._ffmpeg_out_path = None
        self._ffmpeg_start_time = None
        self._rec_event_id = None
        self._rec_preroll_frames = []
        if proc is None:
            return
        log.info(
            "[%s] Recording stopped (%s), queuing re-encode",
            self.camera_id,
            raw_path.name if raw_path else "?",
        )
        if raw_path is None or event_id is None or meta is None or start_time is None:
            # Nothing to finalize, but the subprocess still has to die or
            # it holds an RTSP connection and a file handle for ever.
            threading.Thread(target=self._await_ffmpeg_exit, args=(proc,), daemon=True).start()
            return
        # Stream-copy is on disk, the re-encode thread is about to spawn.
        # Short-lived by design (each clip gets its own thread, there is
        # no shared worker pool), but it is the honest state right here.
        self._set_clip_stage(event_id, STAGE_QUEUED)
        threading.Thread(
            target=self._reencode_motion_clip,
            args=(raw_path, event_id, meta, start_time, preroll_frames),
            kwargs={"proc": proc},
            daemon=True,
        ).start()
