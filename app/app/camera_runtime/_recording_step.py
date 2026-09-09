from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

from ..settings._consts import BIRD_SPECIES_VIDEO_CAP_DEFAULT
from ..species_video_count import confirmed_video_count
from ._clip_tally import ClipTally, rank_headline_species
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
        # No FPS accounting here. This method runs on a strictly smaller
        # set of iterations than the loop it is called from (snapshot
        # cameras never reach it, and the recording-block gate skips it on
        # motion frames), so a rate counted here understates the loop the
        # tracker ticks in — see _cadence.py.
        # Clip boundary knobs (configurable).
        _proc = self.global_cfg.get("processing") or {}
        _clip_max = int(_proc.get("clip_max_duration_s", 120))
        _post_tail = float(
            self.cfg.get("post_motion_tail_s") or _proc.get("post_motion_tail_s", 3.0)
        )
        # Feed whichever pre-roll buffer this recording backend actually
        # uses, every tick, motion or not — a trigger can fire on ANY
        # tick, so the buffer has to already be full by then. ffmpeg
        # stream-copy has no frame-level access of its own (a separate
        # subprocess reads RTSP directly), so its pre-roll comes from this
        # JPEG ring instead — see _recording/_preroll.py.
        if _FFMPEG_AVAILABLE:
            self.motion_preroll.push(proc_frame)
        else:
            self._pre_buffer.append((proc_frame.copy(), time.time()))

        if has_motion:
            self._last_motion_ts = now_dt
            if not self._recording and self._start_clip(
                now_dt, labels, detections, drawn, effective_bbox, cooldown
            ):
                return True
            if self._recording:
                self._absorb_clip_frame(detections, now_dt)
            # Append frames only in OpenCV mode — ffmpeg records itself.
            if self._recording and self._ffmpeg_proc is None:
                self._rec_frames.append(proc_frame.copy())
        elif self._recording:
            self._absorb_clip_frame(detections, now_dt)  # before the close
            self._advance_clip(proc_frame, now_dt, labels, detections, _post_tail, _clip_max)
        return False

    def _absorb_clip_frame(self, detections: list, now_dt) -> None:
        """Fold one analysis tick into the in-flight clip's aggregate.

        Called from BOTH arms of the state machine above, and in the
        no-motion arm it runs BEFORE `_advance_clip` — the method that
        can close the clip. The last tick's detections belong to the
        event just as much as the first tick's, and a subject that only
        shows itself during the post-motion tail is precisely the case
        the single-frame freeze used to lose.

        Cheap by construction — no inference, no frame copy, no I/O. It
        reads results the pipeline computed for this tick anyway and
        merges them per tracker track (see `_clip_tally.ClipTally`).

        The aggregate is kept live on `_rec_event_meta` rather than
        computed at close, because the meta is what all three event
        writers read and what the ffmpeg finalise thread carries off —
        so an event is never a stale copy of the tally, and a clip
        interrupted by a runtime death still has whatever it had seen.
        """
        tally = self._clip_tally
        meta = self._rec_event_meta
        if tally is None or meta is None:
            return
        started = self._rec_start_time
        t_s = (now_dt - started).total_seconds() if started else 0.0
        tally.add_frame(detections, max(0.0, t_s))
        meta["whole_clip"] = tally.summary()
        # Re-decide the headline over everything the clip has shown so
        # far. Same rarest-first rule, more evidence — the species that
        # only becomes identifiable three seconds in now reaches the
        # event. Only overwrite when the clip actually yields a name: a
        # later birdless stretch must not blank a name already won.
        species = rank_headline_species(tally.headline_candidates())
        if species:
            meta["bird_species"] = species

    def _species_over_cap(self, rec_meta: dict) -> str | None:
        """The confirmed species this event is about, when it has already
        collected enough VIDEO samples that another one is not worth an
        ffmpeg launch — else None.

        "Confirmed" is `species_video_count.confirmed_video_count`, an
        operator-confirmed lifetime count (a Telegram "Ja"), never the
        raw detection count — an unconfirmed misfire must not be able to
        cap a species on its own. A rare species that never crosses the
        cap simply never triggers this; that is the whole design.
        """
        if "bird" not in (rec_meta.get("labels") or []):
            return None
        species = (rec_meta.get("bird_species") or "").strip()
        if not species:
            return None
        # `or` would read an explicit 0 as "unset" and silently fall back
        # to the default — the exact bug this codebase has been bitten
        # by before on `post_motion_tail_s` (see CLAUDE.md's own note on
        # `resolve_pre_motion_seconds`). `None`-check instead.
        cap_raw = (self.global_cfg.get("storage") or {}).get("bird_species_video_cap")
        cap = int(cap_raw) if cap_raw is not None else BIRD_SPECIES_VIDEO_CAP_DEFAULT
        if cap <= 0:  # operator turned the cap fully off
            return None
        storage_root = self.global_cfg["storage"]["root"]
        if confirmed_video_count(storage_root, species) >= cap:
            return species
        return None

    def _persist_capped_sighting(
        self, now_dt, event_id: str, species: str, rec_meta: dict, drawn, effective_bbox
    ) -> None:
        """The species is already well-documented on video — keep the
        SIGHTING (so the Sichtungen grid and the species tally still
        count today's magpie) without another full recording.

        Mirrors `_loop_stages._save_snapshot_event`'s event shape (a
        snapshot camera's event has no video either) closely enough to
        reuse its JPEG writer, rather than a third copy of the same
        cv2.imwrite call. Deliberately quiet: no Telegram, no MQTT — the
        whole point of the cap is fewer notifications about a species
        the operator has already confirmed plenty of times.
        """
        day_dir = (
            Path(self.global_cfg["storage"]["root"])
            / "motion_detection"
            / self.camera_id
            / now_dt.strftime("%Y-%m-%d")
        )
        day_dir.mkdir(parents=True, exist_ok=True)
        snap_path = day_dir / f"{event_id}.jpg"
        rel = snap_path.relative_to(Path(self.global_cfg["storage"]["root"]))
        public_base = (self.global_cfg.get("server", {}).get("public_base_url") or "").rstrip("/")
        snapshot_url = self._write_snapshot_jpeg(snap_path, rel, drawn, effective_bbox, public_base)
        event = {
            "event_id": event_id,
            "camera_id": self.camera_id,
            "camera_name": self.cfg.get("name", self.camera_id),
            "armed": bool(self.cfg.get("armed", True)),
            "after_hours": rec_meta["after_hours"],
            "alarm_level": rec_meta["alarm_level"],
            "time": now_dt.isoformat(timespec="seconds"),
            "labels": rec_meta["labels"],
            "top_label": rec_meta["top_label"],
            "bird_species": species,
            "cat_name": rec_meta["cat_name"],
            "person_name": rec_meta["person_name"],
            "whitelisted": rec_meta["whitelisted"],
            "detections": rec_meta["detections"],
            "whole_clip": rec_meta.get("whole_clip"),
            "snapshot_url": snapshot_url,
            "snapshot_relpath": rel.as_posix() if snapshot_url else None,
            "video_url": None,
            "video_relpath": None,
            "provenance": self._build_provenance_snapshot(),
            # Not read by anything yet — a trail for the operator/UI to
            # explain "why is there no video here" without guessing.
            "capped_species_sighting": True,
        }
        self.store.add_event(self.camera_id, event)
        log.info(
            "[cam:%s] %s: Art bereits gut dokumentiert (%s) — nur Sichtung, kein Video",
            self.camera_id,
            event_id,
            species,
        )

    def _start_clip(
        self, now_dt, labels: list, detections: list, drawn, effective_bbox, cooldown: int
    ) -> bool:
        """Open a new recording session if the cooldown allows it.

        Returns True when the caller must ``continue`` — either every
        detection landed in a ``save_video: false`` zone, or this
        species already has enough confirmed video and only got a
        lightweight sighting instead. Either way, no clip is worth an
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
            capped_species = self._species_over_cap(rec_meta)
            if capped_species:
                self._persist_capped_sighting(
                    now_dt, rec_meta["event_id"], capped_species, rec_meta, drawn, effective_bbox
                )
                # Bookkeeping a full clip would have done — WITHOUT this
                # the cooldown never resets and the next motion frame
                # (often milliseconds later, the same bird still in
                # frame) re-enters here and writes ANOTHER sighting,
                # which is the exact flood the cap exists to prevent.
                self.last_event_at = now_dt
                self.event_counter_today += 1
                return True
            # One tally per clip, opened before either backend starts so
            # the trigger frame is inside the aggregate rather than a
            # special case beside it. A fresh instance per clip is what
            # scopes the aggregate to the EVENT — the live tracker's own
            # tracks outlive the clip (they age out on the miss-grace
            # window, not on the clip boundary), so reading its state at
            # close would mix in subjects from before this event began.
            self._clip_tally = ClipTally()
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
                self._start_opencv_fallback_recording(now_dt, rec_meta, labels)
        return False

    def _start_opencv_fallback_recording(self, now_dt, rec_meta: dict, labels: list) -> None:
        """The legacy path: no ffmpeg, so the clip comes from the frame
        buffer this loop has been filling all along. Split out of
        `_start_clip` to keep that method inside CLAUDE.md's 80-line
        ceiling."""
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
                # ffmpeg mode: stop subprocess + queue re-encode.
                # _stop_ffmpeg_and_queue_reencode snapshots
                # _rec_event_meta — whole_clip and all — BEFORE the
                # reset below clears it, so the finalise thread carries
                # the completed aggregate off with it.
                self._stop_ffmpeg_and_queue_reencode()
                self._recording = False
                self._rec_start_time = None
                self._last_motion_ts = None
                self._rec_event_meta = None
                self._clip_tally = None
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
                self._clip_tally = None
                self._rec_corrupt_frames = 0
                if meta_snap and len(frames_snap) >= 3:
                    threading.Thread(
                        target=self._finalize_motion_clip,
                        args=(frames_snap, meta_snap, measured_fps),
                        daemon=True,
                    ).start()
