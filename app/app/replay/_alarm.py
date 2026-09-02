"""Would this set of labels have raised an alert?

Thin pure wrapper over the live decision function so the replay report
answers the question the operator actually cares about — "would I have
been told about this?" — rather than making them read confidence
numbers and infer it.
"""

from __future__ import annotations

from ..event_logic import choose_alarm_level


def alert_preview(alarm_profile, labels) -> dict:
    """``{level, notify, labels}`` for one side of a comparison.

    Two inputs of ``choose_alarm_level`` are deliberately pinned:

      * ``hard_active`` — whether the camera's "hard" schedule window
        was open. That is a property of the CLOCK at capture time, not
        of the settings under test, and a replay run weeks later cannot
        recover it. Pinned False, so the preview answers "would the
        alarm PROFILE have notified", which is the half a tuning
        change can actually move.
      * ``whitelisted`` — identity whitelisting happens downstream of
        detection and is per-person, not per-tuning. Pinned False.

    Both pins can only make the preview more conservative (they can
    turn an alert off, never invent one), so a "würde alarmieren" in
    the report is never a false promise.
    """
    unique = sorted({str(x) for x in (labels or []) if x})
    level, notify = choose_alarm_level(alarm_profile, unique, False, False)
    return {"level": level, "notify": bool(notify), "labels": unique}
