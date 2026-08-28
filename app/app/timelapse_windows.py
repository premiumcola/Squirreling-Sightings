"""Window keys and capture cadence for the per-profile timelapse loops.

Single source of truth for two things that used to be computed in three
places and disagreed:

* **Window keys.** ``_timelapse_profile_loop`` used ``%Y-%m-%d`` for
  every non-custom profile, so "Wöchentlich" and "Monatlich" collected
  at a weekly / monthly *cadence* but encoded and deleted their frames
  at midnight every night. A "monthly" video was one day of 150 frames
  played at 1 fps — and ``_write_video`` dutifully logged "will play at
  1.0 fps (< 15) — video will look choppy" every single time. The key
  now spans the period the profile is named after.

* **Interval + fps.** The UI clamps the capture interval to 8 s and
  pins fps to 15, but the backend floor was ``max(0.5, …)`` with an fps
  fallback of 25. A settings.json that skipped the migration therefore
  ran a custom profile at 0.5 s — the only cadence where the timelapse
  capture measurably competes with the detection loop — with no clamp
  and no log line.

The capture loop itself never opens a camera handle: it copies the
frame the detection loop already holds (``self.lock`` for ~0.4 ms) and
does all validation and encoding outside that lock. There is no second
capture to defer, which is why no deferral scheme lives here.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Mirror of the frontend contract in
# web/static/js/camedit/timelapse-settings.js — keep both in step.
MIN_INTERVAL_S = 8.0
FIXED_FPS = 15

# Profiles whose window spans a fixed calendar unit. ``custom`` is
# absent on purpose: its window is a rolling ``period_seconds`` measured
# from whenever the loop started, so only the loop knows its key.
_CALENDAR_KEY_FORMATS = {
    "daily": "%Y-%m-%d",
    "weekly": "%G-W%V",
    "monthly": "%Y-%m",
    "yearly": "%Y",
}


def window_key(profile_name: str, when: datetime | None = None) -> str | None:
    """Calendar window key for ``profile_name``, or ``None`` for custom.

    ``None`` means "this profile's window is not derivable from the
    clock alone" — callers that need the current key for a custom
    profile must read it off disk (see ``timelapse_storage``).
    """
    when = when or datetime.now()
    if profile_name == "quarterly":
        return f"{when.year}-Q{(when.month - 1) // 3 + 1}"
    fmt = _CALENDAR_KEY_FORMATS.get(profile_name)
    return when.strftime(fmt) if fmt else None


def capture_interval_s(period_s: int, target_s: int, fps: int) -> tuple[float, bool]:
    """Seconds between captures, plus whether the 8 s floor clamped it.

    A clamped profile keeps its cadence but produces fewer frames than
    ``target_s * fps``; the encoder recomputes fps from the frames that
    actually landed, so the video comes out shorter rather than
    desynced.
    """
    total_frames = max(1, int(target_s) * max(1, int(fps)))
    raw = max(0.001, int(period_s) / total_frames)
    return (max(MIN_INTERVAL_S, raw), raw < MIN_INTERVAL_S)


def next_window_start(profile_name: str, when: datetime | None = None) -> datetime | None:
    """When the current calendar window closes and the build fires.

    ``None`` for the custom profile — its boundary is
    ``window_start + period_seconds``, and only the frames on disk say
    when the window started.
    """
    when = when or datetime.now()
    midnight = when.replace(hour=0, minute=0, second=0, microsecond=0)
    if profile_name == "daily":
        return midnight + timedelta(days=1)
    if profile_name == "weekly":
        return midnight + timedelta(days=7 - when.weekday())
    if profile_name == "monthly":
        return (midnight.replace(day=1) + timedelta(days=32)).replace(day=1)
    if profile_name == "quarterly":
        first_month = ((when.month - 1) // 3) * 3 + 1
        start = midnight.replace(month=first_month, day=1)
        return (start + timedelta(days=100)).replace(day=1)
    if profile_name == "yearly":
        return midnight.replace(year=when.year + 1, month=1, day=1)
    return None


def expected_frames(period_s: int, interval_s: float) -> int:
    """How many frames a full window should hold at this cadence."""
    return max(1, int(int(period_s) / max(MIN_INTERVAL_S, float(interval_s))))
