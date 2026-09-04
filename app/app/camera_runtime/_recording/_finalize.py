"""What happens to a motion clip AFTER the recording stops.

Split out of ``_ffmpeg_clip.py``, which had grown to 598 lines against
CLAUDE.md's 500-line ceiling. The seam is the one the file already had:
everything up to ``_stop_ffmpeg_and_queue_reencode`` is the RECORDING
lifecycle and runs while the camera is filming; everything here runs on
a background thread once it has stopped, and is only ever entered from
that one hand-off.

The chain, in order, and the reason it is that order:

    stop ffmpeg  →  transcode to H.264  →  splice the pre-roll on
                 →  thumbnail  →  scrub filmstrip  →  stamp ready
                 →  sidecar, MQTT, alert

The thumbnail and the filmstrip both come AFTER the splice on purpose:
they describe the file the operator receives, and the splice changes
both its length and its opening seconds. The filmstrip comes after the
``ready`` stamp is prepared but is never allowed to delay it — a
convenience must not hold up footage.
"""

from __future__ import annotations

import contextlib
import subprocess as _subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2

from .._consts import log
from ...media_encode import build_reencode_cmd
from ._stages import (
    STAGE_ENCODING,
    STAGE_FAILED,
    STAGE_READY,
    STAGE_STATUS,
)


class FinalizeClipMixin:
    """The post-recording half of the ffmpeg clip lifecycle.

    Mixed into ``FfmpegClipMixin`` so every existing call site keeps
    working unchanged — nothing outside this package knows the split
    happened.
    """

    def _reencode_motion_clip(
        self,
        raw_path: Path,
        event_id: str,
        meta: dict,
        start_time: datetime,
        preroll_frames: list | None = None,
        *,
        proc=None,
    ):
        """The whole post-recording chain, in order. See this module's
        header for what that order is and why.

        On success: delete the raw file, set
        video_url/snapshot/thumb/status=ready. On failure: keep the raw
        file as the fallback the event exposes, and set encode_error.

        An orchestrator only — every step is its own method, so no single
        one crosses CLAUDE.md's 80-line ceiling.
        """
        # The whole chain's wall clock — the operator's actual answer to
        # "recording stopped, when can I watch it". Every sub-step below
        # was individually unmeasured, so the total was too.
        _chain_t0 = time.monotonic()
        # The stop is the FIRST thing here and not the caller's job any
        # more (see _stop_ffmpeg_and_queue_reencode for why those seconds
        # must not be spent on the capture loop), and the raw file is not
        # complete until ffmpeg has closed it.
        if proc is not None:
            self._await_ffmpeg_exit(proc)
        storage_root = Path(self.global_cfg["storage"]["root"])
        public_base = (self.global_cfg.get("server", {}).get("public_base_url") or "").rstrip("/")
        day_dir = raw_path.parent
        vid_path = day_dir / f"{event_id}.mp4"

        video_url, video_relpath, duration_s, file_size_bytes, encode_error, achieved_pre_s = (
            self._produce_playable_clip(
                raw_path, vid_path, event_id, day_dir, storage_root, public_base, preroll_frames
            )
        )

        # AFTER the splice, not before. The thumbnail seeks to a third of
        # whatever file it is handed, and it used to be handed the
        # trigger-only clip — so on every spliced recording the frame it
        # picked sat a whole pre-roll later than a third of the clip the
        # operator actually receives. The filmstrip is built from the
        # final file; the preview picture has to come from the same one,
        # or the grid and the poster disagree about what this clip is.
        thumb_source = vid_path if vid_path.exists() else (raw_path if raw_path.exists() else None)
        thumb_rel, thumb_url = self._extract_motion_thumbnail(
            thumb_source, day_dir, event_id, storage_root, public_base
        )

        # The scrub filmstrip, AFTER the splice — the sheet has to describe
        # the clip the operator will actually drag through, and the splice
        # changes both its length and its first seconds. Never before the
        # clip is playable: this is a convenience, and a convenience must
        # not be able to delay the footage.
        scrub = self._build_scrub_sprite(vid_path if video_url else None)

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
            meta=meta,
            scrub=scrub,
        )

        self._announce_finished_clip(
            ev,
            meta,
            event_id=event_id,
            storage_root=storage_root,
            video_url=video_url,
            video_relpath=video_relpath,
            thumb_rel=thumb_rel,
            duration_s=duration_s,
            achieved_pre_s=achieved_pre_s,
            chain_t0=_chain_t0,
        )

    def _produce_playable_clip(
        self,
        raw_path: Path,
        vid_path: Path,
        event_id: str,
        day_dir: Path,
        storage_root: Path,
        public_base: str,
        preroll_frames: list | None,
    ) -> tuple[str | None, str | None, float, int, str | None, float]:
        """Turn the raw stream copy into the file the operator receives.

        Transcode, then splice the pre-roll onto the front of it. Split
        off the orchestrator to keep it inside the 80-line ceiling, and
        because these two steps share one invariant worth stating once:
        the splice runs ONLY on a clip already confirmed playable, and
        every failure inside it leaves that clip untouched. Footage that
        is known good is never risked to chase a few seconds of lead-in.
        """
        video_url, video_relpath, duration_s, file_size_bytes, encode_error = (
            self._transcode_raw_to_mp4(raw_path, vid_path, event_id, storage_root, public_base)
        )
        achieved_pre_s = 0.0
        if video_url and vid_path.exists() and preroll_frames:
            achieved_pre_s, duration_s, file_size_bytes = self._apply_preroll_splice(
                vid_path, preroll_frames, event_id, day_dir, duration_s, file_size_bytes
            )
        return video_url, video_relpath, duration_s, file_size_bytes, encode_error, achieved_pre_s

    def _announce_finished_clip(
        self,
        ev: dict,
        meta: dict,
        *,
        event_id: str,
        storage_root: Path,
        video_url: str | None,
        video_relpath: str | None,
        thumb_rel: str | None,
        duration_s: float,
        achieved_pre_s: float,
        chain_t0: float,
    ) -> None:
        """Everything that happens once the clip is already watchable.

        Split off the orchestrator above so it stays inside CLAUDE.md's
        80-line ceiling, and because this is genuinely a different job:
        nothing here can affect whether the footage exists or plays. It
        is the announcement, not the production.
        """
        # The number the operator is really asking about: how long after
        # the recording stopped the clip became watchable. Everything
        # below — the tracking sidecar, MQTT, the Telegram alert —
        # happens on an already-playable clip and is deliberately outside
        # this measurement.
        log.info(
            "[%s] Clip abspielbar nach %.1fs (clip %.1fs, Vorlauf %.1fs)",
            self.camera_id,
            time.monotonic() - chain_t0,
            duration_s,
            achieved_pre_s,
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
            cmd = build_reencode_cmd(
                raw_path, vid_path, record_audio=bool(self.cfg.get("record_audio"))
            )
            # WALL CLOCK, because nothing measured this. The longest step
            # in the whole finalize chain — the one the operator actually
            # waits out before a clip is watchable — had no elapsed log
            # anywhere in the tree. The line below that looks like one
            # prints the CLIP's length and its file size, not the time
            # this took, so "how long until I can watch it" was
            # unanswerable from the logs. The timelapse encoder has
            # measured itself properly all along (_timelapse_encode.py);
            # this path simply never did.
            _t0 = time.monotonic()
            r = _subprocess.run(cmd, capture_output=True, timeout=300)
            encode_wall_s = time.monotonic() - _t0
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
            # Both numbers, named for what they are. `clip` is how long
            # the footage runs; `real` is how long the operator waited
            # for it. Only the second answers "why is it not there yet",
            # and the ratio is what says whether this box can keep up:
            # above 1.0 the encoder is slower than the camera records.
            log.info(
                "[%s] Re-encode complete: %s (clip %.1fs · real %.1fs · %.2fx · %dKB)",
                self.camera_id,
                vid_path.name,
                duration_s,
                encode_wall_s,
                (encode_wall_s / duration_s) if duration_s > 0 else 0.0,
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

    def _build_scrub_sprite(self, vid_path: Path | None) -> dict | None:
        """The scrub filmstrip for a finished clip, or None.

        Thin wrapper so the finalize chain reads as one list of steps and
        the sprite logic stays in ``scrub_sprite.py`` where it is unit
        tested without a runtime. Imported lazily for the same reason the
        rest of this module defers heavy imports: a recorder that never
        finishes a clip should not pay for it at start-up.
        """
        if vid_path is None or not vid_path.exists():
            return None
        from ...scrub_sprite import build_scrub_sprite

        geo = build_scrub_sprite(vid_path)
        if geo:
            log.debug(
                "[%s] scrub filmstrip: %d Kacheln, alle %.2fs",
                self.camera_id,
                geo["count"],
                geo.get("interval_s") or 0.0,
            )
        return geo

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
        meta: dict | None = None,
        scrub: dict | None = None,
    ) -> dict:
        """Transition the event JSON from 'processing' → 'ready'/'error'.
        Returns the dict actually written (``{}`` on a store read/write
        failure) so the caller's publish step always has something to
        pass on, even when this update itself could not be persisted.

        This is also where the finished whole-clip aggregate reaches
        disk. The stub written at `_write_recording_event_stub` could
        only carry the trigger frame — the clip had not happened yet —
        and nothing between there and here rewrites it, so an event
        would otherwise keep a `whole_clip` block describing one frame
        of a clip that ran for a minute.
        """
        ev: dict = {}
        try:
            ev = self.store.get_event(self.camera_id, event_id) or {}
            if meta is not None:
                if meta.get("whole_clip") is not None:
                    ev["whole_clip"] = meta["whole_clip"]
                # The headline the whole clip decided, which the stub
                # predates in exactly the case that matters: a species
                # only identifiable seconds into the clip.
                if meta.get("bird_species"):
                    ev["bird_species"] = meta["bird_species"]
            ev["video_url"] = video_url
            ev["video_relpath"] = video_relpath
            ev["duration_s"] = duration_s
            ev["file_size_bytes"] = file_size_bytes
            # The scrub filmstrip's geometry travels ON the event, not in
            # a sidecar: the library already sends this object with every
            # item, so the player gets the grid for free. Only written
            # when a sheet was actually produced — an absent key is the
            # honest "no preview for this clip".
            if scrub:
                ev["scrub"] = scrub
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
