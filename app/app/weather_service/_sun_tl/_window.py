"""Sizing of the sunrise/sunset capture window — the numbers and the
one function that applies them.

Lifted out of ``_sun_tl/__init__.py`` unchanged so the scheduler
(``_schedule.py``) and the capture loop can both import them without
either importing the other. Nothing here has behaviour of its own; the
comments below are the reasoning that used to sit beside the literals.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# 70/30 pre-event bias on the sun-timelapse window: most of the captured
# minutes sit BEFORE the sun event so a sunrise video starts in twilight
# and watches the sun come up; a sunset video catches the run-up to dusk
# and a short tail of afterglow. Single source of truth — referenced by
# both the scheduler in _register_sun_jobs and the preview math in
# sun_times_today so the two never drift again.
_SUN_PRE_BIAS = 0.70

# Drift guard: refuse a "sunset" capture that fires hours after the
# real solar sunset. Without this, a misconfigured schedule produced an
# MP4 labelled "sunset · score=0.60" that was actually 312 minutes
# after the real event — pure IR night with no afterglow at all.
# Production runs refuse outright; test mode logs a WARNING and
# proceeds (the user is deliberately diagnosing).
_SUN_TL_DRIFT_LIMIT_MIN = 90

# Locked sunrise/sunset capture window — single value, not user-tunable.
# Sized to comfortably cover civil twilight (sun 0–6° below horizon, ~30
# min either side at mid-latitudes) PLUS golden hour (~30 min after the
# event). With the 70/30 pre-bias above that gives 52 min before and
# 23 min after the sun event, so the recording starts well into
# nautical twilight (when the first colours appear in the sky) and
# ends after the bright phase has settled. Smaller windows (the
# previous 30-min default) miss the early twilight transition; larger
# ones bloat the file without adding visible content. Per the F-task
# spec the user-facing slider was removed — fewer knobs to mis-set.
_SUN_TL_LOCKED_WINDOW_MIN = 75

# Locked output frame rate — same story as the window above. Every
# timelapse path in the system encodes at 15 fps; the per-phase `fps`
# in settings.json is not consulted by the capture path at all (see
# `target_fps` in _run_sun_capture). Named here so the encoder and the
# preview endpoint quote one value instead of two literals that can
# drift apart.
_SUN_TL_LOCKED_FPS = 15


def _sun_window_bounds(sun_dt: datetime, window_min: int) -> tuple[datetime, datetime, int, int]:
    """Apply _SUN_PRE_BIAS to (sun_dt, window_min). Returns
    (start_dt, end_dt, pre_min, post_min). Pure function — no `self`,
    safe to call from anywhere in the module."""
    pre = int(round(window_min * _SUN_PRE_BIAS))
    post = window_min - pre
    return (
        sun_dt - timedelta(minutes=pre),
        sun_dt + timedelta(minutes=post),
        pre,
        post,
    )
