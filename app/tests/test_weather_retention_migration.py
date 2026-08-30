"""Per-category weather retention defaults must backfill additively.

One blanket `weather.retention_days` used to govern every kind of
weather media — a quarterly recap and a daily sunrise clip have
nothing in common retention-wise. `migrate_weather_defaults` now also
backfills four independent `retention_<category>_days` keys (see
`settings/_consts.py::WEATHER_RETENTION_DEFAULTS`), but the legacy pair
must survive untouched on a real install, and a category the install
already configured (by hand, or from a later version) must never be
clobbered back to the shipped default.
"""

from __future__ import annotations

from app.settings._consts import WEATHER_RETENTION_DEFAULTS
from app.settings.migrations import migrate_weather_defaults


def test_a_fresh_install_gets_every_category_default():
    data: dict = {}
    migrate_weather_defaults(data)
    w = data["weather"]
    assert w["retention_days"] == 90
    assert w["auto_cleanup_enabled"] is True
    assert w["retention_sightings_days"] == 90
    assert w["retention_event_timelapses_days"] == 120
    assert w["retention_sun_timelapses_days"] == 21
    assert w["retention_recaps_days"] == 400


def test_an_existing_blanket_value_survives_untouched():
    """The value a real install already saved under the old single
    slider must not be dropped or reinterpreted."""
    data = {"weather": {"retention_days": 45, "auto_cleanup_enabled": False}}
    migrate_weather_defaults(data)
    w = data["weather"]
    assert w["retention_days"] == 45
    assert w["auto_cleanup_enabled"] is False


def test_the_blanket_value_does_not_leak_into_new_category_keys():
    """A category key is backfilled with ITS OWN shipped default, not
    with whatever the legacy blanket slider happened to hold."""
    data = {"weather": {"retention_days": 45}}
    migrate_weather_defaults(data)
    w = data["weather"]
    assert w["retention_sightings_days"] == 90
    assert w["retention_sun_timelapses_days"] == 21
    assert w["retention_recaps_days"] == 400


def test_a_category_the_install_already_configured_is_never_clobbered():
    data = {"weather": {"retention_sun_timelapses_days": 5}}
    migrate_weather_defaults(data)
    assert (
        data["weather"]["retention_sun_timelapses_days"] == 5
    ), "an operator-set value must survive a re-migration unchanged"


def test_migration_is_idempotent():
    data: dict = {}
    migrate_weather_defaults(data)
    first = dict(data["weather"])
    migrate_weather_defaults(data)
    assert data["weather"] == first


def test_defaults_dict_carries_exactly_the_documented_keys():
    """Pins the contract migrate_weather_defaults relies on — a typo'd
    or renamed key here would silently stop backfilling a category."""
    assert set(WEATHER_RETENTION_DEFAULTS) == {
        "retention_days",
        "auto_cleanup_enabled",
        "retention_sightings_days",
        "retention_event_timelapses_days",
        "retention_sun_timelapses_days",
        "retention_recaps_days",
        "retention_manual_events_days",
    }
