"""Pins the two timelapse fixes that are easy to silently undo.

1. **Window keys span the period the profile is named after.** Every
   non-custom profile used ``%Y-%m-%d``, so "Wöchentlich" and
   "Monatlich" collected at their own cadence but encoded and deleted
   their frames at midnight — a "monthly" video was one day of ~150
   frames at 1 fps.

2. **Storage accounting is cached and invalidated.** The panel reads
   per-profile bytes on every dashboard poll; without the TTL that is a
   scandir over ~900 files per profile per request.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import timelapse_storage  # noqa: E402
from app.timelapse_windows import (  # noqa: E402
    FIXED_FPS,
    MIN_INTERVAL_S,
    TIMELAPSE_PROFILES,
    capture_interval_s,
    expected_frames,
    next_window_start,
    window_covers_day,
    window_key,
)


# ── Window keys ──────────────────────────────────────────────────────────


def test_each_profile_gets_its_own_period_key():
    when = datetime(2026, 8, 28, 13, 45)
    assert window_key("daily", when) == "2026-08-28"
    assert window_key("weekly", when) == "2026-W35"
    assert window_key("monthly", when) == "2026-08"
    assert window_key("quarterly", when) == "2026-Q3"
    assert window_key("yearly", when) == "2026"


def test_custom_profile_has_no_calendar_key():
    """Its window is period_seconds from whenever the loop started."""
    assert window_key("custom", datetime(2026, 8, 28)) is None


def test_weekly_key_is_stable_across_a_day_boundary():
    """The regression itself: mid-week midnight must NOT roll the window."""
    mon = window_key("weekly", datetime(2026, 8, 24, 23, 59))
    tue = window_key("weekly", datetime(2026, 8, 25, 0, 1))
    assert mon == tue


def test_monthly_key_rolls_only_at_month_end():
    assert window_key("monthly", datetime(2026, 8, 31, 23, 59)) == "2026-08"
    assert window_key("monthly", datetime(2026, 9, 1, 0, 1)) == "2026-09"


def test_next_window_start_lands_on_the_period_boundary():
    when = datetime(2026, 8, 28, 13, 45)  # a Friday
    assert next_window_start("daily", when) == datetime(2026, 8, 29)
    assert next_window_start("weekly", when) == datetime(2026, 8, 31)  # next Monday
    assert next_window_start("monthly", when) == datetime(2026, 9, 1)
    assert next_window_start("quarterly", when) == datetime(2026, 10, 1)
    assert next_window_start("yearly", when) == datetime(2027, 1, 1)
    assert next_window_start("custom", when) is None


# ── Interval contract ────────────────────────────────────────────────────


def test_interval_honours_the_eight_second_floor():
    # custom defaults: 600 s window, 30 s video at 15 fps → 1.33 s raw.
    interval, clamped = capture_interval_s(600, 30, 15)
    assert clamped is True
    assert interval == MIN_INTERVAL_S


def test_unclamped_interval_is_the_plain_arithmetic():
    interval, clamped = capture_interval_s(86400, 60, 15)
    assert clamped is False
    assert round(interval, 1) == 96.0


def test_expected_frames_follows_the_clamped_interval():
    interval, _ = capture_interval_s(600, 30, 15)
    assert expected_frames(600, interval) == 75


# ── Storage accounting ───────────────────────────────────────────────────


def _code_only(src: str) -> str:
    """Drop the docstring so a comment ABOUT a banned construct does not
    read as the construct itself."""
    return re.sub(r'""".*?"""', "", src, flags=re.S)


def _write_frames(
    root: Path,
    cam: str,
    profile: str,
    window: str,
    n: int,
    size: int,
    day: str | None = None,
    hour: int = 12,
) -> Path:
    """Frames with a CONTROLLED mtime.

    frames_for_day carves a day out of a multi-day window by mtime — the
    filename inside a ``2026-W35`` directory says nothing about which of
    the seven days it belongs to. Letting the mtime default to "now"
    would make every such test pass only on the day it was written.
    """
    d = root / "timelapse_frames" / cam / profile / window
    d.mkdir(parents=True, exist_ok=True)
    stamp = None
    if day is not None:
        stamp = datetime.strptime(day, "%Y-%m-%d").replace(hour=hour).timestamp()
    for i in range(n):
        f = d / f"{hour:02d}00{i:02d}_00.jpg"
        f.write_bytes(b"x" * size)
        if stamp is not None:
            os.utime(f, (stamp + i, stamp + i))
    return d


def test_profile_usage_reports_count_and_bytes(tmp_storage_root):
    timelapse_storage.invalidate("cam1")
    _write_frames(tmp_storage_root, "cam1", "daily", "2026-08-28", 4, 1000)
    usage = timelapse_storage.profile_usage(tmp_storage_root, "cam1", "daily")
    assert usage["frame_count"] == 4
    assert usage["bytes_on_disk"] == 4000
    assert usage["window_key"] == "2026-08-28"
    assert usage["oldest_frame"] and usage["newest_frame"]


def test_usage_is_cached_until_invalidated(tmp_storage_root):
    timelapse_storage.invalidate("cam2")
    _write_frames(tmp_storage_root, "cam2", "daily", "2026-08-28", 2, 500)
    assert timelapse_storage.profile_usage(tmp_storage_root, "cam2", "daily")["frame_count"] == 2

    _write_frames(tmp_storage_root, "cam2", "daily", "2026-08-28", 6, 500)
    # Still the cached figure — that is the whole point of the TTL.
    assert timelapse_storage.profile_usage(tmp_storage_root, "cam2", "daily")["frame_count"] == 2

    timelapse_storage.invalidate("cam2", "daily")
    assert timelapse_storage.profile_usage(tmp_storage_root, "cam2", "daily")["frame_count"] == 6


def test_missing_profile_dir_is_zero_not_an_error(tmp_storage_root):
    timelapse_storage.invalidate("cam3")
    usage = timelapse_storage.profile_usage(tmp_storage_root, "cam3", "yearly")
    assert usage["frame_count"] == 0
    assert usage["bytes_on_disk"] == 0
    assert usage["window_key"] is None


def test_projection_extrapolates_from_the_observed_frame_size(tmp_storage_root):
    timelapse_storage.invalidate("cam4")
    _write_frames(tmp_storage_root, "cam4", "daily", "2026-08-28", 10, 2000)
    usage = timelapse_storage.profile_usage(tmp_storage_root, "cam4", "daily")
    # 10 frames × 2000 B measured → 900 frames projected at the same mean.
    assert timelapse_storage.projected_bytes(usage, 900) == 1_800_000
    # Never projects below what is already on disk.
    assert timelapse_storage.projected_bytes(usage, 1) == 20_000


def test_frames_for_day_sees_the_profile_layout(tmp_storage_root):
    """The on-demand build endpoints read this. Looking only at the flat
    legacy path made /api/camera/<id>/timelapse answer no_frames for
    every camera with a profile enabled — i.e. the normal case."""
    from app.timelapse import TimelapseBuilder

    _write_frames(tmp_storage_root, "cam6", "daily", "2026-08-28", 3, 10, day="2026-08-28")
    _write_frames(tmp_storage_root, "cam6", "custom", "2026-08-28_140000", 2, 10, day="2026-08-28")
    _write_frames(tmp_storage_root, "cam6", "daily", "2026-08-27", 5, 10, day="2026-08-27")
    flat = tmp_storage_root / "timelapse_frames" / "cam6" / "2026-08-28"
    flat.mkdir(parents=True)
    (flat / "legacy.jpg").write_bytes(b"x")

    found = TimelapseBuilder(tmp_storage_root).frames_for_day("cam6", "2026-08-28")
    # 3 daily + 2 custom (prefix-matched window) + 1 legacy flat frame;
    # the previous day's 5 frames stay out.
    assert len(found) == 6


# ── C1 · the four profiles the window-key change made real ──────────────


def test_window_covers_day_holds_for_every_profile():
    """``key.startswith(day)`` is only ever true for daily and custom.
    2026-W35 / 2026-08 / 2026-Q3 / 2026 never start with an ISO date."""
    day = "2026-08-28"
    for profile, key in (
        ("daily", "2026-08-28"),
        ("weekly", "2026-W35"),
        ("monthly", "2026-08"),
        ("quarterly", "2026-Q3"),
        ("yearly", "2026"),
        ("custom", "2026-08-28_140000"),
    ):
        assert window_covers_day(profile, key, day), profile
        assert not key.startswith(day) or profile in ("daily", "custom")
    assert not window_covers_day("weekly", "2026-W34", day)
    assert not window_covers_day("monthly", "2026-07", day)


def test_frames_for_day_finds_the_calendar_profiles(tmp_storage_root):
    """C1 · with all six profiles collecting, the endpoints used to see
    6 of 18 frames — /api/camera/<id>/timelapse answered ``no_frames``
    for weekly, monthly, quarterly and yearly."""
    from app.timelapse import TimelapseBuilder

    day = "2026-08-28"
    for profile, key in (
        ("daily", "2026-08-28"),
        ("weekly", "2026-W35"),
        ("monthly", "2026-08"),
        ("quarterly", "2026-Q3"),
        ("yearly", "2026"),
        ("custom", "2026-08-28_140000"),
    ):
        _write_frames(tmp_storage_root, "cam7", profile, key, 3, 10, day=day)

    found = TimelapseBuilder(tmp_storage_root).frames_for_day("cam7", day)
    assert len(found) == 18


def test_a_multi_day_window_only_yields_the_requested_day(tmp_storage_root):
    """A weekly window holds seven days in ONE directory. Matching the
    window must not hand the encoder the whole week."""
    from app.timelapse import TimelapseBuilder

    _write_frames(tmp_storage_root, "cam8", "weekly", "2026-W35", 4, 10, day="2026-08-28")
    _write_frames(tmp_storage_root, "cam8", "weekly", "2026-W35", 6, 10, day="2026-08-26", hour=9)

    found = TimelapseBuilder(tmp_storage_root).frames_for_day("cam8", "2026-08-28")
    assert len(found) == 4


def test_two_profiles_interleave_chronologically(tmp_storage_root):
    """C2 · sorting by ``(parent.name, name)`` concatenated the sets, so
    a camera with daily AND custom on produced an MP4 that played the
    day and then replayed the last custom window."""
    from app.timelapse import TimelapseBuilder

    day = "2026-08-28"
    _write_frames(tmp_storage_root, "cam9", "daily", "2026-08-28", 2, 10, day=day, hour=8)
    _write_frames(tmp_storage_root, "cam9", "custom", "2026-08-28_100000", 2, 10, day=day, hour=10)
    _write_frames(tmp_storage_root, "cam9", "daily", "2026-08-28", 2, 10, day=day, hour=14)

    stamped = TimelapseBuilder(tmp_storage_root).frames_for_day_stamped("cam9", day)
    assert [ts for ts, _ in stamped] == sorted(ts for ts, _ in stamped)
    # The custom window's frames sit in the MIDDLE, not appended at the end.
    parents = [p.parent.name for _, p in stamped]
    assert parents.index("2026-08-28_100000") < parents.count("2026-08-28")


# ── D1 · closed windows are part of the number ──────────────────────────


def test_usage_counts_every_window_not_just_the_newest(tmp_storage_root):
    """The measured case: 900 un-encoded frames from yesterday plus 120
    current reported as 120 frames / 120 kB — an 88 % under-report in
    exactly the situation the number exists to report."""
    timelapse_storage.invalidate("camD")
    _write_frames(tmp_storage_root, "camD", "daily", "2026-08-27", 900, 1000, day="2026-08-27")
    _write_frames(tmp_storage_root, "camD", "daily", "2026-08-28", 120, 1000, day="2026-08-28")

    usage = timelapse_storage.profile_usage(tmp_storage_root, "camD", "daily")
    assert usage["frame_count"] == 1020
    assert usage["bytes_on_disk"] == 1_020_000
    # …while still naming and isolating the window being captured into.
    assert usage["window_key"] == "2026-08-28"
    assert usage["current_frame_count"] == 120
    assert usage["pending_windows"] == 1


def test_storage_stats_inherits_the_full_total(tmp_storage_root):
    """/api/media/storage-stats' timelapse_frames_mb sums profile_usage,
    so it under-reported by the same margin."""
    timelapse_storage.invalidate("camE")
    _write_frames(tmp_storage_root, "camE", "daily", "2026-08-27", 5, 1000, day="2026-08-27")
    _write_frames(tmp_storage_root, "camE", "daily", "2026-08-28", 2, 1000, day="2026-08-28")
    _write_frames(tmp_storage_root, "camE", "weekly", "2026-W35", 3, 1000, day="2026-08-28")
    total = timelapse_storage.camera_frames_bytes(tmp_storage_root, "camE", TIMELAPSE_PROFILES)
    assert total == 10_000


def test_cache_key_includes_the_storage_root(tmp_path, tmp_storage_root):
    """D2 · a root-blind key served one tree's numbers for another."""
    other = tmp_path / "other-storage"
    timelapse_storage.invalidate("camF")
    _write_frames(tmp_storage_root, "camF", "daily", "2026-08-28", 4, 100, day="2026-08-28")
    _write_frames(other, "camF", "daily", "2026-08-28", 9, 100, day="2026-08-28")
    assert timelapse_storage.profile_usage(tmp_storage_root, "camF", "daily")["frame_count"] == 4
    assert timelapse_storage.profile_usage(other, "camF", "daily")["frame_count"] == 9


def test_invalidate_clears_every_root_for_the_camera(tmp_path, tmp_storage_root):
    other = tmp_path / "other-storage2"
    timelapse_storage.invalidate("camG")
    _write_frames(tmp_storage_root, "camG", "daily", "2026-08-28", 1, 100, day="2026-08-28")
    _write_frames(other, "camG", "daily", "2026-08-28", 1, 100, day="2026-08-28")
    timelapse_storage.profile_usage(tmp_storage_root, "camG", "daily")
    timelapse_storage.profile_usage(other, "camG", "daily")
    timelapse_storage.invalidate("camG", "daily")
    assert not [k for k in timelapse_storage._cache if k[1] == "camG"]


# ── B2 · the shipped defaults must not be clamped ───────────────────────


def test_shipped_profile_defaults_are_never_clamped():
    """Enabling ``custom`` with its shipped default used to yield a
    FIVE-second video: 600 s window / 30 s target at 15 fps → 1.33 s raw
    → clamped to 8 s → 75 frames → 5 s. A silent 6× cut behind one
    WARNING. The 8 s floor protects the detection loop and stays; the
    shipped period is the free variable."""
    from app.settings._consts import TL_DEFAULT_PROFILES

    for name, spec in TL_DEFAULT_PROFILES.items():
        interval, clamped = capture_interval_s(
            spec["period_seconds"], spec["target_seconds"], FIXED_FPS
        )
        assert not clamped, f"{name} ships a clamped default ({interval:.1f}s interval)"
        realised = int(spec["period_seconds"] / interval) / FIXED_FPS
        assert realised >= spec["target_seconds"] * 0.99, name


def test_runtime_period_fallbacks_mirror_the_shipped_defaults():
    """The two copies disagreed on `custom` (600 vs 3600) and the loop
    read the wrong one."""
    from app.camera_runtime._consts import _PROFILE_PERIOD_DEFAULTS
    from app.settings._consts import TL_DEFAULT_PROFILES

    assert _PROFILE_PERIOD_DEFAULTS == {
        n: s["period_seconds"] for n, s in TL_DEFAULT_PROFILES.items()
    }
    assert set(_PROFILE_PERIOD_DEFAULTS) == set(TIMELAPSE_PROFILES)


# ── B1 · the legacy loop's cadence ──────────────────────────────────────


def test_legacy_rolling_10min_no_longer_captures_twice_a_second():
    """The loop ``_lifecycle`` starts whenever timelapse.enabled is true
    and no profile is on computed its own ``max(0.5, period/frames)``
    with an fps fallback of 25. ``period: rolling_10min`` resolved to
    0.5 s — two captures a second, per camera, against a detection loop
    running at ~2 Hz. It goes through capture_interval_s now."""
    import inspect

    from app.camera_runtime import _timelapse as tl_mod

    src = _code_only(inspect.getsource(tl_mod.TimelapseMixin._timelapse_loop))
    assert "max(0.5" not in src
    assert "capture_interval_s" in src
    interval, clamped = capture_interval_s(tl_mod._LEGACY_PERIOD_S["rolling_10min"], 60, FIXED_FPS)
    assert clamped is True
    assert interval == MIN_INTERVAL_S


# ── B3 · the retry actually retries ─────────────────────────────────────


def test_retry_waits_longer_than_the_measured_frame_cadence():
    """0.5 s sat on the ~0.49 s/frame boundary, so the re-grab mostly
    handed back the buffer that had just been rejected."""
    from app.camera_runtime._timelapse_capture import RETRY_WAIT_S

    assert RETRY_WAIT_S > 0.5


def test_retry_skips_a_buffer_that_has_not_moved():
    """The old ``for retry in range(1, 2)`` re-validated the identical
    rejected frame — it never re-read frame_ts, unlike the outer loop."""
    import inspect

    from app.camera_runtime._timelapse_capture import TimelapseCaptureMixin

    src = _code_only(inspect.getsource(TimelapseCaptureMixin._tl_valid_or_retry))
    assert "for retry in range" not in src
    assert "cand_ts == frame_ts" in src


class _Buf:
    """Stand-in for a numpy frame: identity-comparable and .copy()able."""

    def __init__(self, tag: str):
        self.tag = tag

    def copy(self):
        return self

    def __eq__(self, other):
        return isinstance(other, _Buf) and other.tag == self.tag

    def __repr__(self):
        return f"_Buf({self.tag})"


def test_a_stale_buffer_is_not_revalidated(monkeypatch):
    """Behavioural half of the above: one validation, not two, when the
    frame buffer has not been refreshed by the time the retry fires."""
    import threading

    from app.camera_runtime import _timelapse_capture as cap_mod

    calls = []

    def _fake_valid(frame, profile=None):
        calls.append(frame)
        return False, "too_dark"

    monkeypatch.setattr("app.frame_helpers.is_valid_frame", _fake_valid)
    monkeypatch.setattr(cap_mod.time, "sleep", lambda _s: None)

    rt = cap_mod.TimelapseCaptureMixin()
    rt.camera_id = "camR"
    rt.lock = threading.Lock()
    rt.frame = _Buf("stale")
    rt.frame_ts = 100.0
    st = cap_mod.CaptureState()
    _frame, ok, _reason, attempt = rt._tl_valid_or_retry(_Buf("stale"), 100.0, "weekly", st)
    assert ok is False
    assert attempt == 0
    assert len(calls) == 1, "the unchanged buffer must not be validated twice"


def test_a_refreshed_buffer_is_retried_and_accepted(monkeypatch):
    import threading

    from app.camera_runtime import _timelapse_capture as cap_mod

    def _fake_valid(frame, profile=None):
        return (frame == _Buf("fresh")), "too_dark"

    monkeypatch.setattr("app.frame_helpers.is_valid_frame", _fake_valid)
    monkeypatch.setattr(cap_mod.time, "sleep", lambda _s: None)

    rt = cap_mod.TimelapseCaptureMixin()
    rt.camera_id = "camR"
    rt.lock = threading.Lock()
    rt.frame = _Buf("fresh")
    rt.frame_ts = 101.0
    st = cap_mod.CaptureState()
    frame, ok, _reason, attempt = rt._tl_valid_or_retry(_Buf("stale"), 100.0, "daily", st)
    assert (frame, ok, attempt) == (_Buf("fresh"), True, 1)


def test_camera_frames_bytes_sums_every_profile(tmp_storage_root):
    timelapse_storage.invalidate("cam5")
    _write_frames(tmp_storage_root, "cam5", "daily", "2026-08-28", 3, 100)
    _write_frames(tmp_storage_root, "cam5", "weekly", "2026-W35", 2, 100)
    total = timelapse_storage.camera_frames_bytes(
        tmp_storage_root, "cam5", ("daily", "weekly", "monthly")
    )
    assert total == 500
