"""D2 tile-rescue counters.

The rescue path only ever logged a SUCCESS. That made two very different
situations indistinguishable in the log:

  * roi_mode is off everywhere, so the rescue never runs at all;
  * the rescue runs constantly and finds nothing.

The first calls for a settings change, the second for a different
approach — and neither could be told apart. Counting attempts alongside
hits is what makes the small-object work measurable instead of asserted.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "app"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_counters_are_initialised_on_the_runtime():
    src = _read("camera_runtime/runtime.py")
    assert "self._roi_rescue_attempts: int = 0" in src
    assert "self._roi_rescue_hits: int = 0" in src


def test_every_attempt_is_counted_not_only_successes():
    """The counter must sit before the hit check, or it degenerates back
    into 'successes only' and the distinction is lost again."""
    src = _read("camera_runtime/_rescue.py")
    assert "self._roi_rescue_attempts += 1" in src
    assert "self._roi_rescue_hits += 1" in src

    attempts_at = src.index("self._roi_rescue_attempts += 1")
    hits_at = src.index("self._roi_rescue_hits += 1")
    assert attempts_at < hits_at, "attempts must be counted before the hit branch"


def test_attempt_counter_precedes_the_detection_call():
    """It must count the attempt even when tiled_detect returns nothing."""
    src = _read("camera_runtime/_rescue.py")
    attempts_at = src.index("self._roi_rescue_attempts += 1")
    detect_at = src.index("roi_dets, _sahi = tiled_detect(")
    assert attempts_at < detect_at


def test_counters_are_exposed_in_status():
    src = _read("camera_runtime/_status.py")
    assert '"roi_rescue_attempts"' in src
    assert '"roi_rescue_hits"' in src


def test_heartbeat_reports_the_ratio():
    src = _read("maintenance.py")
    assert "roi_rescue=" in src, "the ratio must reach the heartbeat line"


def test_heartbeat_stays_quiet_when_the_rescue_never_ran():
    """0/0 every five minutes would be noise; absence is the signal."""
    src = _read("maintenance.py")
    assert "if roi_att:" in src
