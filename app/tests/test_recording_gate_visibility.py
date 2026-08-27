"""A blocked recording must say so.

Two gates sat between confirmed motion and a clip, and both `continue`d
in total silence:

    if not self.cfg.get("recording_enabled", True):        -> continue
    if not is_schedule_window_active(schedule_record):     -> continue

From outside, a camera that is switched off for recording, a camera
outside its night-only recording window, and a camera whose detector is
broken produce exactly the same evidence: no clip, no event, no library
entry, no log line. A user who walks past at midday with a 21:00→06:00
recording schedule has no way to tell which of the three happened.

The schedule that blocks here is `schedule_record` — a DIFFERENT setting
from `schedule_notify`, which only governs alerts. Conflating them is
easy and the log line now names which one fired.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "app" / "camera_runtime"


def _loop_src() -> str:
    return (SRC / "_main_loop.py").read_text(encoding="utf-8")


def test_both_gates_log_before_they_skip():
    src = _loop_src()
    gate = src[src.index("if has_motion and not self._recording:") :][:2200]
    assert "recording_enabled=False" in gate
    assert "schedule_record" in gate
    assert "NOT recording" in gate, "a silent skip is the defect being fixed"


def test_the_log_names_which_gate_fired():
    """ "not recording" without a reason would still leave the user
    guessing between the two."""
    src = _loop_src()
    gate = src[src.index("if has_motion and not self._recording:") :][:2200]
    assert "_block = " in gate
    assert "%s" in gate, "reason must be interpolated lazily, per CLAUDE.md"


def test_the_line_is_throttled():
    """Motion fires several times a second; an unthrottled line would
    bury the log it is meant to make readable."""
    src = _loop_src()
    gate = src[src.index("if has_motion and not self._recording:") :][:2200]
    assert "_rec_block_logged_at" in gate
    assert "60.0" in gate


def test_the_throttle_field_is_initialised():
    src = (SRC / "runtime.py").read_text(encoding="utf-8")
    assert "self._rec_block_logged_at: float = 0.0" in src


def test_the_gate_still_skips():
    """Visibility only — the gate must keep blocking, not start recording."""
    src = _loop_src()
    gate = src[src.index("if has_motion and not self._recording:") :][:2200]
    assert "continue" in gate
