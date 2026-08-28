"""The thunder threshold was on the wrong physical scale entirely.

`lightning_potential` from Open-Meteo is the Lightning Potential Index
after Lynn & Yair (2010) — a native ICON-D2 field, "the vertical integral
of the squared updraft velocity weighted by a function that essentially
contains the graupel concentration". Its unit is J/kg, which reads like
CAPE and is nothing like it: published observed thunderstorm cases run
**0.2 to 0.8 J/kg**.

The shipped threshold was 1000.0. That is roughly a thousandfold too
high — it could not fire for any storm that has ever existed, and on
2026-08-28 it did not: the operator watched a thunderstorm with visible
lightning and heavy rain while the archive stayed empty and the panel
read "Blitz-Potential 0 J/kg". The 12:53 sample was 1 J/kg — ABOVE the
published thunderstorm range, and still three orders of magnitude under
its own trigger.

Two consequences the same error caused, both pinned below:
  * the severity scale divided by 3000, so a real storm scored ~0.0003
    and could never clear `push.weather.min_score = 0.4` even if the
    trigger had fired;
  * the archive's INTENSITY_REFERENCE divided by the same 3000, so
    lightning contributed nothing to how "krass" a storm ranked.
"""

from __future__ import annotations

from app.settings._consts import WEATHER_DEFAULTS
from app.settings.migrations import migrate_thunder_lpi_scale
from app.weather_episodes._consts import INTENSITY_REFERENCE

# The band the literature reports for observed thunderstorms.
OBSERVED_LO, OBSERVED_HI = 0.2, 0.8


def _thunder_threshold() -> float:
    return float(WEATHER_DEFAULTS["events"]["thunder"]["threshold"])


def test_the_shipped_threshold_is_on_the_lpi_scale():
    """A threshold above the observed band can never fire on a real storm."""
    thr = _thunder_threshold()
    assert thr <= OBSERVED_LO, (
        "even the WEAKEST published thunderstorm case must cross the trigger; "
        f"observed band is {OBSERVED_LO}-{OBSERVED_HI} J/kg, threshold is {thr}"
    )
    assert thr > 0.0, "a zero threshold would make every calm minute a thunderstorm"


def test_the_intensity_reference_is_on_the_same_scale():
    """Trigger and ranking must agree about what the numbers mean."""
    ref = INTENSITY_REFERENCE["lightning_potential"]
    assert OBSERVED_HI < ref < 100.0, f"reference {ref} is not an LPI magnitude"


def test_the_operators_storm_ranks_as_a_normal_strong_thunderstorm():
    """1 J/kg on 2026-08-28 — they called it 'ein fettes Gewitter'.

    It must clear the trigger comfortably and land mid-scale on
    intensity, not at either extreme.
    """
    measured = 1.0
    assert measured > _thunder_threshold()
    axis = min(1.0, measured / INTENSITY_REFERENCE["lightning_potential"])
    assert 0.35 <= axis <= 0.75, f"expected a mid-scale reading, got {axis:.2f}"


# ── the migration ─────────────────────────────────────────────────────
#
# Settings are merged additively everywhere else in this project, on
# purpose. This one migration overwrites, because a value three orders
# of magnitude outside its own index's range is a unit error rather than
# a preference — and additive merging would preserve it forever.


def test_a_cape_scale_value_is_corrected():
    data = {"weather": {"events": {"thunder": {"enabled": True, "threshold": 1000.0}}}}
    migrate_thunder_lpi_scale(data)
    assert data["weather"]["events"]["thunder"]["threshold"] == _thunder_threshold()


def test_a_hand_tuned_lpi_value_is_left_alone():
    """The guard is conservative — only absurd values are touched."""
    for kept in (0.15, 0.5, 2.0, 25.0, 99.0):
        data = {"weather": {"events": {"thunder": {"threshold": kept}}}}
        migrate_thunder_lpi_scale(data)
        assert data["weather"]["events"]["thunder"]["threshold"] == kept


def test_the_migration_is_idempotent():
    data = {"weather": {"events": {"thunder": {"threshold": 1000.0}}}}
    migrate_thunder_lpi_scale(data)
    once = data["weather"]["events"]["thunder"]["threshold"]
    migrate_thunder_lpi_scale(data)
    assert data["weather"]["events"]["thunder"]["threshold"] == once


def test_a_settings_file_without_the_block_survives():
    for data in ({}, {"weather": {}}, {"weather": {"events": {}}}):
        migrate_thunder_lpi_scale(data)  # must not raise


def test_a_non_numeric_threshold_is_not_crashed_on():
    data = {"weather": {"events": {"thunder": {"threshold": "hoch"}}}}
    migrate_thunder_lpi_scale(data)
    assert data["weather"]["events"]["thunder"]["threshold"] == "hoch"
