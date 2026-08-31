"""The unified Mediathek-Verwaltung panel: one catalog, every window
lowerable.

The defect this file exists to prevent is silent and one-directional. A
retention row that SAVES but never ACKNOWLEDGES can be raised and never
lowered: `storage_retention.nightly_window` keeps deferring to the wider
previously-enforced window forever, and the UI shows the new number the
whole time. It was live for the Mediathek slider until it got a
hand-written acknowledger; the weather sliders got a second one; the
camera-timelapse and Papierkorb windows had no UI at all, so nobody
noticed there was a third and fourth category to forget.

So the row set is data now (`app/retention_catalog.py`) and every
consumer derives from it. What is pinned here:

  * every row of every section is acknowledged on save — the property,
    checked per row, not per hand-written loop;
  * the runtime keys match what the existing sweeps already use, so an
    install upgrading into this code does not lose the window it has
    been enforcing;
  * the additive migration seeds the new keys and never
    `storage.retention_days` (that one would freeze config.yaml);
  * a category with no explicit value still resolves through the layers
    it always did.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state, maintenance, retention_catalog, storage_retention  # noqa: E402
from app.retention_catalog import (  # noqa: E402
    RETENTION_GROUPS,
    RETENTION_ROWS,
    acknowledge_payload,
    panel_groups,
    resolve_days,
    rows_for_section,
)
from app.settings._consts import (  # noqa: E402
    STORAGE_RETENTION_DEFAULTS,
    TRASH_DEFAULTS,
    WEATHER_RETENTION_DEFAULTS,
)
from app.settings.retention_migration import migrate_retention_defaults  # noqa: E402


@pytest.fixture
def runtime(monkeypatch):
    """A settings stub whose runtime.* dict the test can read back —
    that dict is where the widening guard records what it enforced."""
    store: dict = {}
    data: dict = {}
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(
            data=data,
            runtime_get=lambda key, default=None: store.get(key, default),
            runtime_set=store.__setitem__,
        ),
        raising=False,
    )
    monkeypatch.setattr(app_state, "base_cfg", {}, raising=False)
    return store, data


# ── the row set ────────────────────────────────────────────────────────


def test_the_panel_carries_every_category_that_deletes_something():
    """One panel, and it is not allowed to be a subset. Two of these had
    no control anywhere before: camera timelapses were exempt from every
    sweep, and the Papierkorb-Frist was settable only by hand-editing
    settings.json."""
    assert {row.key for row in RETENTION_ROWS} == {
        "motion_clips",
        "camera_timelapses",
        "weather_sightings",
        "weather_event_timelapses",
        "weather_sun_timelapses",
        "weather_recaps",
        "weather_manual_events",
        "trash_grace",
    }


def test_every_row_has_its_own_runtime_key():
    """Two categories sharing a guard key means confirming one silently
    confirms the other."""
    keys = [row.runtime_key for row in RETENTION_ROWS]
    assert len(set(keys)) == len(keys)


def test_the_runtime_keys_are_the_ones_the_sweeps_already_use():
    """An upgrading install must keep its enforced windows. A renamed key
    reads as "nothing was ever enforced", which re-opens the widening
    guard on every category at once."""
    from app.weather_service._retention import weather_retention_runtime_key

    by_key = {row.key: row for row in RETENTION_ROWS}
    assert by_key["motion_clips"].runtime_key == storage_retention.ENFORCED_KEY
    for row_key, category in (
        ("weather_sightings", "sightings"),
        ("weather_event_timelapses", "event_timelapses"),
        ("weather_sun_timelapses", "sun_timelapses"),
        ("weather_recaps", "recaps"),
        ("weather_manual_events", "manual_events"),
    ):
        assert by_key[row_key].runtime_key == weather_retention_runtime_key(category)


def test_defaults_are_imported_not_restated():
    """A second copy of a shipped default drifts. These have to BE the
    numbers settings/_consts.py ships."""
    by_key = {row.key: row for row in RETENTION_ROWS}
    assert by_key["motion_clips"].default == maintenance.DEFAULT_RETENTION_DAYS
    assert by_key["trash_grace"].default == TRASH_DEFAULTS["grace_days"]
    assert (
        by_key["camera_timelapses"].default
        == STORAGE_RETENTION_DEFAULTS["retention_camera_timelapses_days"]
    )
    for row in rows_for_section("weather"):
        assert row.default == WEATHER_RETENTION_DEFAULTS[row.field]


def test_each_row_is_bounded_and_its_default_is_inside_its_bounds():
    for row in RETENTION_ROWS:
        assert row.minimum <= row.default <= row.maximum, row.key
        assert row.minimum >= storage_retention.MIN_RETENTION_DAYS or row.off_at_zero, row.key


def test_only_the_camera_timelapse_row_treats_zero_as_off():
    """`off_at_zero` suppresses the "a window of zero is delete
    everything" guard for one row. Exactly one row may claim it."""
    assert [row.key for row in RETENTION_ROWS if row.off_at_zero] == ["camera_timelapses"]


def test_the_two_auto_cleanup_switches_stay_separate():
    """They gate two independent nightly sweeps and were separately
    settable before the panels merged. One master toggle would silently
    take that apart."""
    toggles = {(g.toggle_section, g.toggle_field) for g in RETENTION_GROUPS if g.toggle_section}
    assert toggles == {("storage", "auto_cleanup_enabled"), ("weather", "auto_cleanup_enabled")}


# ── acknowledge on save ────────────────────────────────────────────────


@pytest.mark.parametrize("row", RETENTION_ROWS, ids=lambda r: r.key)
def test_every_row_is_acknowledged_when_it_is_saved(row, runtime):
    """THE property. Without it the row can only ever be raised."""
    store, _ = runtime
    days = max(row.minimum, 1)
    acknowledge_payload(row.section, {row.field: days})
    assert store.get(row.runtime_key) == days, (
        f"{row.key} saved without confirming its window — nightly_window will keep "
        "deferring to the previously-enforced one, so LOWERING it does nothing"
    )


@pytest.mark.parametrize("row", RETENTION_ROWS, ids=lambda r: r.key)
def test_a_saved_row_can_actually_be_lowered_afterwards(row, runtime):
    """End to end through the guard itself: save 30, save 10, and the
    unattended sweep must be allowed to act on 10."""
    store, _ = runtime
    high = min(row.maximum, 30)
    low = max(row.minimum, 1, high - 20)
    acknowledge_payload(row.section, {row.field: high})
    acknowledge_payload(row.section, {row.field: low})
    assert (
        storage_retention.nightly_window(low, high, key=row.runtime_key) == low
    ), f"{row.key} stayed pinned at the wider window after an explicit save"


def test_a_row_absent_from_the_payload_stays_deferred(runtime):
    store, _ = runtime
    acknowledge_payload("weather", {"retention_sun_timelapses_days": 21})
    ack = {row.key for row in RETENTION_ROWS if row.runtime_key in store}
    assert ack == {"weather_sun_timelapses"}


def test_an_unparseable_value_is_ignored_instead_of_raising(runtime):
    store, _ = runtime
    acknowledge_payload("storage", {"retention_days": "vierzehn"})
    assert store == {}


def test_nie_loeschen_is_not_recorded_as_an_enforced_window(runtime):
    """0 on the camera-timelapse row is the OFF position. Recording it
    would set the guard's floor to 0 and silence it for every later
    change of that row."""
    store, _ = runtime
    acknowledge_payload("storage", {"retention_camera_timelapses_days": 0})
    assert retention_catalog.CAMERA_TL_RUNTIME_KEY not in store


def test_the_weather_entry_point_still_works_and_routes_here(runtime):
    """`acknowledge_weather_retention_from_payload` is what the weather
    sweep's own callers know. It must keep confirming the same keys."""
    from app.weather_service._retention import (
        acknowledge_weather_retention_from_payload,
        weather_retention_runtime_key,
    )

    store, _ = runtime
    acknowledge_weather_retention_from_payload({"retention_recaps_days": 200})
    assert store[weather_retention_runtime_key("recaps")] == 200


# ── resolution ─────────────────────────────────────────────────────────


def _row(key: str):
    return next(r for r in RETENTION_ROWS if r.key == key)


def test_settings_json_wins_over_config_yaml(monkeypatch):
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"storage": {"retention_days": 30}}), False
    )
    monkeypatch.setattr(app_state, "base_cfg", {"storage": {"retention_days": 14}}, False)
    assert resolve_days(_row("motion_clips")) == 30


def test_config_yaml_is_the_fallback(monkeypatch):
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), False)
    monkeypatch.setattr(app_state, "base_cfg", {"storage": {"retention_days": 21}}, False)
    assert resolve_days(_row("motion_clips")) == 21


def test_a_category_with_no_value_anywhere_falls_back_to_its_default(monkeypatch):
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), False)
    monkeypatch.setattr(app_state, "base_cfg", {}, False)
    for row in RETENTION_ROWS:
        assert resolve_days(row) == row.default, row.key


def test_a_weather_category_still_defers_to_the_legacy_blanket_value(monkeypatch):
    """A real install may carry only `weather.retention_days`. The panel
    has to show the number that install is actually running on, which is
    the same fallback the sweep uses."""
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"weather": {"retention_days": 45}}), False
    )
    monkeypatch.setattr(app_state, "base_cfg", {}, False)
    assert resolve_days(_row("weather_sightings")) == 45
    assert resolve_days(_row("weather_recaps")) == 45


def test_garbage_falls_through_to_the_next_layer_instead_of_crashing(monkeypatch):
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(data={"storage": {"retention_days": "dreissig"}}),
        False,
    )
    monkeypatch.setattr(app_state, "base_cfg", {"storage": {"retention_days": 21}}, False)
    assert resolve_days(_row("motion_clips")) == 21


# ── the rendered panel ─────────────────────────────────────────────────


def test_the_panel_renders_with_its_values_already_in_it(monkeypatch):
    """Server-side hydration is the whole point of the unification: the
    weather panel used to paint from /api/bootstrap's `data.app.weather`,
    a key `bootstrap_state()` does not return, so a saved 30 came back as
    the shipped 90 on every reload."""
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(
            data={
                "storage": {"retention_days": 33, "auto_cleanup_enabled": False},
                "weather": {"retention_recaps_days": 222, "auto_cleanup_enabled": True},
                "trash": {"grace_days": 9},
            }
        ),
        False,
    )
    monkeypatch.setattr(app_state, "base_cfg", {}, False)
    groups = panel_groups()
    values = {row["field"]: row["current"] for g in groups for row in g["rows"]}
    assert values["retention_days"] == 33
    assert values["retention_recaps_days"] == 222
    assert values["grace_days"] == 9
    by_group = {g["key"]: g for g in groups}
    assert by_group["kamera"]["toggle_on"] is False
    assert by_group["wetter"]["toggle_on"] is True


def test_every_rendered_control_knows_where_it_saves_to(monkeypatch):
    """The JS collector walks the DOM for data-section/data-field rather
    than carrying its own field map — a map is the thing that drifts."""
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), False)
    monkeypatch.setattr(app_state, "base_cfg", {}, False)
    for group in panel_groups():
        for row in group["rows"]:
            assert row["section"] and row["field"]
            assert row["input_id"] and row["range_id"] != row["input_id"]


def test_a_stored_value_outside_the_slider_range_is_clamped_for_display(monkeypatch):
    """A hand-edited 5000 must not render a slider that cannot represent
    it — and must not be silently re-saved as 5000 either, which is why
    the clamp lives in the view, not in resolve_days."""
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"trash": {"grace_days": 5000}}), False
    )
    monkeypatch.setattr(app_state, "base_cfg", {}, False)
    row = next(r for g in panel_groups() for r in g["rows"] if r["field"] == "grace_days")
    assert row["current"] == row["max"]
    assert resolve_days(_row("trash_grace")) == 5000


# ── the migration ──────────────────────────────────────────────────────


def test_the_migration_seeds_the_new_keys():
    data: dict = {}
    migrate_retention_defaults(data)
    assert data["storage"]["retention_camera_timelapses_days"] == 0
    assert data["trash"]["grace_days"] == 7


def test_the_migration_never_seeds_retention_days():
    """THE precedence trap. `resolve_retention_days` reads settings.json
    before config.yaml, so seeding this key freezes whatever config.yaml
    says today and makes every later config.yaml edit inert."""
    data: dict = {}
    migrate_retention_defaults(data)
    assert "retention_days" not in data["storage"]


def test_the_migration_never_clobbers_a_configured_value():
    data = {"storage": {"retention_camera_timelapses_days": 30}, "trash": {"grace_days": 21}}
    migrate_retention_defaults(data)
    assert data["storage"]["retention_camera_timelapses_days"] == 30
    assert data["trash"]["grace_days"] == 21


def test_the_migration_is_idempotent():
    data: dict = {}
    migrate_retention_defaults(data)
    first = {"storage": dict(data["storage"]), "trash": dict(data["trash"])}
    migrate_retention_defaults(data)
    assert data["storage"] == first["storage"]
    assert data["trash"] == first["trash"]


def test_the_migration_leaves_sibling_keys_alone():
    data = {"storage": {"corpus_quota_per_label_day": 99, "retention_days": 45}}
    migrate_retention_defaults(data)
    assert data["storage"]["corpus_quota_per_label_day"] == 99
    assert data["storage"]["retention_days"] == 45


def test_a_non_dict_section_is_replaced_rather_than_crashing_boot():
    data = {"trash": "kaputt"}
    migrate_retention_defaults(data)
    assert data["trash"] == {"grace_days": 7}


def test_the_migration_runs_at_boot():
    """A migration nobody calls is a comment."""
    import inspect

    from app.settings import store as store_module

    assert "migrate_retention_defaults(self.data)" in inspect.getsource(store_module.SettingsStore)
