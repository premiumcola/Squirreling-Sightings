"""Timelapse capture loops + species achievement unlocks.

Composition only: the two loops here decide *when* to act, the mixins
they compose decide *what* the action is.

* ``_timelapse_capture`` — one method per step of a capture interval.
* ``_timelapse_encode``  — everything that happens to a window after it
  closes.

The file was 821 lines against a 500-line ceiling before the split,
with a 368-line loop and a 241-line finaliser against an 80-line
function ceiling.
"""

from __future__ import annotations

import json as _json_mod
import time
from datetime import datetime
from pathlib import Path

import cv2

from ..io_utils import atomic_write_json
from ..timelapse_windows import FIXED_FPS, capture_interval_s
from ._consts import _SPECIES_TO_ACH_ID, log, log_tl
from ._timelapse_capture import CaptureState, TimelapseCaptureMixin
from ._timelapse_encode import TimelapseEncodeMixin

# Legacy ``timelapse.period`` slug → seconds. Only the legacy loop reads
# these; the profile loop takes period_seconds straight from the config.
_LEGACY_PERIOD_S = {"day": 86400, "hour": 3600, "rolling_10min": 600}


class TimelapseMixin(TimelapseEncodeMixin, TimelapseCaptureMixin):
    """Periodic timelapse capture/finalize loops + achievement unlocks.

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (frame buffers, lock, config, etc.) which live on the concrete class.
    """

    def _timelapse_loop(self):
        """Legacy single-profile timelapse — started only for a camera
        with ``timelapse.enabled`` and no profile configured.

        Its cadence now comes from ``timelapse_windows.capture_interval_s``
        like every other loop's. It used to compute its own
        ``max(0.5, period_s / total_frames)`` with an fps fallback of 25,
        which is both a parallel implementation of the shared helper and
        the worst cadence in the tree: ``period: rolling_10min`` resolved
        to 0.5 s, i.e. two captures a second per camera against a
        detection loop running at ~2 Hz. The 8 s floor in the shared
        helper is what that number should always have been.
        """
        while self.running:
            tl = self.cfg.get("timelapse") or {}
            if not tl.get("enabled"):
                time.sleep(10)
                continue
            target_s = int(tl.get("daily_target_seconds", 60))
            target_fps = int(tl.get("fps") or FIXED_FPS)
            period_s = _LEGACY_PERIOD_S.get(tl.get("period", "day"), 86400)
            interval_s, _clamped = capture_interval_s(period_s, target_s, target_fps)
            self._legacy_timelapse_capture(interval_s)
            deadline = time.time() + interval_s
            while self.running and time.time() < deadline:
                time.sleep(1)

    def _legacy_timelapse_capture(self, interval_s: float) -> None:
        """Write one frame into the flat ``<cam>/<day>/`` layout."""
        with self.lock:
            frame = self.frame.copy() if self.frame is not None else None
        if frame is None:
            return
        try:
            tl_dir = (
                Path(self.global_cfg["storage"]["root"])
                / "timelapse_frames"
                / self.camera_id
                / datetime.now().strftime("%Y-%m-%d")
            )
            tl_dir.mkdir(parents=True, exist_ok=True)
            out = tl_dir / f"{datetime.now().strftime('%H%M%S')}.jpg"
            cv2.imwrite(str(out), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
            log_tl.debug(
                "[%s] timelapse frame saved: %s (interval=%.2fs)",
                self.camera_id,
                out.name,
                interval_s,
            )
        except Exception as e:
            log_tl.debug("[%s] timelapse frame write error: %s", self.camera_id, e)

    def _timelapse_profile_loop(self, profile_name: str):
        """Per-profile capture loop. Reads the latest frame from the main
        loop — never opens a camera handle of its own. Tracks period
        windows: encodes, registers and cleans up frames when each
        window ends.

        * ``custom`` — fixed-duration rolling windows, ``period_seconds``
          long each.
        * everything else — one window per calendar period the profile
          is named after, encoded at that period's boundary.
        """
        from ..frame_helpers import DAY_PROFILE as _DAY_PROFILE

        # DAY keeps the historic behaviour for the first iteration,
        # before any baseline pick has run.
        st = CaptureState(active_profile=_DAY_PROFILE)
        while self.running:
            tl = self.cfg.get("timelapse") or {}
            if not ((tl.get("profiles") or {}).get(profile_name) or {}).get("enabled"):
                if st.window_key is not None:
                    log_tl.debug(
                        "[%s][%s] profile disabled — resetting window %s",
                        self.camera_id,
                        profile_name,
                        st.window_key,
                    )
                st.window_key = None
                st.window_start_t = 0.0
                time.sleep(10)
                continue
            cad = self._tl_cadence(tl, profile_name, st)
            self._tl_roll_window(profile_name, st, cad)
            try:
                self._tl_capture_once(profile_name, st, cad)
            except Exception as e:
                log_tl.debug("[%s][%s] frame write error: %s", self.camera_id, profile_name, e)
            deadline = time.time() + cad.interval_s
            while self.running and time.time() < deadline:
                time.sleep(1)

    def _try_unlock_achievement(self, species_name: str, species_label: str) -> bool:
        """Unlock achievement for a bird/animal species. Returns True if newly unlocked."""
        ach_id = _SPECIES_TO_ACH_ID.get(species_name.lower().strip())
        if not ach_id:
            return False
        try:
            with self._ach_lock:
                data: dict = {}
                if self._ach_path.exists():
                    try:
                        data = _json_mod.loads(self._ach_path.read_text(encoding="utf-8"))
                    except Exception:
                        data = {}
                if ach_id in data:
                    return False  # already unlocked
                data[ach_id] = {
                    "date": datetime.now().isoformat(timespec="seconds"),
                    "camera_id": self.camera_id,
                    "species": species_label,
                }
                atomic_write_json(self._ach_path, data)
            log.info("[%s] Achievement unlocked: %s (%s)", self.camera_id, ach_id, species_label)
            return True
        except Exception as e:
            log.warning("[%s] Achievement unlock failed: %s", self.camera_id, e)
            return False
