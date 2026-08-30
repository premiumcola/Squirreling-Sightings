"""Loop cadence measurement — the number the tracker's grace math needs.

``track_miss_grace_seconds`` is configured in WALL-CLOCK SECONDS and
enforced in TICKS: ``compute_miss_grace_samples(seconds, fps)`` turns it
into a sample count, and a track closes once it has missed that many
tracker steps. One tracker step happens per loop iteration, so the only
rate that makes the conversion correct is the rate at which THIS loop
iterates.

That rate used to be counted inside ``_rtsp_recording_step``, which is a
strictly smaller set of iterations than the tracker's:

* it sits behind ``if self.cfg.get("rtsp_url")`` — a snapshot-only camera
  never reaches it, so ``_main_fps`` stayed 0.0 for the camera's whole
  life and the tracker silently used a hard-coded literal instead;
* it sits behind the recording-block ``continue`` — a camera with
  ``recording_enabled`` off, or outside its ``schedule_record`` window,
  skips it on exactly the frames that HAVE motion, which is exactly when
  the tracker is doing work.

Every iteration counted there is an iteration the tracker also ran, but
not the reverse, so the measurement could only ever come out too LOW —
and too low means too FEW grace samples, which closes live tracks early.
That is the track-fragmentation direction, not a cosmetic telemetry
drift.

Counting here, on the loop's own tick immediately before the tracker
step, makes the published number describe the loop the tracker actually
runs in. ``self._main_fps`` keeps its name and its readers (telemetry's
``analysed_fps``, the debug snapshot, the sim evidence block, the OpenCV
clip-fps fallback) — only the tick it counts changes.
"""

from __future__ import annotations

import time

# Rolling measurement window. Kept at the historical 5 s so the published
# _main_fps still means what every existing reader thinks it means.
_FPS_WINDOW_S = 5.0
# Below this many ticks a part-window rate is a single interval, which is
# noise. Two ticks make it an average.
_FPS_MIN_SAMPLES = 2
# Bounds for the cold-start estimate derived from the configured loop
# interval — the only value available before the second tick of a
# session.
_NOMINAL_MIN_HZ = 0.02
_NOMINAL_MAX_HZ = 60.0
# A single inter-tick gap longer than this counts as a STALL, not as
# cadence: the loop `continue`s past the tracker on a forced reconnect, a
# wedged capture handle, the 3 s post-connect warm-up and every rejected
# frame. Averaging dead time into the rate would understate it for one
# whole window. Expressed as a multiple of the loop's configured interval
# (and never below one window) so a legitimately slow snapshot camera,
# whose every tick is 25 s apart, is not mistaken for a stall.
_STALL_INTERVALS = 5.0


def nominal_rate(interval_s: float) -> float:
    """Ticks per second the loop is CONFIGURED for, from its sleep interval.

    Used for the first two ticks of a camera session only, where no
    measurement exists yet. Honest per-camera (an RTSP camera on a 150 ms
    interval and a snapshot camera on a 3 s one differ by 20x) where the
    old hard-coded 3.0 literal was right for one of them by accident.
    """
    try:
        iv = float(interval_s)
    except (TypeError, ValueError):
        return _NOMINAL_MIN_HZ
    if iv <= 0:
        return _NOMINAL_MAX_HZ
    return max(_NOMINAL_MIN_HZ, min(_NOMINAL_MAX_HZ, 1.0 / iv))


def _stall_gap_s(interval_s: float) -> float:
    """Inter-tick gap above which the loop counts as stalled, not slow."""
    return max(_FPS_WINDOW_S, _STALL_INTERVALS / nominal_rate(interval_s))


class LoopCadenceMixin:
    """Mixin for CameraRuntime: counts the main loop's own tick rate.

    State (``_main_fps``, ``_main_fps_frames``, ``_main_fps_window_start``,
    ``_main_fps_last_tick``) lives on the concrete class.
    ``_main_fps_window_start`` is the monotonic timestamp of the tick that
    OPENED the current window (None until the session's first tick), and
    that tick is not counted in ``_main_fps_frames`` — so
    ``frames / elapsed`` is an unbiased rate rather than one tick too high.
    """

    def _tick_loop_cadence(self, interval_s: float) -> float:
        """Count one loop tick; return the loop's effective ticks/second.

        Publishes the rolling window on ``self._main_fps`` and returns the
        best estimate available RIGHT NOW: the published rate once a full
        window has closed, the part-window rate during warm-up, and the
        configured cadence for the first two ticks of a session.
        """
        now = time.monotonic()
        prev_tick = self._main_fps_last_tick
        self._main_fps_last_tick = now
        if self._main_fps_window_start is None:
            # First tick of the session. The gap before it is process
            # startup and stream connect, not loop cadence — open the
            # window here instead of letting it skew the first average.
            self._main_fps_window_start = now
            return nominal_rate(interval_s)
        elapsed = now - self._main_fps_window_start
        gap = now - prev_tick if prev_tick is not None else 0.0
        if elapsed < 0.0 or gap > _stall_gap_s(interval_s):
            # Either the clock base changed, or the loop stopped ticking
            # for a while. Reopen the window on this tick; the last
            # published rate stands until the next one closes, which is
            # at most one window away and is a rate this loop really ran
            # at — unlike an average taken across the dead stretch.
            self._main_fps_window_start = now
            self._main_fps_frames = 0
            return self._main_fps or nominal_rate(interval_s)
        self._main_fps_frames += 1
        if elapsed >= _FPS_WINDOW_S and self._main_fps_frames >= _FPS_MIN_SAMPLES:
            # 2 decimals, not 1: a slow snapshot camera can genuinely sit
            # at 0.04 Hz, and rounding that to 0.0 would hand the tracker
            # a "no measurement" reading forever.
            self._main_fps = round(self._main_fps_frames / elapsed, 2)
            self._main_fps_window_start = now
            self._main_fps_frames = 0
            return self._main_fps
        if self._main_fps > 0.0:
            return self._main_fps
        if self._main_fps_frames >= _FPS_MIN_SAMPLES and elapsed > 0.0:
            return self._main_fps_frames / elapsed
        return nominal_rate(interval_s)
