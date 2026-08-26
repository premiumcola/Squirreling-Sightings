"""F-2 · late-confirming labels must reach the in-flight event.

The event's labels were set once, at recording start — and that start is
decided by MOTION, which confirms much sooner than a class does. Motion
needs 2 of 3 frames (~0.7 s at the 350 ms cadence); a person needs 3
hits in 5 s (~1.05 s). Motion wins the race almost every time, so the
event is filed as ``labels=["motion"]`` and stays that way for the whole
clip. Every downstream decision then reads "motion": it is ``off`` in
the severity matrix and ``push:false`` in the push config, so a clip
that plainly shows a person produces no alert.

The contradiction was visible in the stored JSON all along — ``top_label``
came from the *unconfirmed* detections, so events read
``top_label: "person"`` right next to ``labels: ["motion"]``.
"""

from __future__ import annotations

import pytest

from app.camera_runtime._motion import MotionMixin


class _Det:
    def __init__(self, label, score):
        self.label = label
        self.score = score

    def to_dict(self):
        return {"label": self.label, "score": self.score}


class _Cam(MotionMixin):
    def __init__(self, **cfg):
        self.camera_id = "cam-test"
        self.cfg = {"armed": True, "alarm_profile": "soft", **cfg}
        self._rec_event_meta = {
            "event_id": "evt-1",
            "labels": ["motion"],
            "top_label": "motion",
            "detections": [],
            "whitelisted": False,
            "after_hours": False,
            "alarm_level": "info",
            "severity": "off",
            "notify": False,
        }


def test_person_confirming_late_upgrades_the_event():
    cam = _Cam(class_severity={"person": "alarm", "motion": "off"})
    changed = cam._upgrade_event_meta(["person"], [_Det("person", 0.71)])

    assert changed is True
    assert cam._rec_event_meta["labels"] == ["person"]
    assert cam._rec_event_meta["top_label"] == "person"


def test_the_upgrade_also_re_decides_notify():
    """Carrying "person" while keeping motion's notify=False would be the
    same silent drop wearing a better label."""
    cam = _Cam(class_severity={"person": "alarm", "motion": "off"})
    assert cam._rec_event_meta["notify"] is False

    cam._upgrade_event_meta(["person"], [_Det("person", 0.71)])

    assert cam._rec_event_meta["notify"] is True
    assert cam._rec_event_meta["severity"] == "alarm"


def test_motion_is_dropped_once_a_real_class_is_known():
    cam = _Cam(class_severity={"squirrel": "info", "motion": "off"})
    cam._upgrade_event_meta(["squirrel"], [_Det("squirrel", 0.6)])

    assert "motion" not in cam._rec_event_meta["labels"]


def test_nothing_new_means_no_change():
    cam = _Cam(class_severity={"person": "alarm"})
    cam._rec_event_meta["labels"] = ["person"]
    assert cam._upgrade_event_meta(["person"], [_Det("person", 0.8)]) is False


def test_a_bare_motion_frame_changes_nothing():
    cam = _Cam(class_severity={"person": "alarm", "motion": "off"})
    assert cam._upgrade_event_meta(["motion"], []) is False
    assert cam._rec_event_meta["labels"] == ["motion"]


def test_no_recording_in_flight_is_safe():
    cam = _Cam()
    cam._rec_event_meta = None
    assert cam._upgrade_event_meta(["person"], [_Det("person", 0.9)]) is False


def test_second_class_is_merged_not_replaced():
    cam = _Cam(class_severity={"person": "alarm", "cat": "info"})
    cam._upgrade_event_meta(["cat"], [_Det("cat", 0.6)])
    cam._upgrade_event_meta(["person"], [_Det("person", 0.8)])

    assert set(cam._rec_event_meta["labels"]) == {"cat", "person"}


def test_top_label_follows_the_strongest_detection():
    cam = _Cam(class_severity={"person": "alarm", "cat": "info"})
    cam._upgrade_event_meta(["cat", "person"], [_Det("cat", 0.55), _Det("person", 0.88)])

    assert cam._rec_event_meta["top_label"] == "person"


def test_whitelisted_events_stay_silent():
    """A whitelisted subject must not start notifying just because the
    label got sharper."""
    cam = _Cam(class_severity={"person": "alarm"})
    cam._rec_event_meta["whitelisted"] = True
    cam._upgrade_event_meta(["person"], [_Det("person", 0.9)])

    assert cam._rec_event_meta["notify"] is False


def test_disarmed_camera_stays_silent():
    cam = _Cam(armed=False, class_severity={"person": "alarm"})
    cam._upgrade_event_meta(["person"], [_Det("person", 0.9)])

    assert cam._rec_event_meta["notify"] is False


def test_after_hours_is_read_from_the_key_that_exists():
    """The meta stores this as `after_hours`. Reading a `hard_active` key
    would silently be False forever and downgrade every night event."""
    import inspect

    src = inspect.getsource(MotionMixin._upgrade_event_meta)
    assert 'meta.get("after_hours")' in src
    assert 'meta.get("hard_active")' not in src


@pytest.mark.parametrize("labels", [[], None])
def test_empty_labels_are_ignored(labels):
    cam = _Cam()
    assert cam._upgrade_event_meta(labels, []) is False


def test_main_loop_calls_the_upgrade_while_recording():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "app" / "camera_runtime" / "_main_loop.py"
    ).read_text(encoding="utf-8")
    branch = src[src.index("elif self._recording:") :][:1400]
    assert "_upgrade_event_meta(" in branch, (
        "the upgrade must run on frames DURING the recording — that is the "
        "only window in which a late class confirmation can still be caught"
    )
