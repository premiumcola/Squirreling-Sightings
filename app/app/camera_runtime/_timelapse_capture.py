"""Per-interval work of the timelapse capture loop.

Split out of ``_timelapse.py``: ``_timelapse_profile_loop`` was 368
lines against an 80-line function ceiling, which is what let a magic
0.5 s retry sleep and a one-iteration ``for`` loop sit in it unread. The
loop that survives in ``_timelapse.py`` is the control flow — resolve
cadence, roll the window, capture, sleep — and every step it takes is a
method here.

Nothing in this module opens a camera handle. It copies the frame the
detection loop already holds (``self.lock`` for ~0.4 ms) and does all
validation, hashing and encoding outside that lock, which is why the
cadence floor in ``timelapse_windows`` is the only thing standing
between the timelapse and the detection loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2

from ..timelapse_windows import (
    FIXED_FPS,
    capture_interval_s,
    expected_frames,
    window_key as _tl_window_key,
)
from ._consts import _PROFILE_PERIOD_DEFAULTS, log_cam, log_tl

# How long to wait before the single re-grab after a rejected frame.
#
# It has to exceed the interval at which the main loop replaces
# ``self.frame`` or the re-grab hands back the buffer that was just
# rejected. Measured at ~0.49 s per decoded frame on the Unraid box, so
# the 0.5 s this replaced sat exactly on the boundary and mostly
# re-validated the identical buffer — a cut that cost recoveries at
# dawn and dusk, where rejects cluster, and bought nothing. 0.75 s
# clears the measured cadence and the 350 ms configured frame interval,
# and is still half of the 1.4 s the old three-attempt path could block
# the loop for.
RETRY_WAIT_S = 0.75

# Perceptual-hash distance under which two frames count as the same
# picture and the newer one is not written.
_DUP_HAMMING_MAX = 4

# How often the validator re-picks its DAY / TWILIGHT / NIGHT profile.
_PROFILE_REPICK_S = 300.0

_JPEG_QUALITY = 72


@dataclass
class Cadence:
    """What the profile config resolves to for one iteration."""

    target_s: int
    target_fps: int
    period_s: int
    interval_s: float
    clamped: bool


@dataclass
class CaptureState:
    """Everything one profile loop carries between iterations.

    Per-loop rather than on ``self`` on purpose: six profiles run at six
    different cadences in six threads, and a shared stale counter or
    pHash would have them corrupting each other's state.
    """

    window_key: str | None = None
    window_start_t: float = 0.0
    # frame_ts at the last capture — detects a frame buffer that the
    # RTSP loop has stopped refreshing.
    last_frame_ts: float = 0.0
    # pHash of the most recently WRITTEN frame, for the dedup guard.
    last_saved_phash: int = 0
    dup_dropped: int = 0
    stale_streak: int = 0
    stats: object | None = None
    stats_window_key: str | None = None
    active_profile: object | None = None
    next_profile_repick_t: float = 0.0
    clamp_logged: bool = False


class TimelapseCaptureMixin:
    """The steps of one capture interval, one method each."""

    # ── Cadence ──────────────────────────────────────────────────────────

    def _tl_cadence(self, tl: dict, profile_name: str, st: CaptureState) -> Cadence:
        """Resolve target / period / interval for this profile.

        Per-profile fps falls back to the camera-level fps, then to the
        15 the UI pins — NOT 25. A legacy settings.json that skipped the
        fps migration ran at 25, which shortens the interval and is the
        only thing that made the timelapse measurably compete with the
        detection loop.
        """
        prof = (tl.get("profiles") or {}).get(profile_name) or {}
        target_s = int(prof.get("target_seconds", 60))
        target_fps = int(prof.get("fps") or tl.get("fps") or FIXED_FPS)
        period_s = int(
            prof.get("period_seconds", _PROFILE_PERIOD_DEFAULTS.get(profile_name, 86400))
        )
        interval_s, clamped = capture_interval_s(period_s, target_s, target_fps)
        if clamped and not st.clamp_logged:
            # One WARNING per thread, not one per tick.
            log_tl.warning(
                "[timelapse] %s/%s interval clamped to %.0fs "
                "(period=%ds target=%ds fps=%d) — video will be shorter than requested",
                self.camera_id,
                profile_name,
                interval_s,
                period_s,
                target_s,
                target_fps,
            )
            st.clamp_logged = True
        return Cadence(target_s, target_fps, period_s, interval_s, clamped)

    # ── Window boundaries ────────────────────────────────────────────────

    def _tl_roll_window(self, profile_name: str, st: CaptureState, cad: Cadence) -> None:
        """Open the right window for now, finalising the one it replaces."""
        if profile_name == "custom":
            self._tl_roll_custom_window(profile_name, st, cad)
        else:
            self._tl_roll_calendar_window(profile_name, st, cad)

    def _tl_roll_custom_window(self, profile_name: str, st: CaptureState, cad: Cadence) -> None:
        """Rolling ``period_seconds`` window measured from the loop start."""
        now_t = time.time()
        if st.window_key is not None and now_t - st.window_start_t < cad.period_s:
            return
        rolled = st.window_key is not None
        if rolled:
            self._finalize_timelapse_window(
                profile_name, st.window_key, cad.target_s, cad.target_fps, cad.period_s
            )
        st.window_start_t = now_t
        st.window_key = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_tl.info(
            "[%s][timelapse] custom %s window: %s (period=%ds interval=%.0fs)",
            self.camera_id,
            "new" if rolled else "first",
            st.window_key,
            cad.period_s,
            cad.interval_s,
        )
        if rolled:
            self._finalize_orphaned_windows(
                profile_name, st.window_key, cad.target_s, cad.target_fps, cad.period_s
            )

    def _tl_roll_calendar_window(self, profile_name: str, st: CaptureState, cad: Cadence) -> None:
        """One window per period the profile is NAMED after — day / ISO
        week / month / quarter / year. This used to be ``%Y-%m-%d`` for
        every profile, so weekly and monthly collected at their own
        cadence but encoded and deleted at midnight: "monthly" was a
        one-day video of ~150 frames at 1 fps."""
        new_key = _tl_window_key(profile_name) or datetime.now().strftime("%Y-%m-%d")
        if new_key == st.window_key:
            return
        if st.window_key is not None:
            old_key = st.window_key
            self._finalize_timelapse_window(
                profile_name, old_key, cad.target_s, cad.target_fps, cad.period_s
            )
            log_tl.info(
                "[%s][timelapse] %s window boundary: finalized %s, starting %s",
                self.camera_id,
                profile_name,
                old_key,
                new_key,
            )
        st.window_key = new_key
        log_tl.info(
            "[%s][timelapse] %s window: %s (period=%ds interval=%.0fs)",
            self.camera_id,
            profile_name,
            st.window_key,
            cad.period_s,
            cad.interval_s,
        )
        self._finalize_orphaned_windows(
            profile_name, st.window_key, cad.target_s, cad.target_fps, cad.period_s
        )

    # ── Stale-buffer detection ───────────────────────────────────────────

    def _tl_note_stale_frame(self, profile_name: str, st: CaptureState, frame_ts: float) -> None:
        """The frame buffer has not moved since the last capture — the
        RTSP stream is genuinely stuck. A static scene (identical
        content, new timestamp) is intentionally saved instead."""
        age_s = time.time() - frame_ts
        self._stale_incidents += 1
        st.stale_streak += 1
        self._stale_streak = st.stale_streak  # mirror for status UI
        # Noise control: only streak 1 and 5 at WARNING (first sign +
        # "this is getting bad"); the reconnect decision still uses the
        # full streak.
        if st.stale_streak in (1, 5):
            log_tl.warning(
                "[%s][%s] stale frame buffer (age=%.0fs, streak=%d) — RTSP stream may be stuck",
                self.camera_id,
                profile_name,
                age_s,
                st.stale_streak,
            )
        else:
            log_tl.debug(
                "[%s][%s] stale frame buffer (age=%.0fs, streak=%d)",
                self.camera_id,
                profile_name,
                age_s,
                st.stale_streak,
            )
        if st.stale_streak >= 15 and not self._force_reconnect:
            log_tl.error(
                "[%s][%s] stale streak exceeded threshold — requesting RTSP reconnect",
                self.camera_id,
                profile_name,
            )
            self._force_reconnect = True

    def _tl_note_fresh_frame(self, profile_name: str, st: CaptureState, frame_ts: float) -> None:
        st.last_frame_ts = frame_ts
        if st.stale_streak > 0:
            log_cam.info(
                "[%s][%s] stream recovered after %d stale intervals",
                self.camera_id,
                profile_name,
                st.stale_streak,
            )
        st.stale_streak = 0
        self._stale_streak = 0  # clear the UI mirror too

    # ── Per-window stats + validator profile ─────────────────────────────

    def _tl_window_dir(self, profile_name: str, window_key: str) -> Path:
        return (
            Path(self.global_cfg["storage"]["root"])
            / "timelapse_frames"
            / self.camera_id
            / profile_name
            / window_key
        )

    def _tl_ensure_stats(self, st: CaptureState, tl_dir: Path, cad: Cadence) -> None:
        """First frame of a window gets a fresh CaptureStats keyed to
        that window's frame directory."""
        from ..frame_helpers import CaptureStats as _CaptureStats

        if st.stats is not None and st.stats_window_key == st.window_key:
            return
        tl_dir.mkdir(parents=True, exist_ok=True)
        st.stats = _CaptureStats(
            out_dir=tl_dir, expected_frames=expected_frames(cad.period_s, cad.interval_s)
        )
        st.stats_window_key = st.window_key
        # A window-boundary scene shift would otherwise look like a
        # duplicate of the previous window's last frame.
        st.last_saved_phash = 0
        st.dup_dropped = 0

    def _tl_repick_validator_profile(self, profile_name: str, st: CaptureState, frame) -> None:
        """Re-pick DAY / TWILIGHT / NIGHT thresholds every 5 min off the
        freshest shared frame, so a full diurnal cycle gets the right
        thresholds at each phase with no extra capture cost."""
        from ..frame_helpers import pick_profile_from_baseline as _pick_profile

        now_t = time.time()
        if now_t < st.next_profile_repick_t:
            return
        try:
            new_prof = _pick_profile([frame])
            if new_prof is not st.active_profile:
                log_tl.info(
                    "[timelapse] %s/%s profile-switch %s → %s",
                    self.camera_id,
                    profile_name,
                    getattr(st.active_profile, "name", "?").upper(),
                    new_prof.name.upper(),
                )
                st.active_profile = new_prof
        except Exception:
            pass
        st.next_profile_repick_t = now_t + _PROFILE_REPICK_S

    # ── Validation with one re-grab ──────────────────────────────────────

    def _tl_valid_or_retry(self, frame, frame_ts: float, profile_name: str, st: CaptureState):
        """``(frame, ok, reason, attempt_used)`` — validate, then re-grab once.

        Capped at one retry deliberately: the old three-attempt path
        blocked the loop for up to 1.4 s of sleep plus two extra
        full-resolution validations.

        The re-grab is skipped when the buffer has not moved. The
        previous version compared nothing and simply re-validated the
        identical rejected buffer, which cannot change its verdict — the
        outer loop's own ``frame_ts`` guard exists for exactly this
        reason and the retry did not use it.
        """
        from ..frame_helpers import is_valid_frame as _fh_valid

        ok, reason = _fh_valid(frame, profile=st.active_profile)
        if ok:
            return frame, True, reason, 0
        self._tl_log_reject(profile_name, 1, reason)
        time.sleep(RETRY_WAIT_S)
        with self.lock:
            cand = self.frame.copy() if self.frame is not None else None
            cand_ts = self.frame_ts
        if cand is None or cand_ts == frame_ts:
            self._tl_log_reject(profile_name, 2, "no fresh buffer after %.2fs" % RETRY_WAIT_S)
            return frame, False, reason, 0
        ok, reason = _fh_valid(cand, profile=st.active_profile)
        if not ok:
            self._tl_log_reject(profile_name, 2, reason)
            return frame, False, reason, 0
        return cand, True, reason, 1

    def _tl_log_reject(self, profile_name: str, attempt: int, reason: str) -> None:
        """Per-rejection INFO line for the daily profile only — it is
        what explains dawn-hour gaps in the assembled video. Other
        profiles stay on the post-attempt summary to keep log volume
        sane."""
        if profile_name != "daily":
            return
        log_tl.info(
            "[timelapse] %s/daily reject @ %s (attempt %d): %s",
            self.camera_id,
            datetime.now().strftime("%H:%M:%S"),
            attempt,
            reason,
        )

    # ── Write ────────────────────────────────────────────────────────────

    def _tl_store_frame(
        self,
        frame,
        tl_dir: Path,
        profile_name: str,
        st: CaptureState,
        cad: Cadence,
        attempt_used: int,
    ) -> None:
        """Write the frame unless it is a duplicate of the last one.

        A stuck stream that delivers the same buffer with a fresh
        timestamp slips past the ``frame_ts`` guard; without this it
        inflates the on-disk footprint AND produces frozen-time runs in
        the encoded video.
        """
        from ..frame_helpers import hamming_distance as _ph_hamming, perceptual_hash as _ph_phash

        this_phash = _ph_phash(frame)
        if st.last_saved_phash != 0 and _ph_hamming(st.last_saved_phash, this_phash) <= (
            _DUP_HAMMING_MAX
        ):
            st.dup_dropped += 1
            if st.dup_dropped in (1, 5, 25, 100):
                log_tl.info(
                    "[timelapse] %s/%s skipped duplicate frame "
                    "(pHash match) — total dropped this run: %d",
                    self.camera_id,
                    profile_name,
                    st.dup_dropped,
                )
            return
        out = tl_dir / f"{datetime.now().strftime('%H%M%S_%f')[:10]}.jpg"
        cv2.imwrite(str(out), frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
        st.stats.record_capture(attempt_used=attempt_used)
        st.last_saved_phash = this_phash
        log_tl.debug(
            "[%s][%s] frame saved: %s window=%s (%.2fs/frame, q=%d, attempt=%d)",
            self.camera_id,
            profile_name,
            out.name,
            st.window_key,
            cad.interval_s,
            _JPEG_QUALITY,
            attempt_used + 1,
        )

    def _tl_capture_once(self, profile_name: str, st: CaptureState, cad: Cadence) -> None:
        """One capture interval: grab, validate, write, flush stats."""
        with self.lock:
            frame = self.frame.copy() if self.frame is not None else None
            frame_ts = self.frame_ts
        if frame is None or st.window_key is None:
            return
        if frame_ts == st.last_frame_ts:
            # Don't advance last_frame_ts — keep detecting stale each interval.
            self._tl_note_stale_frame(profile_name, st, frame_ts)
            return
        self._tl_note_fresh_frame(profile_name, st, frame_ts)
        tl_dir = self._tl_window_dir(profile_name, st.window_key)
        self._tl_ensure_stats(st, tl_dir, cad)
        self._tl_repick_validator_profile(profile_name, st, frame)
        frame, ok, reason, attempt_used = self._tl_valid_or_retry(frame, frame_ts, profile_name, st)
        if not ok:
            st.stats.record_invalid(reason)
            log_tl.info(
                "[timelapse] %s frame %s: invalid grabs, leaving slot empty (%s)",
                self.camera_id,
                datetime.now().strftime("%H%M%S_%f")[:10],
                reason,
            )
        else:
            self._tl_store_frame(frame, tl_dir, profile_name, st, cad, attempt_used)
        # Cheap to flush each interval; lets the build path see
        # partial-window stats if it runs while capture is still going.
        st.stats.flush()
