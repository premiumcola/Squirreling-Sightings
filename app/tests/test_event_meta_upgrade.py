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
    def __init__(self, label, score, species=None, species_latin=None):
        self.label = label
        self.score = score
        self.species = species
        self.species_latin = species_latin

    def to_dict(self):
        return {
            "label": self.label,
            "score": self.score,
            "species": self.species,
            "species_latin": self.species_latin,
        }


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
            # _build_event_meta always stamps this key; the stub models
            # the common case where recording opened on motion alone and
            # no bird had been classified yet.
            "bird_species": None,
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


# ── the bird headline must follow the detections it is derived from ───
#
# `_build_event_meta` derives `bird_species` from the detections of the
# ONE frame where recording started. `_upgrade_event_meta` then replaces
# `meta["detections"]` wholesale with a later frame's — and used to leave
# the derived aggregate untouched, so the two could no longer agree.
#
# This is the common path, not a corner: motion confirms in ~0.7 s and a
# class in ~1.05 s (see this module's own docstring), so a bird event
# almost always opens as `labels=["motion"]` with no bird detection yet,
# and the bird arrives on the upgrade. The species was written to the
# detection and dropped from the headline.
#
# Nothing else repaired it either: bird_species_backfill.py::
# _needs_backfill only selects events where a bird detection is missing
# `species`, so an event whose detection HAS a species but whose headline
# is empty was invisible to the retroactive sweep.


def test_a_bird_confirming_late_brings_its_species_to_the_headline():
    cam = _Cam()
    cam._upgrade_event_meta(
        ["bird"], [_Det("bird", 0.8, species="Blaumeise", species_latin="Cyanistes caeruleus")]
    )
    assert cam._rec_event_meta["bird_species"] == "Blaumeise"


def test_a_later_frames_species_supersedes_the_one_on_record():
    """The headline must name a bird the stored detections actually
    contain — those detections were just replaced."""
    cam = _Cam()
    cam._rec_event_meta["bird_species"] = "Amsel"
    cam._upgrade_event_meta(
        ["bird", "person"],
        [
            _Det("bird", 0.8, species="Blaumeise", species_latin="Cyanistes caeruleus"),
            _Det("person", 0.9),
        ],
    )
    assert cam._rec_event_meta["bird_species"] == "Blaumeise"


def test_an_existing_species_survives_a_later_birdless_frame():
    """A name already won must never be blanked by an upgrade that
    carries no bird — that would lose information the event had."""
    cam = _Cam()
    cam._rec_event_meta["bird_species"] = "Amsel"
    cam._upgrade_event_meta(["person"], [_Det("person", 0.9)])
    assert cam._rec_event_meta["bird_species"] == "Amsel"


def test_an_unclassified_bird_leaves_the_headline_empty():
    """A bird box with no species is not a name. The headline stays
    None so bird_species_backfill.py still selects the event."""
    cam = _Cam()
    cam._upgrade_event_meta(["bird"], [_Det("bird", 0.8)])
    assert cam._rec_event_meta["bird_species"] is None


def test_main_loop_calls_the_upgrade_while_recording():
    """The recording state machine moved to ``_recording_step`` when
    ``_main_loop`` was split back under the 500-line ceiling. The
    invariant is unchanged: the ``elif self._recording:`` arm — the only
    window in which a late class confirmation can still be caught — must
    reach the upgrade, and must reach it BEFORE the clip can be closed.
    """
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "app" / "camera_runtime" / "_recording_step.py"
    ).read_text(encoding="utf-8")
    branch = src[src.index("elif self._recording:") :][:400]
    assert "self._advance_clip(" in branch

    advance = src[src.index("def _advance_clip(") :]
    assert "_upgrade_event_meta(" in advance
    assert advance.index("_upgrade_event_meta(") < advance.index(
        "self._stop_ffmpeg_and_queue_reencode()"
    ), "a label confirmed on the closing frame must still land in the event"
