from __future__ import annotations

# ruff: noqa: F401
# Comprehensive per-mixin import block — some symbols are unused in this
# mixin but kept identical across mixins so methods can move between them
# without import bookkeeping. See service.py for the canonical import list.
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from ._consts import (
    EVENT_ICON_HEX,
    EVENT_LABEL_DE,
    HISTORY_FIELD_TO_EVENT,
    HISTORY_FIELDS,
    HISTORY_LABELS_DE,
    HISTORY_MAXLEN,
    HISTORY_UNITS,
    _atomic_write_json,
    _is_quiet_now,
    _safe_dt,
    _safe_subset,
    log,
)
from ._event_tl_detect import EventTLDetectorsMixin
from ._event_tl_encode import EventTLEncodeMixin
from ._event_tl_prebuf import EventTLPrebufferMixin


class EventTimelapseMixin(EventTLDetectorsMixin, EventTLPrebufferMixin, EventTLEncodeMixin):
    """Weather-event-driven timelapse capture (thunder rising / front passing / storm front).

    Mixin for WeatherService. Methods access shared state via `self.*`
    (cfg, runtimes, settings_store, scheduler, etc.) which live on the
    concrete class.

    Composition:
      * ``EventTLDetectorsMixin`` — the forecast trigger + watch predicates.
      * ``EventTLPrebufferMixin`` — the pre-roll ring buffer lifecycle.
      * ``EventTLEncodeMixin``    — encode, manifest, Telegram handover.
      * this class — trigger gating and the capture loop.
    """

    def _latest_api_snapshot_safe(self) -> dict:
        """Best-effort fetch of the latest 15-minute API slot. Used by the
        sun capture so the manifest carries the actual sky conditions."""
        try:
            loc = self.server_cfg.get("location") or {}
            lat, lon = loc.get("lat"), loc.get("lon")
            if lat is None or lon is None:
                return {}
            api = self.cfg.get("api") or {}
            url = api.get("base_url") or "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "minutely_15": "precipitation,snowfall,weather_code,lightning_potential,visibility,wind_gusts_10m,cloud_cover",
                "timezone": api.get("timezone") or "Europe/Berlin",
                "models": api.get("model") or "icon_d2",
            }
            r = requests.get(url, params=params, timeout=8)
            if r.status_code != 200:
                return {}
            return self._latest_slice(r.json())
        except Exception:
            return {}

    # ── Wetter-Ereignis-Timelapse ───────────────────────────────────────────

    # 4 h cross-trigger cooldown per camera, plus a per-day cap of 2.
    # Both keep the system from carpet-bombing the user with 60-min
    # timelapses during an active weather day.
    _EVENT_TL_COOLDOWN_S: int = 4 * 3600
    _EVENT_TL_DAILY_CAP: int = 2

    def _event_tl_state(self) -> dict:
        # Lazy attr — keeps __init__ unchanged.
        if not hasattr(self, "_event_tl_state_dict"):
            self._event_tl_state_dict = {
                "last_trigger_ts": {},  # cam_id -> unix ts (any-trigger 4h cooldown)
                "daily_count": {},  # (cam_id, "YYYY-MM-DD") -> int
            }
        return self._event_tl_state_dict

    def _event_tl_cooldown_active(self, cam_id: str) -> tuple[bool, int]:
        """Return (in_cooldown, minutes_remaining)."""
        st = self._event_tl_state()
        last = st["last_trigger_ts"].get(cam_id, 0.0)
        elapsed = time.time() - last
        if elapsed < self._EVENT_TL_COOLDOWN_S:
            return True, int((self._EVENT_TL_COOLDOWN_S - elapsed) // 60) + 1
        return False, 0

    def _event_tl_daily_cap_hit(self, cam_id: str) -> bool:
        st = self._event_tl_state()
        key = (cam_id, date.today().isoformat())
        return st["daily_count"].get(key, 0) >= self._EVENT_TL_DAILY_CAP

    def _event_tl_record_trigger(self, cam_id: str):
        st = self._event_tl_state()
        st["last_trigger_ts"][cam_id] = time.time()
        key = (cam_id, date.today().isoformat())
        st["daily_count"][key] = st["daily_count"].get(key, 0) + 1

    def _event_tl_gate(self, cam_id: str, slices: list, evt_cfg: dict) -> list:
        """Cooldown + daily-cap gate. Returns the trigger list when the
        camera may fire, [] otherwise. Logging only happens when a
        detector would HAVE fired, so a quiet week doesn't fill the log
        with "cooldown active" every 5-minute poll."""
        in_cd, mins = self._event_tl_cooldown_active(cam_id)
        if in_cd:
            fired = self._evaluate_event_tl_detectors(slices, evt_cfg)
            if fired:
                log.info(
                    "[weather] Cooldown active (%dh %02dmin remaining) — %s skipped on %s",
                    mins // 60,
                    mins % 60,
                    fired[0][0],
                    self._cam_name(cam_id),
                )
            return []
        if self._event_tl_daily_cap_hit(cam_id):
            fired = self._evaluate_event_tl_detectors(slices, evt_cfg)
            if fired:
                log.info(
                    "[weather] Daily limit reached (%d/day), skipping %s on %s",
                    self._EVENT_TL_DAILY_CAP,
                    fired[0][0],
                    self._cam_name(cam_id),
                )
            return []
        return self._evaluate_event_tl_detectors(slices, evt_cfg)

    def _check_event_tl_triggers(self, payload: dict):
        """Evaluate the 3 event-tl triggers per opted-in camera. Anyone that
        fires arms the cross-trigger cooldown (so the OTHER triggers also
        get blocked for 4 h) and increments the daily counter.

        Also the drive shaft for the pre-roll rings: the same slices that
        decide "capture now" decide "keep a ring rolling", and the sync
        runs first so a camera whose opt-in was just revoked has its ring
        purged even when no trigger fires this cycle."""
        slices = self._slices_window(payload, past_min=60, future_min=180)
        try:
            self._sync_event_tl_rings(slices)
        except Exception as e:
            log.warning("[weather] prebuffer sync failed: %s", e)
        if not slices:
            return
        for cam in self._cfg_cameras():
            cam_id = cam.get("id")
            cw = cam.get("weather") or {}
            evt_cfg = cw.get("event_timelapse") or {}
            if not cw.get("enabled") or not evt_cfg.get("enabled"):
                continue
            triggers = self._event_tl_gate(cam_id, slices, evt_cfg)
            if not triggers:
                continue
            # Fire the FIRST matching trigger — once per cam per cycle.
            trig_kind, score, fc_snapshot = triggers[0]
            if not self._event_tl_claim_capture(cam_id):
                log.info(
                    "[weather] %s on %s skipped — capture already running",
                    trig_kind,
                    self._cam_name(cam_id),
                )
                continue
            self._event_tl_record_trigger(cam_id)
            window_min = int(evt_cfg.get("window_min", 60) or 60)
            interval_s = max(1, int(evt_cfg.get("interval_s", 6) or 6))
            fps = max(1, int(evt_cfg.get("fps", 24) or 24))
            log.info(
                "[weather] %s on %s · score=%.2f · capture starting (%d min, %ds-Intervall, %d fps)",
                trig_kind,
                self._cam_name(cam_id),
                score,
                window_min,
                interval_s,
                fps,
            )
            threading.Thread(
                target=self._run_event_tl_capture,
                args=(
                    cam_id,
                    trig_kind,
                    score,
                    slices[0] if slices else {},
                    fc_snapshot,
                    window_min,
                    interval_s,
                    fps,
                ),
                daemon=True,
                name=f"weather-evt-tl-{cam_id}-{trig_kind}",
            ).start()

    def _run_event_tl_capture(
        self,
        cam_id: str,
        trigger: str,
        score: float,
        api_now: dict,
        fc_snapshot: dict,
        window_min: int,
        interval_s: int,
        fps: int,
    ):
        """Splice the retained pre-roll onto a fresh forward capture, then
        encode. The claim taken in `_check_event_tl_triggers` is released
        here in every exit path — a leaked claim would freeze the ring for
        that camera until the next service reload."""
        rt = self.runtimes.get(cam_id)
        if rt is None or not hasattr(rt, "snapshot_jpeg_hires"):
            log.warning("[weather] cam %s nicht verfügbar — capture abgebrochen", cam_id)
            self._event_tl_release_capture(cam_id)
            return
        cam_name = self._cam_name(cam_id)
        out_dir = self._sightings_dir() / cam_id / "event_timelapse"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts_label = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        # Camera slug appended so cross-camera downloads stay unique;
        # see camera_id.camera_slug for the derivation order.
        from ..camera_id import camera_slug

        cam_slug = camera_slug(self.settings_store, cam_id)
        stem = f"{ts_label}_{trigger}_{cam_slug}"
        frames_dir = out_dir / f".scratch_{stem}"
        frames_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Ring first: the pre-roll frames become 00000.jpg upward so a
            # plain sorted() over the scratch dir stays chronological across
            # the pre/post seam. n_pre == 0 is normal (feature off, camera
            # was offline, ring never armed) and simply yields the
            # forward-only clip the system produced before this landed.
            n_pre = self._event_tl_take_preroll(cam_id, frames_dir)
            n_written = self._capture_event_tl_frames(
                cam_id, rt, frames_dir, window_min, interval_s, n_pre
            )
            if n_written < fps * 2:
                log.warning("[weather] Zu wenige Frames (%d) — Encode übersprungen", n_written)
                return
            self._finish_event_tl_clip(
                cam_id=cam_id,
                cam_name=cam_name,
                trigger=trigger,
                score=score,
                api_now=api_now,
                fc_snapshot=fc_snapshot,
                out_dir=out_dir,
                frames_dir=frames_dir,
                stem=stem,
                window_min=window_min,
                interval_s=interval_s,
                fps=fps,
                n_pre=n_pre,
            )
        finally:
            self._cleanup_sun_scratch(frames_dir)
            self._event_tl_release_capture(cam_id)

    @staticmethod
    def _event_tl_baseline_profile(rt):
        """Adaptive validator profile — same approach as the sun-tl
        capture: 3 quick samples → DAY/TWILIGHT/NIGHT. Event timelapses
        can run during any weather event (storm at noon vs midnight
        snowfall) so the profile-pick is just as relevant here."""
        from ..frame_helpers import pick_profile_from_baseline

        baseline_samples = []
        for _bi in range(3):
            try:
                _b = rt.snapshot_jpeg_hires(quality=85)
                if _b:
                    baseline_samples.append(_b)
            except Exception:
                pass
            if _bi < 2:
                time.sleep(0.5)
        return pick_profile_from_baseline(baseline_samples)

    @staticmethod
    def _event_tl_repick_profile(rt, active_profile):
        """Re-pick the validator profile mid-run. Returns the (possibly
        unchanged) profile; a failed grab keeps the current one."""
        from ..frame_helpers import pick_profile_from_baseline

        try:
            samp = rt.snapshot_jpeg_hires(quality=85)
            if not samp:
                return active_profile
            new_prof = pick_profile_from_baseline([samp])
            if new_prof is not active_profile:
                log.info(
                    "[weather] event-tl profile-switch %s → %s mid-run",
                    active_profile.name.upper(),
                    new_prof.name.upper(),
                )
            return new_prof
        except Exception:
            return active_profile

    def _capture_event_tl_frames(
        self,
        cam_id: str,
        rt,
        frames_dir: Path,
        window_min: int,
        interval_s: int,
        start_index: int,
    ) -> int:
        """Forward capture loop. Continues the frame numbering at
        ``start_index`` so the pre-roll already in ``frames_dir`` sorts
        ahead of everything written here. Returns the TOTAL frame count
        (pre-roll included)."""
        from ..frame_helpers import CaptureStats, grab_valid_frame

        cam_name = self._cam_name(cam_id)
        end_at = datetime.now() + timedelta(minutes=window_min)
        expected_frames = start_index + int((window_min * 60) / max(1, interval_s))
        stats = CaptureStats(out_dir=frames_dir, expected_frames=expected_frames)
        n_written = start_index
        i = start_index
        active_profile = self._event_tl_baseline_profile(rt)
        log.info("[weather] event-tl profile=%s cam=%s", active_profile.name.upper(), cam_name)
        # 2 min cadence (was 5) so a scene transition is detected
        # before the loop burns through dozens of false-positive
        # rejects. ``last_repick_at`` rate-limits the dead_area-
        # triggered forced re-pick.
        next_repick_at = datetime.now() + timedelta(minutes=2)
        last_repick_at = None
        while datetime.now() < end_at:
            now_dt = datetime.now()
            if now_dt >= next_repick_at:
                active_profile = self._event_tl_repick_profile(rt, active_profile)
                last_repick_at = now_dt
                next_repick_at = now_dt + timedelta(minutes=2)
            jpg, attempt_used, last_reason = grab_valid_frame(
                lambda: rt.snapshot_jpeg_hires(quality=92),
                profile=active_profile,
            )
            if jpg:
                try:
                    (frames_dir / f"{i:05d}.jpg").write_bytes(jpg)
                    n_written += 1
                    stats.record_capture(attempt_used=attempt_used)
                except Exception:
                    pass
            else:
                stats.record_invalid(last_reason)
                # Force a profile re-pick on a dead_area reject (rate-
                # limited to once per 30 s) — same logic as sun-tl.
                if last_reason and "dead_area" in last_reason:
                    if last_repick_at is None or (now_dt - last_repick_at).total_seconds() >= 30:
                        next_repick_at = now_dt
                log.info(
                    "[weather] %s slot %05d: invalid grabs, leaving slot empty (%s)",
                    cam_name,
                    i,
                    last_reason,
                )
            stats.flush()
            i += 1
            slept = 0.0
            while slept < interval_s and datetime.now() < end_at:
                time.sleep(0.5)
                slept += 0.5
        log.info(
            "[weather] Capture done: %s · %d Frames (%d Pre-Roll)",
            cam_name,
            n_written,
            start_index,
        )
        return n_written
