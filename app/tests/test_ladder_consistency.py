"""Where "what is detected" and "what is reported" disagree.

One real contradiction, and one thing that only LOOKS like one.

Originally written as two contradictions between "what is detected" and "what is reported".

Both were live on all three cameras and both are silent — nothing warns
you that the answer you gave is being overruled somewhere else.

1. THE CAT. `class_severity` is the per-camera, per-label matrix that
   replaced `alarm_profile` as the source of truth. It said `cat = info`
   on every camera. The shipped GLOBAL config says `cat: {push: False}`,
   and the global won. Cats were detected, recorded, listed as active —
   and never reported once.
"""

from __future__ import annotations

import pytest

from app.settings._consts import TELEGRAM_PUSH_DEFAULTS
from app.thresholds._ladder import SOURCE_CAMERA, resolve_effective

PUSH = TELEGRAM_PUSH_DEFAULTS


# ── 1 · the dead zone is DESIGN, and that is worth pinning ───────────────
#
# I tried to make `push <= spawn` an invariant here and 15 existing tests
# said no. They were right: the two-tier model is deliberate — a track
# spawns on weaker evidence than an alert needs, and the Netz mapping
# actively enforces `push >= spawn + 0.10` (MIN_GAP in netz/_mapping.js).
# Collapsing push onto spawn would have fought the whole calibration model
# and the Netz would have pushed it straight back up.
#
# So the band is not a defect to remove. What IS actionable is when a
# camera can never reach its own push bar — see the Werkstatt numbers in
# the test below, which is a CALIBRATION fact about one camera, fixed by
# dragging that camera's axis, not by changing the model for everyone.


@pytest.mark.parametrize("label", ["person", "dog", "car", "squirrel"])
def test_the_two_tier_gap_is_intentional_and_stays(label):
    eff = resolve_effective({}, PUSH, label)
    assert eff.push > eff.spawn, (
        f"{label}: push collapsed onto spawn — the two-tier model is deliberate "
        "and netz/_mapping.js enforces a 0.10 minimum gap"
    )


def test_a_camera_whose_scores_never_reach_its_push_bar_is_a_calibration_issue():
    """The Werkstatt reality, recorded so the numbers are not lost: the
    detector reports people at 0.46-0.54 there, while the shipped push bar
    is 0.85. No global default change fixes that — only that camera's own
    threshold does, which is exactly what the Netz axis writes."""
    observed_person_scores = [0.46, 0.48, 0.50, 0.52, 0.54]
    shipped = resolve_effective({}, PUSH, "person")
    assert max(observed_person_scores) < shipped.push

    tuned = resolve_effective({"push_thresholds": {"person": 0.50}}, PUSH, "person")
    assert (
        max(observed_person_scores) >= tuned.push
    ), "a per-camera push threshold is the lever that makes this camera report"


# ── 2 · the camera's own matrix decides ───────────────────────────────────


def test_a_camera_that_says_info_gets_reported_despite_the_global_no():
    """THE cat. Shipped global says push:False; this camera says info."""
    cam = {"class_severity": {"cat": "info"}}
    eff = resolve_effective(cam, PUSH, "cat")
    assert eff.push_enabled is True
    assert eff.source["push_enabled"] == SOURCE_CAMERA


def test_a_camera_that_says_off_stays_muted_despite_the_global_yes():
    """The matrix outranks in BOTH directions — muting a class must
    keep working, or this "fix" becomes an alert flood."""
    cam = {"class_severity": {"person": "off"}}
    eff = resolve_effective(cam, PUSH, "person")
    assert eff.push_enabled is False
    assert eff.source["push_enabled"] == SOURCE_CAMERA


def test_alarm_severity_reports_too():
    cam = {"class_severity": {"person": "alarm"}}
    assert resolve_effective(cam, PUSH, "person").push_enabled is True


def test_a_camera_with_no_matrix_falls_back_to_the_global():
    """Unconfigured cameras must behave exactly as before."""
    assert resolve_effective({}, PUSH, "cat").push_enabled is False
    assert resolve_effective({}, PUSH, "person").push_enabled is True


def test_a_label_missing_from_the_matrix_falls_back_to_the_global():
    cam = {"class_severity": {"person": "alarm"}}
    assert resolve_effective(cam, PUSH, "cat").push_enabled is False


def test_the_three_real_cameras_have_no_silent_contradiction():
    """The concrete configurations from storage/settings.json."""
    werkstatt = {
        "object_filter": ["cat", "dog", "person"],
        "class_severity": {"person": "alarm", "cat": "info", "dog": "info", "bird": "off"},
    }
    for label in werkstatt["object_filter"]:
        eff = resolve_effective(werkstatt, PUSH, label)
        assert eff.push_enabled is True, (
            f"{label} is in this camera's object_filter and its matrix does not mute it, "
            "yet it can never be reported"
        )
