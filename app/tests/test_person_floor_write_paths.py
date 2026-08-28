"""Every write path to a security camera's person spawn respects the floor.

`clamp_manual_e` guards the Netz. It does not guard the two routes that
write `label_thresholds` directly, and both accepted `person: 0.95` —
on Werkstatt or Garten that means a person must be recognised with 95 %
confidence before a track even starts. The camera is blind, and nothing
in the UI says so.

`AUTO_E_FLOOR_PERSON_SECURITY` (E 35) maps to a person spawn of 0.54,
which is therefore the ceiling. A wildlife-role camera is untouched: a
bird feeder has no intruder to miss.
"""

from __future__ import annotations

import pytest

from app.thresholds._apply import (
    AUTO_E_FLOOR_PERSON_SECURITY,
    clamp_person_label_threshold,
    spawn_for,
)

SECURITY = {"id": "cam_sec", "role": "security"}
WILDLIFE = {"id": "cam_wild", "role": "wildlife"}


def _ceiling() -> float:
    return spawn_for("person", AUTO_E_FLOOR_PERSON_SECURITY)


def test_the_ceiling_is_derived_not_guessed():
    """Pinned so a future edit cannot quietly re-hard-code it."""
    assert _ceiling() == pytest.approx(0.54)


def test_a_blinding_person_threshold_is_capped():
    out = clamp_person_label_threshold(SECURITY, {"person": 0.95})
    assert out["person"] == pytest.approx(_ceiling())


def test_a_reasonable_value_passes_through():
    out = clamp_person_label_threshold(SECURITY, {"person": 0.45})
    assert out["person"] == pytest.approx(0.45)


def test_a_wildlife_camera_is_not_clamped():
    out = clamp_person_label_threshold(WILDLIFE, {"person": 0.95})
    assert out["person"] == pytest.approx(0.95)


def test_other_classes_are_untouched():
    src = {"cat": 0.95, "squirrel": 0.9}
    assert clamp_person_label_threshold(SECURITY, src) == src


def test_the_callers_dict_is_not_mutated():
    src = {"person": 0.95}
    clamp_person_label_threshold(SECURITY, src)
    assert src["person"] == 0.95


def test_a_non_numeric_value_does_not_crash():
    out = clamp_person_label_threshold(SECURITY, {"person": "hoch"})
    assert out["person"] == "hoch"


def test_both_write_routes_apply_the_clamp():
    """The two routes that bypass the Netz's own guard.

    A source assertion on purpose: the behavioural cover lives in the
    unit tests above, and what this pins is that neither call site is
    removed in a refactor — which is exactly how the rail went missing
    the first time.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "routes" / "cameras.py"
    text = src.read_text(encoding="utf-8")
    assert text.count("clamp_person_label_threshold(") == 2, "expected one call per write path"
    assert text.count("import clamp_person_label_threshold") == 2
