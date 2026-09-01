from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path

import cv2

from .._consts import log


class OpenCVFallbackMixin:
    """The legacy OpenCV frame-buffer recording path — used only when
    ffmpeg isn't available in the container (see ``_consts._FFMPEG_AVAILABLE``).
    Records to an in-memory frame list and encodes the whole clip at once,
    losing native timestamps in the process; ``FfmpegClipMixin`` is the
    path production actually takes.

    Extracted out of ``_recording/__init__.py`` to keep that file under
    CLAUDE.md's 500-line ceiling. Mixin for CameraRuntime (via
    RecordingMixin). Methods access shared state via `self.*` (recording
    state, store) which live on the concrete class.
    """

    def _write_clip_ffmpeg(self, frames, fps, out_path) -> bool:
        """Encode raw BGR frames to H.264/mp4 via ffmpeg pipe.

        Browsers cannot decode the mp4v codec cv2.VideoWriter produces.
        Piping raw BGR into libx264 yields a faststart-optimised mp4 that plays
        natively in every modern browser. Returns False on any failure so the
        caller can fall back to mp4v.
        """
        import subprocess as _sp

        if not frames:
            return False
        h, w = frames[0].shape[:2]
        fps_c = max(5.0, min(30.0, float(fps)))
        cmd = [
            'ffmpeg',
            '-y',
            '-f',
            'rawvideo',
            '-vcodec',
            'rawvideo',
            '-pix_fmt',
            'bgr24',
            '-s',
            f'{w}x{h}',
            '-r',
            str(fps_c),
            '-i',
            'pipe:0',
            '-vcodec',
            'libx264',
            '-preset',
            'fast',
            '-crf',
            '23',
            '-pix_fmt',
            'yuv420p',
            '-movflags',
            '+faststart',
            str(out_path),
        ]
        try:
            proc = _sp.Popen(cmd, stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE)
            last_good = frames[0]
            for f in frames:
                if self._is_frame_valid(f) and not self._is_frame_too_different(f, last_good):
                    proc.stdin.write(f.tobytes())
                    last_good = f
                else:
                    proc.stdin.write(last_good.tobytes())
            proc.stdin.close()
            _, stderr = proc.communicate(timeout=120)
            if proc.returncode != 0:
                log.error(
                    '[%s] ffmpeg encode failed: %s',
                    self.camera_id,
                    stderr.decode(errors='replace')[-800:],
                )
                return False
            return True
        except FileNotFoundError:
            log.warning('[%s] ffmpeg not found — falling back to mp4v', self.camera_id)
            return False
        except Exception as e:
            log.error('[%s] ffmpeg pipe error: %s', self.camera_id, e)
            return False

    def _finalize_motion_clip(self, frames: list, meta: dict, fps: float = 10.0):
        """Save MP4 clip (H.264 via ffmpeg, mp4v fallback), verify, write event JSON, send Telegram."""
        start_time: datetime = meta["time"]
        event_id: str = meta["event_id"]
        storage_root = Path(self.global_cfg["storage"]["root"])
        public_base = (self.global_cfg.get("server", {}).get("public_base_url") or "").rstrip("/")

        vid_path = None
        video_url = None
        video_relpath = None
        duration_s: float = 0.0
        file_size_bytes: int = 0
        encode_error: str | None = None
        fps_clamped = max(5.0, min(30.0, float(fps)))
        try:
            day_dir = (
                storage_root / "motion_detection" / self.camera_id / start_time.strftime("%Y-%m-%d")
            )
            day_dir.mkdir(parents=True, exist_ok=True)
            vid_path = day_dir / f"{event_id}.mp4"
            ok = self._write_clip_ffmpeg(frames, fps, vid_path)
            if not ok:
                # Fallback: legacy mp4v (may not play in browser)
                log.warning("[%s] H.264 encode unavailable, writing mp4v fallback", self.camera_id)
                encode_error = encode_error or "ffmpeg h264 encode failed — mp4v fallback"
                h, w = frames[0].shape[:2]
                writer = cv2.VideoWriter(
                    str(vid_path), cv2.VideoWriter_fourcc(*'mp4v'), fps_clamped, (w, h)
                )
                last_good = frames[0]
                for f in frames:
                    if self._is_frame_valid(f) and not self._is_frame_too_different(f, last_good):
                        writer.write(f)
                        last_good = f
                    else:
                        writer.write(last_good)
                writer.release()

            # Verify output: must exist, have size, and be a readable video with real duration
            if not vid_path.exists() or vid_path.stat().st_size < 1024:
                raise RuntimeError(
                    f"clip empty/missing ({vid_path.stat().st_size if vid_path.exists() else 0} bytes)"
                )
            check = cv2.VideoCapture(str(vid_path))
            fc = int(check.get(cv2.CAP_PROP_FRAME_COUNT))
            cfps = check.get(cv2.CAP_PROP_FPS) or fps_clamped
            check.release()
            dur = fc / cfps if cfps > 0 else 0.0
            if fc < 3 or dur < 0.3:
                raise RuntimeError(f"clip broken: frames={fc} dur={dur:.2f}s")

            duration_s = round(dur, 2)
            file_size_bytes = vid_path.stat().st_size
            rel = vid_path.relative_to(storage_root)
            video_url = (
                f"{public_base}/media/{rel.as_posix()}"
                if public_base
                else f"/media/{rel.as_posix()}"
            )
            video_relpath = rel.as_posix()
            # Extract a representative thumbnail frame (~1/3 into the clip) and
            # downscale to max 640px wide. The motion card + lightbox both use
            # snapshot_relpath as their preview image.
            thumb_path = day_dir / f"{event_id}.jpg"
            try:
                check_thumb = cv2.VideoCapture(str(vid_path))
                total_f = int(check_thumb.get(cv2.CAP_PROP_FRAME_COUNT))
                if total_f > 0:
                    check_thumb.set(cv2.CAP_PROP_POS_FRAMES, min(total_f // 3, total_f - 1))
                ok_th, frame_th = check_thumb.read()
                check_thumb.release()
                if ok_th and frame_th is not None:
                    tw = frame_th.shape[1]
                    if tw > 640:
                        scale = 640 / tw
                        frame_th = cv2.resize(frame_th, (640, int(frame_th.shape[0] * scale)))
                    cv2.imwrite(str(thumb_path), frame_th, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            except Exception as _te:
                log.debug("[%s] motion thumb failed: %s", self.camera_id, _te)
            log.info(
                "[%s] Motion clip saved: %s (%d frames %.1fs @ %.1ffps %dKB)",
                self.camera_id,
                vid_path.name,
                len(frames),
                dur,
                fps_clamped,
                file_size_bytes // 1024,
            )
        except Exception as e:
            log.error("[%s] Motion clip save error: %s", self.camera_id, e)
            if encode_error is None:
                encode_error = str(e)

        # Fallback: primary path failed but file exists — the mp4v writer output may
        # still be playable even without faststart. Re-check via OpenCV.
        if video_url is None and vid_path is not None and vid_path.exists():
            try:
                size_bytes = vid_path.stat().st_size
                if size_bytes > 0:
                    check = cv2.VideoCapture(str(vid_path))
                    fc = int(check.get(cv2.CAP_PROP_FRAME_COUNT))
                    cfps = check.get(cv2.CAP_PROP_FPS) or fps_clamped
                    check.release()
                    dur = fc / cfps if cfps > 0 else 0.0
                    if fc >= 3 and dur >= 0.3:
                        duration_s = round(dur, 2)
                        file_size_bytes = size_bytes
                        rel = vid_path.relative_to(storage_root)
                        video_url = (
                            f"{public_base}/media/{rel.as_posix()}"
                            if public_base
                            else f"/media/{rel.as_posix()}"
                        )
                        video_relpath = rel.as_posix()
                        log.warning(
                            "[%s] Motion clip recovered via fallback: %s (%d frames %.2fs, encode_error=%s)",
                            self.camera_id,
                            vid_path.name,
                            fc,
                            dur,
                            encode_error,
                        )
                    else:
                        log.error(
                            "[%s] Fallback: clip unreadable (frames=%d dur=%.2fs) — removing",
                            self.camera_id,
                            fc,
                            dur,
                        )
                        vid_path.unlink()
                else:
                    vid_path.unlink()
            except Exception as fe:
                log.error("[%s] Fallback read failed: %s", self.camera_id, fe)
                with contextlib.suppress(Exception):
                    vid_path.unlink()

        # Resolve thumbnail path (may have been created above after a successful encode)
        thumb_rel = None
        thumb_url = None
        try:
            if 'thumb_path' in locals() and thumb_path.exists():
                thumb_rel = thumb_path.relative_to(storage_root).as_posix()
                thumb_url = (
                    f"{public_base}/media/{thumb_rel}" if public_base else f"/media/{thumb_rel}"
                )
        except Exception:
            pass

        # Recording settings snapshot + achievement metrics. The first
        # block captures the detection config active at clip-finalize
        # time so each event.json carries the exact thresholds /
        # filters / cadence it was shot under. The second block
        # captures what those settings actually produced — inference
        # cadence + motion pretrigger state. Track-derived achievement
        # fields (tracks_by_class, peak_score_by_class,
        # confirm_hits_by_track) are filled in later by
        # tracking_worker once its pass over the mp4 completes; we
        # don't synthesise them here.
        recording_settings = self._build_recording_settings_snapshot()
        achievement = self._build_achievement_snapshot()

        # Write event JSON
        event = {
            "event_id": event_id,
            "camera_id": self.camera_id,
            "camera_name": self.cfg.get("name", self.camera_id),
            "armed": bool(self.cfg.get("armed", True)),
            "after_hours": meta["after_hours"],
            "alarm_level": meta["alarm_level"],
            "severity": meta.get("severity", "off"),
            "time": start_time.isoformat(timespec="seconds"),
            "labels": meta["labels"],
            "top_label": meta["top_label"],
            "bird_species": meta["bird_species"],
            "cat_name": meta["cat_name"],
            "person_name": meta["person_name"],
            "whitelisted": meta["whitelisted"],
            "detections": meta["detections"],
            "snapshot_url": thumb_url,
            "snapshot_relpath": thumb_rel,
            "thumb_url": thumb_url,
            "video_url": video_url,
            "video_relpath": video_relpath,
            "duration_s": duration_s,
            "file_size_bytes": file_size_bytes,
            "recording_settings": recording_settings,
            "achievement": achievement,
        }
        if encode_error:
            event["encode_error"] = encode_error

        # F06 first-since marker — runs BEFORE add_event so the first
        # write of the JSON already carries it.
        self._apply_first_since(event, meta)

        self.store.add_event(self.camera_id, event)

        # Phase 1 object tracking — enqueue a background pass that
        # writes <event_id>.tracks.json next to the mp4. Fire-and-
        # forget; the recording finalize must not block on it. Skip
        # when the clip never produced a playable mp4 (encode_error
        # set) or when the tracking worker hasn't been built yet
        # (early boot).
        if video_relpath and vid_path is not None and vid_path.exists():
            snap = (storage_root / thumb_rel) if thumb_rel else None
            self._enqueue_tracks_for_clip(event_id, vid_path, snap)

        # Same publish step the ffmpeg path uses — see _publish.py. The
        # marker is already stamped above, so it is not re-applied here.
        self._publish_finalized_event(event, meta, thumb_rel, apply_first_since=False)
