"""The forced-reconnect warning must report the streak it recovered from.

``_timelapse_capture`` raises ``_force_reconnect`` only once a profile has
seen ``stale_streak >= 15`` consecutive stale reads, so that counter is
the whole reason the log line exists — it is the operator's only trace of
how long the feed had been wedged before the recovery kicked in.

The reset used to sit one line ABOVE the log call:

    self._force_reconnect = False
    self._stale_streak = 0          # cleared here
    log_cam.warning(..., self._stale_streak, ...)   # always 0

Nothing wrote to the attribute in between, so the warning could only ever
print ``stale_streak=0`` — guaranteed wrong, and guaranteed to hide a
number that is always at least 15.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.camera_runtime._lifecycle import LifecycleMixin  # noqa: E402


class _Cam(LifecycleMixin):
    def __init__(self, stale_streak: int):
        self.camera_id = "acme_cam_garden_113"
        self._stale_streak = stale_streak
        self.frame_ts = time.time() - 42.0

    def _reconnect_count_24h(self) -> int:
        return 3


def test_the_warning_carries_the_streak_it_is_recovering_from(caplog):
    cam = _Cam(stale_streak=17)
    with caplog.at_level(logging.WARNING):
        cam._note_forced_reconnect()

    line = "\n".join(r.getMessage() for r in caplog.records)
    assert "forced reconnect" in line, "the recovery was not reported at all"
    assert "stale_streak=17" in line, f"the streak was lost from the diagnostic: {line!r}"
    assert "reconnects_24h=3" in line


def test_the_streak_is_cleared_after_it_has_been_reported(caplog):
    """Reporting must not cost the reset — the next stall has to start
    counting from zero again."""
    cam = _Cam(stale_streak=17)
    with caplog.at_level(logging.WARNING):
        cam._note_forced_reconnect()

    assert cam._stale_streak == 0, "the streak was never cleared, so it would keep growing"
