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

import sys
from datetime import datetime
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import timelapse_storage  # noqa: E402
from app.timelapse_windows import (  # noqa: E402
    MIN_INTERVAL_S,
    capture_interval_s,
    expected_frames,
    next_window_start,
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


def _write_frames(root: Path, cam: str, profile: str, window: str, n: int, size: int) -> Path:
    d = root / "timelapse_frames" / cam / profile / window
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"1200{i:02d}_00.jpg").write_bytes(b"x" * size)
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

    _write_frames(tmp_storage_root, "cam6", "daily", "2026-08-28", 3, 10)
    _write_frames(tmp_storage_root, "cam6", "custom", "2026-08-28_140000", 2, 10)
    _write_frames(tmp_storage_root, "cam6", "daily", "2026-08-27", 5, 10)
    (tmp_storage_root / "timelapse_frames" / "cam6" / "2026-08-28").mkdir(parents=True)
    (tmp_storage_root / "timelapse_frames" / "cam6" / "2026-08-28" / "legacy.jpg").write_bytes(b"x")

    found = TimelapseBuilder(tmp_storage_root).frames_for_day("cam6", "2026-08-28")
    # 3 daily + 2 custom (prefix-matched window) + 1 legacy flat frame;
    # the previous day's 5 frames stay out.
    assert len(found) == 6


def test_camera_frames_bytes_sums_every_profile(tmp_storage_root):
    timelapse_storage.invalidate("cam5")
    _write_frames(tmp_storage_root, "cam5", "daily", "2026-08-28", 3, 100)
    _write_frames(tmp_storage_root, "cam5", "weekly", "2026-W35", 2, 100)
    total = timelapse_storage.camera_frames_bytes(
        tmp_storage_root, "cam5", ("daily", "weekly", "monthly")
    )
    assert total == 500
