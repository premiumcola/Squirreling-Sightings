from __future__ import annotations

# ruff: noqa: F401
# Comprehensive import block — some symbols are unused in this mixin
# but kept for parity so methods can be moved between mixins without
# import bookkeeping. Trim later if a mixin grows enough to warrant it.
import contextlib
import json as _json_mod
import logging
import os
import shutil as _shutil
import subprocess as _subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests

from ..detect_setup import apply_bottom_crop, apply_object_filter, make_spawn_for
from ..detection_confirmer import DetectionConfirmer
from ..detectors import (
    BirdSpeciesClassifier,
    CoralObjectDetector,
    Detection,
    WildlifeClassifier,
    draw_detections,
)
from ..event_logic import (
    choose_alarm_level,
    compute_severity_from_matrix,
    is_schedule_window_active,
    schedule_action_active,
)
from ._consts import (
    _FFMPEG_AVAILABLE,
    _PROFILE_PERIOD_DEFAULTS,
    _PROFILES,
    _SPECIES_TO_ACH_ID,
    _WILDLIFE_BBOX_DONORS,
    _bbox_iou,
    _refine_wildlife_bbox,
    _suppress_overlap,
    log,
    log_cam,
    log_tl,
)
from ._rescue import _confirmable_on_blob


class MainLoopMixin:
    """The per-camera orchestrator (_loop).

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (frame buffers, lock, config, etc.) which live on the concrete class.

    The D1/D2 rescue it calls lives next door in ``_rescue.RescueMixin``.
    """

    def _loop(self):
        if self.cfg.get("rtsp_url"):
            interval = max(
                0.05,
                float(
                    self.cfg.get("frame_interval_ms")
                    or self.global_cfg.get("processing", {})
                    .get("motion", {})
                    .get("frame_interval_ms", 150)
                )
                / 1000.0,
            )
        else:
            interval = max(1.0, float(self.cfg.get("snapshot_interval_s") or 3))
        cooldown = max(
            10, int(self.global_cfg.get("processing", {}).get("event_cooldown_seconds", 10))
        )

        # ── Watchdog: hard-kill a wedged capture handle ──────────────────
        # CAP_PROP_READ_TIMEOUT_MSEC isn't reliably honoured across every
        # OpenCV/FFmpeg build — some combos still block forever on a dead
        # TCP half-open. The watchdog releases the capture after 20 s of
        # silence so the next loop iteration is guaranteed to enter the
        # reconnect branch via self.capture becoming None / not-opened.
        # Updated on every successful frame inside the loop below.
        self._last_activity = time.time()

        def _watchdog():
            while self.running:
                time.sleep(10.0)
                if not self.running:
                    return
                if self.cfg.get("rtsp_url") and (time.time() - self._last_activity) > 20:
                    log_cam.warning(
                        "[%s] watchdog: capture silent >20s, requesting reconnect", self.camera_id
                    )
                    # Hand off to the main loop — calling release() from
                    # this thread races against the main-loop's read()
                    # and segfaults libav on corrupt HEVC streams (exit
                    # 139). The main loop already handles _force_reconnect
                    # at the top of every iteration.
                    self._force_reconnect = True
                    self._last_activity = time.time()

        threading.Thread(target=_watchdog, daemon=True, name=f"cam-wd-{self.camera_id}").start()

        while self.running:
            # Timelapse threads may request a forced reconnect when they detect a stale stream
            if self._force_reconnect:
                self._force_reconnect = False
                self._stale_streak = 0
                log_cam.warning(
                    "[cam:%s] forced reconnect — stale-feed recovery "
                    "(stale_streak=%d, last_frame_age=%.0fs, reconnects_24h=%d)",
                    self.camera_id,
                    self._stale_streak,
                    (time.time() - self.frame_ts) if self.frame_ts > 0 else 0,
                    self._reconnect_count_24h(),
                )
                try:
                    if self.capture is not None:
                        self.capture.release()
                except Exception:
                    pass
                self.capture = None
                self._reconnect_count += 1
                self._reconnect_log.append(time.time())
                time.sleep(2.0)
                continue
            try:
                frame = self._grab_frame()
                # Always store raw frame so status → "active" and snapshots work.
                # Also update the inter-frame EMA so the test-detection
                # endpoint can spot a decoder backlog (frames arriving
                # faster than the camera's configured cadence = bursting
                # a buffer, not real-time). EMA is wall-clock so it
                # tracks decode arrivals, not capture timing.
                _now_grab = time.time()
                with self.lock:
                    prev_ts = self.frame_ts
                    self.frame = frame
                    self.frame_ts = _now_grab
                    if prev_ts > 0:
                        delta_ms = (_now_grab - prev_ts) * 1000.0
                        # Filter spurious "reconnect gap" deltas: any
                        # interval > 30 s reflects an outage, not a
                        # capture cadence, and would yank the EMA up
                        # for thousands of subsequent frames if we let
                        # it in. Treat it as a reset.
                        if delta_ms > 30_000:
                            self._frame_interval_ema_ms = 0.0
                        elif self._frame_interval_ema_ms <= 0:
                            self._frame_interval_ema_ms = delta_ms
                        else:
                            self._frame_interval_ema_ms = (
                                0.9 * self._frame_interval_ema_ms + 0.1 * delta_ms
                            )
                # First decoded frame after an open() — log latency so the
                # operator can confirm a reconnect actually recovered the
                # stream. Only fires once per open cycle.
                if self._rtsp_opened_at and not self._rtsp_first_frame_logged:
                    latency_ms = int((time.time() - self._rtsp_opened_at) * 1000)
                    masked = self._masked_rtsp_url()
                    log_cam.info(
                        "[cam:%s] RTSP opened — %s · first frame in %d ms",
                        self.camera_id,
                        masked,
                        latency_ms,
                    )
                    self._rtsp_first_frame_logged = True
                    self._last_rtsp_success_ts = time.time()
                # Feed the watchdog — any successful grab resets the silence clock.
                self._last_activity = time.time()
                if self._error_streak > 0:
                    downtime_s = int(
                        time.time()
                        - (self._last_rtsp_success_ts or self._rtsp_opened_at or time.time())
                    )
                    log_cam.info(
                        "[cam:%s] frame flow recovered after %d errors (downtime≈%ds)",
                        self.camera_id,
                        self._error_streak,
                        downtime_s,
                    )
                self.last_error = None
                self._error_streak = 0
                # The detection configuration, resolved ONCE per runtime in
                # __init__ (beside self._tracker, off the same config) —
                # never per frame. Every camera-config change restarts the
                # runtime via server.restart_single_camera, so a per-frame
                # rebuild allocated a frozen dataclass, two dict copies, a
                # frozenset and a resolve_track_thresholds call ~20×/s
                # across three cameras for values that cannot have changed.
                setup = self.detect_setup
                # Apply bottom crop before processing (removes corrupt H.264 bottom strip)
                proc_frame = apply_bottom_crop(frame, setup.bottom_crop_px)
                # Skip frames with corrupt bottom strip (high-saturation codec artifact)
                if self._has_corrupt_strip(proc_frame):
                    log.debug("[%s] corrupt strip detected, frame skipped", self.camera_id)
                    time.sleep(interval)
                    continue
                # Quality gate: skip corrupt/uniform/artifact frames for events only
                if not self._is_frame_valid(proc_frame):
                    if self._recording:
                        self._rec_corrupt_frames += 1
                    time.sleep(interval)
                    continue
                # Stream warmup: ignore first 3 s after connect to skip transition frames
                if self.connect_time and time.time() - self.connect_time < 3.0:
                    time.sleep(interval)
                    continue
                motion_labels, motion_bbox, wildlife_motion_low, wl_blobs = self._motion_detect(
                    proc_frame
                )
                # D1 · feed the wildlife-low blobs to the cross-frame
                # MotionBlobTracker and ask whether any shows COHERENT net
                # translation (a real animal crossing) vs in-place shimmer
                # (wind). Only a coherent blob is allowed to escalate to the
                # D2 ROI/tiling re-detection further down. Per-camera tunable
                # min net-displacement fraction (D3); falls back to the
                # conservative module default when unset.
                self._blob_tracker.update(wl_blobs)
                _min_net = self.cfg.get("roi_min_net_disp_frac")
                if _min_net:
                    _coherent_blob = self._blob_tracker.coherent_track(
                        proc_frame.shape[1], min_net_frac=float(_min_net)
                    )
                else:
                    _coherent_blob = self._blob_tracker.coherent_track(proc_frame.shape[1])
                # Multi-frame confirmation: only trigger on motion in ≥2 of last 3 frames.
                # Two parallel deques — one for the regular threshold (which gates
                # event recording + COCO) and one for the lower wildlife threshold
                # (which extends the gate for the wildlife classifier only).
                self._motion_confirm.append(1 if motion_labels else 0)
                # Wildlife deque counts BOTH normal motion and wildlife-only motion;
                # wildlife is by definition more sensitive, so anything that
                # registers as normal motion must also register as wildlife motion.
                self._motion_confirm_wl.append(1 if (motion_labels or wildlife_motion_low) else 0)
                motion_confirmed = sum(self._motion_confirm) >= 2
                wlmotion_confirmed = sum(self._motion_confirm_wl) >= 2
                wildlife_motion_only = wlmotion_confirmed and not motion_confirmed
                effective_motion = motion_labels if motion_confirmed else []
                effective_bbox = motion_bbox if motion_confirmed else None
                # Per-label confidence overrides (e.g. {"person": 0.72}).
                # In the two-tier tracker design these become the SPAWN
                # floor for that label — a "person" detection below 0.72
                # can still EXTEND an existing person-track (continuation)
                # via the tracker's tentative-tier path. Cold-start
                # gating still happens here because the confirmer's 3-of-5s
                # rule trumps the tracker for fresh sightings.
                label_thresholds = setup.label_thresholds or None
                _t0 = time.time()
                # Pull EVERY hit above the tracker's continuation floor —
                # the tracker classifies them into confirmed (≥ spawn) vs
                # tentative (floor ≤ score < spawn) downstream. Per-camera
                # detection_min_score is no longer the live cutoff — it
                # would defeat the point of the tracker's two-tier flow.
                raw_detections = self.detector.detect_frame_raw(
                    proc_frame,
                    threshold=setup.floor,
                )
                # Rolling-average Coral inference latency for the /status
                # bubble. Cost is unchanged from detect_frame() — same
                # underlying invoke; only the post-filter threshold differs.
                self._inference_times_ms.append((time.time() - _t0) * 1000.0)
                _fh_px, _fw_px = proc_frame.shape[:2]
                allowed = setup.object_filter
                excluded = setup.excluded_classes
                detections, _ = apply_object_filter(list(raw_detections), allowed, excluded)
                # Exclusion mask first: drop detections inside masked
                # regions before zone filtering or the tracker runs. A
                # tracked subject must NOT survive into a masked region.
                detections = self._filter_masked_detections(proc_frame, detections)
                # Inclusion zones next: if any zones are defined, keep
                # only detections whose centre lies inside a zone.
                # Masks + zones compose: detect inside zones BUT exclude
                # masked areas within zones.
                detections = self._filter_zoned_detections(proc_frame, detections)
                # ── Two-tier tracker thresholds ─────────────────────────
                # Classifies each surviving detection into confirmed
                # (≥ per-label spawn threshold) vs tentative (above floor,
                # below spawn). Confirmed dets can spawn or extend tracks;
                # tentative dets can only extend a still-unmatched IoU
                # partner. Subjects survive short low-conf dips while
                # genuine cold-start gating stays the confirmer's job.
                # Resolved BEFORE the rescue gate below, which needs the same
                # notion of "strong enough to be believed".
                spawn_for = make_spawn_for(label_thresholds, self._tracker.spawn_default)
                # ── D2 · ROI / tiling rescue ─────────────────────────────
                # D1 saw a coherent moving blob and the full-frame pass
                # produced nothing CONFIRMABLE on it — see
                # _confirmable_on_blob for why "nothing at all" was the
                # wrong question. The coherent blob is a precondition, but it
                # is NOT by itself a cost guard: it stays true for the whole
                # time a subject crosses the scene, and the "no confirmable
                # detection" half stays true precisely in the case this
                # exists for (COCO has no squirrel), so the two together
                # describe a state that persists for seconds, not an event.
                # Without the cooldown that is one magnified re-detect per
                # frame for the whole crossing. See _RESCUE_MIN_INTERVAL_S.
                det_mode = setup.det_mode
                if (
                    det_mode != "off"
                    and _coherent_blob is not None
                    and self._rescue_cooldown_ready(time.time())
                    and not _confirmable_on_blob(detections, _coherent_blob, spawn_for)
                ):
                    # Stamped on the attempt, not the hit: the cost this
                    # brake exists to bound is the inference, which is paid
                    # whether or not the rescue finds anything.
                    self._roi_rescue_last_ts = time.time()
                    detections = self._roi_rescue(
                        proc_frame, raw_detections, _coherent_blob, det_mode, allowed, excluded
                    )
                # Effective fps for grace-window math. Falls back to a
                # conservative 3 Hz when the rolling measurement hasn't
                # warmed up yet (first ~5 s of a camera's session).
                _eff_fps = max(1.0, float(getattr(self, "_main_fps", 0.0) or 3.0))
                detections = self._tracker.step(
                    detections,
                    t_s=time.monotonic(),
                    fps=_eff_fps,
                    spawn_for=spawn_for,
                    frame_w=_fw_px,
                    frame_h=_fh_px,
                )
                if log.isEnabledFor(logging.DEBUG) and detections:
                    log.debug(
                        "[%s] tracker: %d dets survived (active=%d)",
                        self.camera_id,
                        len(detections),
                        self._tracker.active_count(),
                    )
                labels = effective_motion + [d.label for d in detections]
                if self.bird_classifier.available:
                    for d in detections:
                        if d.label == "bird":
                            crop = self._crop(proc_frame, d.bbox)
                            species, species_latin, species_score = (
                                self.bird_classifier.classify_crop(crop)
                            )
                            if species:
                                d.species = species
                                d.species_latin = species_latin
                                d.species_score = (
                                    float(species_score) if species_score is not None else None
                                )
                # Wildlife second-stage (fox / squirrel / hedgehog — none of
                # which exist as a COCO class). Lives in _wildlife_stage.py;
                # it classifies a CROP around the motion box rather than the
                # whole frame, which is what the offline test panel always
                # did and the live path never did.
                detections, labels = self._apply_wildlife_stage(
                    proc_frame,
                    detections,
                    labels,
                    motion_confirmed=motion_confirmed,
                    wildlife_motion_only=wildlife_motion_only,
                    allowed=allowed,
                    effective_bbox=effective_bbox,
                )
                if self.cat_registry:
                    for d in detections:
                        if d.label == "cat":
                            crop = self._crop(proc_frame, d.bbox)
                            m = self.cat_registry.match_details(crop)
                            if m:
                                d.identity = m.get("name")
                if self.person_registry:
                    for d in detections:
                        if d.label == "person":
                            crop = self._crop(proc_frame, d.bbox)
                            m = self.person_registry.match_details(crop)
                            if m:
                                d.identity = m.get("name")
                drawn = draw_detections(proc_frame, detections)
                with self.lock:
                    self.preview = drawn
                # ── MAD glitch check vs previous accepted frame ───────────────
                if self.cfg.get("rtsp_url") and self._is_frame_too_different(
                    proc_frame, self._prev_good_frame
                ):
                    log.warning("[%s] Frame MAD>60 (glitch/corrupt), skipped", self.camera_id)
                    time.sleep(interval)
                    continue
                self._prev_good_frame = proc_frame  # no copy — proc_frame is already a new array

                confirmed_object_labels = self._confirmed_labels(detections, spawn_for)
                now_dt = datetime.now()
                # Per-camera trigger mode:
                #   motion_and_objects (default) — motion OR object fires event
                #   objects_only                 — motion alone ignored; objects
                #                                  still carry motion in metadata
                #   motion_only                  — only motion fires; objects
                #                                  are still labelled for metadata
                trigger_mode = self.cfg.get("detection_trigger", "motion_and_objects")
                # Trigger logic uses CONFIRMED labels only — unconfirmed
                # detections still appear in the preview overlay but do
                # not propagate to event recording / Telegram. The full
                # detections list is still written into the event meta
                # below so the saved JSON keeps the complete frame info.
                object_labels = list(confirmed_object_labels)
                if trigger_mode == "objects_only":
                    has_motion = bool(object_labels)
                    labels = sorted(set(effective_motion + object_labels)) if has_motion else []
                elif trigger_mode == "motion_only":
                    has_motion = bool(effective_motion)
                    labels = sorted(set(effective_motion + object_labels)) if has_motion else []
                else:
                    # motion_and_objects: motion alone OR confirmed object fires
                    has_motion = bool(effective_motion) or bool(object_labels)
                    labels = sorted(set(effective_motion + object_labels)) if has_motion else []

                # Per-camera recording schedule — outside the configured
                # window (or when recording_enabled is off entirely) we
                # still detect, but never start a new on-disk event.
                # In-progress recordings finalize normally (gate only fires
                # when has_motion AND we're not already recording).
                # New schedule_record dict gates by time window; the
                # recording_enabled toggle is the master record on/off.
                if has_motion and not self._recording:
                    # Both gates below used to `continue` in total silence.
                    # From the outside that is indistinguishable from "the
                    # camera saw nothing": no clip, no event, no library
                    # entry, no log. A user who walks past a camera at
                    # midday with a night-only recording schedule gets
                    # exactly the same evidence as a broken detector.
                    # Throttled to one line per minute per reason so a
                    # busy scene cannot flood the log.
                    _block = None
                    if not self.cfg.get("recording_enabled", True):
                        _block = "recording_enabled=False"
                    elif not is_schedule_window_active(self.cfg.get("schedule_record") or {}):
                        _sched = self.cfg.get("schedule_record") or {}
                        _block = (
                            f"schedule_record window={_sched.get('from', '?')}"
                            f"→{_sched.get('to', '?')} inactive"
                        )
                    if _block is not None:
                        _now_mono = time.monotonic()
                        if _now_mono - getattr(self, "_rec_block_logged_at", 0.0) > 60.0:
                            self._rec_block_logged_at = _now_mono
                            log.info(
                                "[trigger][cam:%s] motion seen (labels=%s) but NOT recording: %s",
                                self.camera_id,
                                ",".join(sorted(set(labels))) or "—",
                                _block,
                            )
                        time.sleep(interval)
                        continue

                if self.cfg.get("rtsp_url"):
                    if self._rtsp_recording_step(
                        proc_frame=proc_frame,
                        now_dt=now_dt,
                        has_motion=has_motion,
                        labels=labels,
                        detections=detections,
                        drawn=drawn,
                        effective_bbox=effective_bbox,
                        cooldown=cooldown,
                    ):
                        continue
                else:
                    # ── Snapshot camera: save JPEG event ──────────────────────
                    self._save_snapshot_event(
                        now_dt, labels, detections, drawn, effective_bbox, cooldown
                    )
                self.last_error = None
            except Exception as e:
                self._handle_loop_error(e)
            time.sleep(interval)
