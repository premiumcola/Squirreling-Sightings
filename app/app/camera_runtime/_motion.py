from __future__ import annotations

# ruff: noqa: F401
# Comprehensive import block — some symbols are unused in this mixin
# but kept for parity so methods can be moved between mixins without
# import bookkeeping. Trim later if a mixin grows enough to warrant it.
import json as _json_mod
import logging
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
from ._clip_tally import rank_headline_species
from ._clip_tally import single_frame_summary as _first_frame_clip_block
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


def _resolve_bird_species(detections: list) -> str | None:
    """Event-level `bird_species` aggregate for `_build_event_meta`:
    rarest-or-never-recorded-first among every bird detection's species
    in THIS frame — see bird_species_rank.py::pick_headline_species for
    the rule shared with the offline backfill sweep.

    Frame-scoped by construction: this runs while a single frame's
    detections are in hand and is what opens an event. The whole-clip
    answer accumulates as the clip records and re-decides the same field
    through the same ranking rule — see `_clip_tally.ClipTally` and
    `_recording_step.RecordingStepMixin._absorb_clip_frame`.
    """
    return rank_headline_species(
        [(d.species, d.species_latin) for d in detections if d.label == "bird" and d.species]
    )


def _refresh_bird_species(meta: dict, detections: list, tally=None) -> None:
    """Re-derive `meta["bird_species"]` after `_upgrade_event_meta` has
    replaced the detections it was originally computed from.

    Prefers the clip's accumulated candidates when a `ClipTally` is in
    flight, and falls back to the passed frame's when there is none (a
    snapshot camera, or a direct unit-test call). Without that
    preference this would be a REGRESSION rather than a refresh: the
    upgrade runs on a single later frame, so re-ranking over that frame
    alone would throw away the whole-clip evidence
    `_recording_step._absorb_clip_frame` had already folded in and hand
    the headline back to a one-frame decision.

    `_build_event_meta` derives the headline from the ONE frame where
    recording started. The upgrade then swaps `meta["detections"]` for a
    later frame's, and without this the derived aggregate kept pointing
    at the old list — so an event could name a bird its own stored
    detections no longer contained or, far more often, carry no name at
    all while the species sat right there in the detection.

    That second case is the common path, not a corner: motion confirms in
    ~0.7 s and a class in ~1.05 s, so a bird event usually opens as
    `labels=["motion"]` with no bird detection yet, and the bird arrives
    on the upgrade. Nothing repaired it later either —
    bird_species_backfill.py::_needs_backfill only selects events whose
    bird detection is MISSING `species`, so an event with a classified
    detection and an empty headline was invisible to that sweep.

    Only overwrites when the new detections actually yield a species: a
    later birdless frame must not blank a name the event already won.

    Module-level rather than a mixin method because it needs no `self`,
    which also keeps `_upgrade_event_meta` under the 80-line ceiling.
    """
    candidates = tally.headline_candidates() if tally is not None else None
    species = rank_headline_species(candidates) if candidates else _resolve_bird_species(detections)
    if species:
        meta["bird_species"] = species


class MotionMixin:
    """Background-subtractor motion detection + event metadata builder.

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (frame buffers, lock, config, etc.) which live on the concrete class.
    """

    def _motion_detect(self, frame):
        """Returns (labels, motion_bbox, wildlife_motion_low, wl_blobs).
        - labels: ["motion"] when normal-threshold motion fired, else [].
        - motion_bbox: (x, y, w, h) union rect of normal-motion contours, or None.
        - wildlife_motion_low: True when only the lower wildlife area floor fired.
        - wl_blobs: per-blob [{bbox, solidity}] for the wildlife-low contours,
          fed to the D1 MotionBlobTracker for coherent-motion escalation.
        Applies per-camera exclusion masks and motion_sensitivity threshold.
        Brightness-normalises both frames before diff to suppress cloud/sun transitions."""
        # Per-camera kill-switch — skips all motion work (saves CPU when
        # the camera is in objects-only mode).
        if not self.cfg.get("motion_enabled", True):
            return [], None, False, []
        proc = self.global_cfg.get("processing", {}).get("motion", {})
        if not proc.get("enabled", True):
            return [], None, False, []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_size = int(proc.get("blur_size", 15))
        if blur_size % 2 == 0:
            blur_size += 1
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        # Reset if frame dimensions changed (e.g. bottom_crop_px config change)
        if self.prev_gray is not None and self.prev_gray.shape != gray.shape:
            self.prev_gray = None
        if self.prev_gray is None:
            self.prev_gray = gray
            return [], None, False, []
        # Brightness normalisation: scale current frame to match previous mean so that
        # gradual global illumination changes (clouds, day/night) don't produce diff.
        mean_prev = float(np.mean(self.prev_gray))
        mean_curr = float(np.mean(gray))
        if mean_curr > 1:
            scale = mean_prev / mean_curr
            if 0.5 < scale < 2.0:  # only correct moderate shifts; ignore extreme jumps
                gray = np.clip(gray.astype(np.float32) * scale, 0, 255).astype(np.uint8)
        diff = cv2.absdiff(self.prev_gray, gray)
        self.prev_gray = gray
        _, thresh = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
        thresh = cv2.dilate(thresh, None, iterations=2)
        # Apply camera exclusion masks: zero out masked regions. Reuses
        # the cached mask image (_ensure_mask_image() rebuilds only on
        # signature changes) so this stays cheap per frame.
        self._ensure_mask_image()
        if self._mask_image is not None:
            h_t, w_t = thresh.shape[:2]
            if self._mask_image.shape[:2] != (h_t, w_t):
                mask_resized = cv2.resize(
                    self._mask_image, (w_t, h_t), interpolation=cv2.INTER_NEAREST
                )
            else:
                mask_resized = self._mask_image
            thresh = cv2.bitwise_and(thresh, mask_resized)
        # Apply inclusion zones — keep only motion that happens inside at
        # least one zone. The cached _zone_image is None when no zones are
        # configured, in which case this is a no-op.
        self._ensure_zone_image()
        if self._zone_image is not None:
            h_t, w_t = thresh.shape[:2]
            if self._zone_image.shape[:2] != (h_t, w_t):
                zone_resized = cv2.resize(
                    self._zone_image, (w_t, h_t), interpolation=cv2.INTER_NEAREST
                )
            else:
                zone_resized = self._zone_image
            thresh = cv2.bitwise_and(thresh, zone_resized)
        # Per-camera sensitivity → scales minimum contour area
        sensitivity = self.cfg.get("motion_sensitivity")
        h_f, w_f = frame.shape[:2]
        frame_area = h_f * w_f
        base_min_area = frame_area * 0.005
        if sensitivity is not None:
            sensitivity = float(sensitivity)
            min_area = int(base_min_area / max(0.1, sensitivity))
        else:
            min_area = int(proc.get("min_area", 3000))
        # Wildlife uses a parallel, more sensitive threshold so small animals
        # (squirrel/fox/hedgehog/distant cat+dog) can wake the wildlife stage
        # even when the normal motion gate doesn't fire. 0.0 = "auto" → 1.4×
        # the normal sensitivity. D1 · the base fraction is now 0.001 (was
        # 0.005) so animal-sized blobs (~11 k px ≈ 0.3 % of a 2560×1440 frame,
        # B4) clear the floor — the old ~18 k floor missed them. A LOW area
        # floor is safe because the D1 motion-blob tracker (coherent net
        # translation) is the real wind filter, not area. The cap is 3.0 so a
        # per-camera wildlife_motion_sensitivity can push the floor lower.
        wl_sens = self.cfg.get("wildlife_motion_sensitivity")
        if wl_sens is None or float(wl_sens) <= 0.0:
            base_sens = float(sensitivity) if sensitivity is not None else 0.5
            wl_sens = min(3.0, base_sens * 1.4)
        else:
            wl_sens = min(3.0, max(0.1, float(wl_sens)))
        wl_min_area = int(frame_area * 0.001 / max(0.1, wl_sens))
        # Cheap early-out before findContours: if fewer pixels changed in the
        # WHOLE frame than the smallest contour we would accept, no contour can
        # clear either floor and the contour pass is wasted work.
        #
        # This used to be a flat 0.5 % of the frame — 18 432 px on 2560x1440 —
        # which is 3.5x the wildlife floor above (5 266 px at the default
        # sensitivity). It was therefore not an early-out at all but a hidden
        # third threshold that silently overrode both configured ones: an
        # 11 000 px squirrel at the feeder cleared `wl_min_area` and was
        # rejected here regardless, so the wildlife stage was never even
        # offered the blob. Deriving the floor from the two real thresholds
        # also makes the pre-check per-camera for free, via the existing
        # `motion_sensitivity` / `wildlife_motion_sensitivity` knobs. A camera
        # that wants the old, deafer behaviour back sets
        # wildlife_motion_sensitivity=0.2, which puts wl_min_area at exactly
        # the old 18 432 px.
        #
        # Not quite "can only skip work, never change a verdict": `contourArea`
        # is the area of the enclosing polygon, so an annular blob (a moving
        # outline around a static centre) can report an area larger than its
        # own changed-pixel count and clear a floor this pre-check already
        # rejected. That gap is a small fraction of the one the flat 0.5 %
        # floor opened, but it is not zero and should not be claimed as zero.
        change_floor = max(1, min(int(min_area), int(wl_min_area)))
        if int(np.sum(thresh > 0)) < change_floor:
            return [], None, False, []
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # Two parallel checks against the same contour set — cheap.
        big_normal = [c for c in contours if cv2.contourArea(c) >= min_area]
        big_wl = [c for c in contours if cv2.contourArea(c) >= wl_min_area]
        wildlife_motion_low = bool(big_wl) and not big_normal
        # D1 · per-blob features for the wildlife-low blobs, fed to the
        # cross-frame MotionBlobTracker so it can measure net translation
        # (animal) vs in-place shimmer (wind). solidity = area / convex-hull
        # area is carried as a cheap support signal.
        wl_blobs = []
        for c in big_wl:
            a = float(cv2.contourArea(c))
            ha = float(cv2.contourArea(cv2.convexHull(c))) or 1.0
            wl_blobs.append(
                {
                    "bbox": tuple(int(v) for v in cv2.boundingRect(c)),
                    "solidity": round(a / ha, 3),
                }
            )
        if not big_normal:
            # Normal motion didn't trigger — but tell the caller whether the
            # lower wildlife threshold did (+ the wildlife blobs) so the
            # wildlife stage + the D1/D2 escalation can still run. No
            # labels/bbox returned in this case (no normal-motion event).
            return [], None, wildlife_motion_low, wl_blobs
        all_pts = np.concatenate(big_normal)
        bbox = cv2.boundingRect(all_pts)
        return ["motion"], bbox, wildlife_motion_low, wl_blobs

    def _crop(self, frame, bbox):
        x1, y1, x2, y2 = bbox
        return frame[max(0, y1) : max(0, y2), max(0, x1) : max(0, x2)]

    def _upgrade_event_meta(self, labels: list, detections: list) -> bool:
        """Fold late-confirming labels into the in-flight event.

        The event's labels used to be frozen at recording start and never
        revisited — and that start is decided by MOTION, which confirms
        far sooner than a class does. Motion needs 2 of 3 frames (~0.7 s
        at the 350 ms cadence); a person needs 3 hits in 5 s (~1.05 s).
        Motion therefore wins the race almost every time, the event is
        filed as ``labels=["motion"]``, and every downstream decision
        reads that: `motion` is `off` in the severity matrix and
        `push:false` in the push config, so the alert is dropped for a
        clip that plainly shows a person.

        The tell was visible in the event JSON all along — `top_label`
        was built from the *unconfirmed* detections, so events read
        `top_label: "person"` next to `labels: ["motion"]`.

        Returns True when something actually changed, so the caller can
        decide whether to rewrite the stub on disk.
        """
        meta = self._rec_event_meta
        if not meta or not labels:
            return False
        known = set(meta.get("labels") or [])
        fresh = {lbl for lbl in labels if lbl and lbl != "motion"}
        if not fresh - known:
            return False

        merged = sorted((known | fresh) - {"motion"}) or sorted(known | fresh)
        meta["labels"] = merged
        if detections:
            top = max(detections, key=lambda d: d.score, default=None)
            if top is not None:
                meta["top_label"] = top.label
                meta["detections"] = [d.to_dict() for d in detections]
                _refresh_bird_species(meta, detections, getattr(self, "_clip_tally", None))
        elif merged:
            meta["top_label"] = merged[0]

        # Re-run the severity decision on the corrected label set. Skipping
        # this would leave the event carrying "person" while still holding
        # motion's `notify=False`, which is the same silent drop wearing a
        # better label.
        whitelisted = bool(meta.get("whitelisted"))
        profile = (self.cfg.get("alarm_profile") or "").strip().lower()
        # The meta stores this under "after_hours" (see _build_event_meta);
        # reading a "hard_active" key here would silently always be False
        # and quietly downgrade every night-time event.
        hard_active = bool(meta.get("after_hours"))
        level, notify = choose_alarm_level(profile, merged, hard_active, whitelisted)
        class_severity_cfg = self.cfg.get("class_severity") or {}
        if class_severity_cfg and not whitelisted:
            severity = compute_severity_from_matrix(class_severity_cfg, merged)
            notify = severity != "off"
        else:
            severity = "alarm" if level == "alarm" else ("info" if notify else "off")
        if whitelisted or not self.cfg.get("armed", True):
            notify = False
        meta["alarm_level"] = level
        meta["severity"] = severity
        meta["notify"] = notify
        log.info(
            "[trigger][cam:%s] event %s upgraded: labels=%s top=%s severity=%s notify=%s",
            self.camera_id,
            meta.get("event_id"),
            ",".join(merged),
            meta.get("top_label"),
            severity,
            notify,
        )
        return True

    def _build_event_meta(
        self, ts: datetime, labels: list, detections: list, drawn_frame, effective_bbox
    ) -> dict:
        """Snapshot of all event metadata at the moment motion recording starts."""
        event_id = ts.strftime("%Y%m%d-%H%M%S-%f")
        top_det = max(detections, key=lambda d: d.score, default=None)
        cat_match = next((d.identity for d in detections if d.label == "cat" and d.identity), None)
        person_match = next(
            (d.identity for d in detections if d.label == "person" and d.identity), None
        )
        bird_species = _resolve_bird_species(detections)
        sched = self.cfg.get("schedule") or {}
        # "Hart-Modus" — when active, person → alarm regardless of profile.
        # When the schedule is disabled this is treated as 24/7 active so a
        # user with no schedule still gets the historic person→alarm
        # promotion via choose_alarm_level's profile rules.
        hard_active = schedule_action_active(sched, "hard")
        whitelisted = bool(
            person_match and (person_match in (self.cfg.get("whitelist_names") or []))
        )
        if self.person_registry and person_match:
            p = self.person_registry.get_profile(person_match) or {}
            whitelisted = whitelisted or bool(p.get("whitelisted"))
        profile = (self.cfg.get("alarm_profile") or "").strip() or "soft"
        level, notify = choose_alarm_level(
            profile, list(sorted(set(labels))), hard_active, whitelisted
        )
        # Per-class severity matrix — new source of truth. When the
        # camera carries a non-empty class_severity dict, the matrix
        # overrides the legacy alarm_profile-derived notify decision:
        # severity=alarm/info → notify=True (route to push), severity=
        # off → notify=False (skip). Whitelisted detections still
        # short-circuit notification regardless of severity.
        class_severity_cfg = self.cfg.get("class_severity") or {}
        if class_severity_cfg and not whitelisted:
            severity = compute_severity_from_matrix(
                class_severity_cfg,
                list(sorted(set(labels))),
            )
            notify = severity != "off"
        else:
            # Fall back to deriving severity from the legacy decision so
            # downstream consumers (telegram_bot silent kwarg, MQTT
            # event payload) always have a value to read.
            severity = "alarm" if level == "alarm" else ("info" if notify else "off")
        # "Stumm" kill-switch: armed=false suppresses all Telegram alerts
        # but keeps the event recording and archive path intact.
        if not self.cfg.get("armed", True):
            notify = False
        # Encode thumbnail for Telegram (in memory, never written as JPEG to disk)
        thumb_bytes = None
        if drawn_frame is not None:
            save_thumb = drawn_frame.copy()
            if effective_bbox is not None:
                mx, my, mw, mh = effective_bbox
                cv2.rectangle(save_thumb, (mx, my), (mx + mw, my + mh), (0, 220, 0), 2)
            h_px, w_px = save_thumb.shape[:2]
            if w_px > 1280:
                scale = 1280 / w_px
                save_thumb = cv2.resize(
                    save_thumb, (1280, int(h_px * scale)), interpolation=cv2.INTER_AREA
                )
            ok, buf = cv2.imencode('.jpg', save_thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                thumb_bytes = buf.tobytes()
        # Aggregate per-zone trigger flags across all surviving detections.
        # OR-rule: if ANY detection sits in a zone that allows snapshot/
        # video/telegram, the event keeps that channel on. A detection
        # without zone_flags (no zones configured, or motion-only event)
        # contributes True for all three — preserves legacy behaviour.
        ev_save_photo = False
        ev_save_video = False
        ev_send_tg = False
        any_with_flags = False
        for d in detections:
            f = getattr(d, "zone_flags", None)
            if f is None:
                ev_save_photo = ev_save_video = ev_send_tg = True
            else:
                any_with_flags = True
                if f.get("save_photo", True):
                    ev_save_photo = True
                if f.get("save_video", True):
                    ev_save_video = True
                if f.get("send_telegram", True):
                    ev_send_tg = True
        if not any_with_flags and not detections:
            # Motion-only event: keep legacy defaults.
            ev_save_photo = ev_save_video = ev_send_tg = True
        # Feed the live-tile red-glow indicator. We use the
        # surviving `labels` list (post-whitelist, post-zone,
        # post-confidence, post-confirm) so the UI only lights up
        # on detections the pipeline actually treats as real
        # events. Time is epoch seconds for cheap age-comparison
        # in routes/cameras.py.
        now_epoch = time.time()
        for lbl in sorted(set(labels)):
            self.recent_detections.append((lbl, now_epoch))
        return {
            "event_id": event_id,
            "time": ts,
            "labels": sorted(set(labels)),
            "top_label": top_det.label if top_det else labels[0],
            # The TRIGGER frame — the one tick that opened this event.
            # Deliberately still a single frame: every archived event
            # holds exactly this, and the Mediathek overlay, the
            # player's object-list fallback and the replay's "before"
            # side all read it as one. `whole_clip` below is the
            # accumulated answer; this is the moment of the decision.
            "detections": [d.to_dict() for d in detections],
            # Everything the pipeline recognised across the WHOLE clip,
            # accumulated per tracker track while the clip records — see
            # `_clip_tally.ClipTally`. Opens as the trigger frame's own
            # content so a clip that ends on its first tick still says
            # something true, and is replaced by the running aggregate
            # from the first `_absorb_clip_frame` onward. Snapshot events
            # have no clip and keep exactly this.
            "whole_clip": _first_frame_clip_block(detections),
            "bird_species": bird_species,
            "cat_name": cat_match,
            "person_name": person_match,
            "whitelisted": whitelisted,
            "alarm_level": level,
            # New severity field driven by the class_severity matrix. The
            # notifier reads this to pick silent vs. loud Telegram pushes
            # ("info" → silent, "alarm" → loud) and MQTT publishes it as
            # part of the event payload so Home Assistant can route by
            # severity. Falls back to a legacy-derived value when the
            # matrix is empty so consumers always have a non-empty key.
            "severity": severity,
            # `after_hours` historically meant "alerting schedule active"; we
            # keep the key for read-side compatibility (event JSONs already on
            # disk) but its value is now the schedule's hard-mode gate.
            "after_hours": hard_active,
            "notify": notify,
            "thumb_bytes": thumb_bytes,
            # Per-event recording switches derived from zone trigger flags.
            "save_photo": ev_save_photo,
            "save_video": ev_save_video,
            "send_telegram": ev_send_tg,
        }
