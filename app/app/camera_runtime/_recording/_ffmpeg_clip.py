from __future__ import annotations

import contextlib
import subprocess as _subprocess
import threading
from datetime import datetime
from pathlib import Path

import cv2

from .._consts import log
from ._stages import (
    STAGE_ENCODING,
    STAGE_FAILED,
    STAGE_QUEUED,
    STAGE_READY,
    STAGE_RECORDING,
    STAGE_STATUS,
    set_clip_stage,
)


class FfmpegClipMixin:
    """The ffmpeg stream-copy motion-clip lifecycle — the path production
    actually takes (ffmpeg ships in the image): start → stop/reencode →
    finalize, plus the pre-roll splice at finalize time.

    Extracted out of ``_recording/__init__.py`` to keep that file under
    CLAUDE.md's 500-line ceiling once the pre-roll splice call landed here
    too. Mixin for CameraRuntime (via RecordingMixin). Methods access
    shared state via `self.*` (recording state, store, motion_preroll)
    which live on the concrete class.
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

    def _stop_ffmpeg_and_queue_reencode(self):
        """Stop the running ffmpeg subprocess gracefully, then kick off a background
        thread that re-encodes the raw stream-copy to browser-friendly H.264."""
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
        log.info(
            "[%s] Recording stopped (%s), queuing re-encode",
            self.camera_id,
            raw_path.name if raw_path else "?",
        )
        if raw_path is None or event_id is None or meta is None or start_time is None:
            return
        # Stream-copy is on disk, the re-encode thread is about to spawn.
        # Short-lived by design (each clip gets its own thread, there is
        # no shared worker pool), but it is the honest state right here.
        self._set_clip_stage(event_id, STAGE_QUEUED)
        threading.Thread(
            target=self._reencode_motion_clip,
            args=(raw_path, event_id, meta, start_time, preroll_frames),
            daemon=True,
        ).start()

    def _reencode_motion_clip(
        self,
        raw_path: Path,
        event_id: str,
        meta: dict,
        start_time: datetime,
        preroll_frames: list | None = None,
    ):
        """Background: transcode raw stream-copy → browser-friendly H.264,
        then splice the pre-roll ring onto the front of it.
        On success: delete the raw file, set video_url/snapshot/thumb/status=ready.
        On failure: keep raw as fallback, set encode_error on the event.

        Broken into the sub-steps below so no single method here crosses
        CLAUDE.md's 80-line function ceiling — this orchestrator just
        threads state between them in order.
        """
        storage_root = Path(self.global_cfg["storage"]["root"])
        public_base = (self.global_cfg.get("server", {}).get("public_base_url") or "").rstrip("/")
        day_dir = raw_path.parent
        vid_path = day_dir / f"{event_id}.mp4"

        video_url, video_relpath, duration_s, file_size_bytes, encode_error = (
            self._transcode_raw_to_mp4(raw_path, vid_path, event_id, storage_root, public_base)
        )
        thumb_source = vid_path if vid_path.exists() else (raw_path if raw_path.exists() else None)
        thumb_rel, thumb_url = self._extract_motion_thumbnail(
            thumb_source, day_dir, event_id, storage_root, public_base
        )

        # Pre-roll splice — ONLY once the trigger-only clip is confirmed
        # playable above. Never risk the footage we already know is good
        # to chase a few extra seconds of lead-in.
        achieved_pre_s = 0.0
        if video_url and vid_path.exists() and preroll_frames:
            achieved_pre_s, duration_s, file_size_bytes = self._apply_preroll_splice(
                vid_path, preroll_frames, event_id, day_dir, duration_s, file_size_bytes
            )

        ev = self._update_reencoded_event(
            event_id,
            video_url=video_url,
            video_relpath=video_relpath,
            duration_s=duration_s,
            file_size_bytes=file_size_bytes,
            thumb_url=thumb_url,
            thumb_rel=thumb_rel,
            encode_error=encode_error,
            achieved_pre_s=achieved_pre_s,
        )

        # Tracking sidecar — enqueue once per finalized clip so the
        # next Mediathek open finds <event>.tracks.json on disk. The
        # ffmpeg re-encode path used to skip this step; the legacy
        # OpenCV-buffer finalize did it, so the Lightbox kept showing
        # "Tracking wird generiert" on every first open of an
        # ffmpeg-recorded clip. video_relpath is the source of truth
        # for the playable file (vid_path on success, raw_path on
        # fallback) — derive the absolute path from it.
        if video_url and video_relpath:
            playable = storage_root / video_relpath
            snap = (storage_root / thumb_rel) if thumb_rel else None
            self._enqueue_tracks_for_clip(event_id, playable, snap)

        # Every consequence of the event — first-since, MQTT, achievement,
        # quests, dossiers, and the Telegram alert. This path is the one
        # production actually takes (ffmpeg is installed in the image), and
        # it used to do NONE of that: a comment here claimed the alert was
        # "fired once, by the modern push pipeline in _finalize_motion_clip",
        # but that function is reachable only from the OpenCV fallback. So
        # the alert removed here as a duplicate was the only one that ran.
        # See _publish.py.
        meta.setdefault("event_id", event_id)
        ev.setdefault("event_id", event_id)
        self._publish_finalized_event(ev, meta, thumb_rel)

    def _transcode_raw_to_mp4(
        self, raw_path: Path, vid_path: Path, event_id: str, storage_root: Path, public_base: str
    ) -> tuple[str | None, str | None, float, int, str | None]:
        """Run the raw stream-copy → H.264 ffmpeg pass. Returns
        ``(video_url, video_relpath, duration_s, file_size_bytes, encode_error)``
        — on failure, falls back to exposing the still-on-disk raw file
        rather than losing the clip."""
        video_url = None
        video_relpath = None
        duration_s = 0.0
        file_size_bytes = 0
        encode_error = None
        # ffmpeg is about to run — this is the long pole of the chain and
        # the one the user actually waits on.
        self._set_clip_stage(event_id, STAGE_ENCODING)
        try:
            if not raw_path.exists() or raw_path.stat().st_size < 1024:
                raise RuntimeError(
                    f"raw clip missing/empty ({raw_path.stat().st_size if raw_path.exists() else 0} bytes)"
                )
            cmd = [
                'ffmpeg',
                '-y',
                '-i',
                str(raw_path),
                '-vcodec',
                'libx264',
                '-preset',
                'fast',
                '-crf',
                '22',
                '-pix_fmt',
                'yuv420p',
                '-movflags',
                '+faststart',
                '-an',
                str(vid_path),
            ]
            r = _subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode != 0 or not vid_path.exists() or vid_path.stat().st_size < 1024:
                stderr_text = (r.stderr or b'').decode('utf-8', errors='replace')
                raise RuntimeError(f"ffmpeg re-encode rc={r.returncode}: {stderr_text[-300:]}")
            # Verify
            check = cv2.VideoCapture(str(vid_path))
            fc = int(check.get(cv2.CAP_PROP_FRAME_COUNT))
            cfps = check.get(cv2.CAP_PROP_FPS) or 0.0
            check.release()
            duration_s = round(fc / cfps, 2) if cfps > 0 else 0.0
            file_size_bytes = vid_path.stat().st_size
            rel = vid_path.relative_to(storage_root)
            video_url = (
                f"{public_base}/media/{rel.as_posix()}"
                if public_base
                else f"/media/{rel.as_posix()}"
            )
            video_relpath = rel.as_posix()
            # Delete raw on success
            with contextlib.suppress(Exception):
                raw_path.unlink()
            log.info(
                "[%s] Re-encode complete: %s (%.1fs %dKB)",
                self.camera_id,
                vid_path.name,
                duration_s,
                file_size_bytes // 1024,
            )
        except Exception as e:
            log.error("[%s] Re-encode failed: %s", self.camera_id, e)
            encode_error = str(e)
            # Fallback: raw may still be playable — expose it if so
            if raw_path.exists() and raw_path.stat().st_size > 1024:
                rel = raw_path.relative_to(storage_root)
                video_url = (
                    f"{public_base}/media/{rel.as_posix()}"
                    if public_base
                    else f"/media/{rel.as_posix()}"
                )
                video_relpath = rel.as_posix()
                file_size_bytes = raw_path.stat().st_size
        return video_url, video_relpath, duration_s, file_size_bytes, encode_error

    def _extract_motion_thumbnail(
        self,
        thumb_source: Path | None,
        day_dir: Path,
        event_id: str,
        storage_root: Path,
        public_base: str,
    ) -> tuple[str | None, str | None]:
        """Grab a representative frame (~1/3 into whichever file is
        present) and downscale to max 640px wide. Returns
        ``(thumb_relpath, thumb_url)``, both None on any failure."""
        if thumb_source is None:
            return None, None
        thumb_path = day_dir / f"{event_id}.jpg"
        try:
            cap = cv2.VideoCapture(str(thumb_source))
            total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_f > 3:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total_f // 3)
            ok_th, frame_th = cap.read()
            cap.release()
            if ok_th and frame_th is not None:
                tw = frame_th.shape[1]
                if tw > 640:
                    scale = 640 / tw
                    frame_th = cv2.resize(frame_th, (640, int(frame_th.shape[0] * scale)))
                if cv2.imwrite(str(thumb_path), frame_th, [int(cv2.IMWRITE_JPEG_QUALITY), 75]):
                    thumb_rel = thumb_path.relative_to(storage_root).as_posix()
                    thumb_url = (
                        f"{public_base}/media/{thumb_rel}" if public_base else f"/media/{thumb_rel}"
                    )
                    return thumb_rel, thumb_url
        except Exception as _te:
            log.debug("[%s] motion thumb (post-encode) failed: %s", self.camera_id, _te)
        return None, None

    def _apply_preroll_splice(
        self,
        vid_path: Path,
        preroll_frames: list,
        event_id: str,
        day_dir: Path,
        duration_s: float,
        file_size_bytes: int,
    ) -> tuple[float, float, int]:
        """Splice the pre-roll ring onto ``vid_path`` and re-probe on
        success so the caller's duration/size describe the spliced file,
        not the trigger-only segment. Returns
        ``(achieved_pre_s, duration_s, file_size_bytes)`` — the latter two
        unchanged when there was nothing to splice or the splice failed."""
        achieved_pre_s = self._splice_preroll_onto_clip(vid_path, preroll_frames, event_id, day_dir)
        if achieved_pre_s <= 0:
            return achieved_pre_s, duration_s, file_size_bytes
        try:
            chk = cv2.VideoCapture(str(vid_path))
            fc = int(chk.get(cv2.CAP_PROP_FRAME_COUNT))
            cfps = chk.get(cv2.CAP_PROP_FPS) or 0.0
            chk.release()
            if fc > 0 and cfps > 0:
                duration_s = round(fc / cfps, 2)
            file_size_bytes = vid_path.stat().st_size
        except Exception as e:
            log.debug("[%s] post-splice re-probe failed: %s", self.camera_id, e)
        return achieved_pre_s, duration_s, file_size_bytes

    def _update_reencoded_event(
        self,
        event_id: str,
        *,
        video_url: str | None,
        video_relpath: str | None,
        duration_s: float,
        file_size_bytes: int,
        thumb_url: str | None,
        thumb_rel: str | None,
        encode_error: str | None,
        achieved_pre_s: float,
    ) -> dict:
        """Transition the event JSON from 'processing' → 'ready'/'error'.
        Returns the dict actually written (``{}`` on a store read/write
        failure) so the caller's publish step always has something to
        pass on, even when this update itself could not be persisted."""
        ev: dict = {}
        try:
            ev = self.store.get_event(self.camera_id, event_id) or {}
            ev["video_url"] = video_url
            ev["video_relpath"] = video_relpath
            ev["duration_s"] = duration_s
            ev["file_size_bytes"] = file_size_bytes
            ev["snapshot_url"] = thumb_url
            ev["snapshot_relpath"] = thumb_rel
            ev["thumb_url"] = thumb_url
            ev["stage"] = STAGE_READY if video_url else STAGE_FAILED
            ev["status"] = STAGE_STATUS[ev["stage"]]
            ev["stage_since"] = datetime.now().isoformat(timespec="seconds")
            if encode_error:
                ev["encode_error"] = encode_error
            rs = ev.get("recording_settings") or {}
            rs["pre_motion_seconds"] = round(achieved_pre_s, 2)
            ev["recording_settings"] = rs
            self.store.update_event(self.camera_id, event_id, ev)
        except Exception as e:
            log.warning("[%s] event JSON update failed: %s", self.camera_id, e)
        return ev
