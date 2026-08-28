"""THR-1 · the resolved threshold ladder + the additive key migration.

Two halves:

* ``resolve_effective`` — one camera, one label, all four gates, and
  where each value came from. The precedence camera > adapted > global
  > default is pinned here; an automatic calibration must never be able
  to overwrite what the operator typed.
* the settings migration — the new keys land on EVERY camera and no
  other field in settings.json moves (round-trip diff, as CLAUDE.md
  demands for anything touching settings).

IPs in fixtures are RFC 5737 documentation addresses (192.0.2.x).
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.schema import CAMERA_SCHEMA  # noqa: E402
from app.settings._consts import (  # noqa: E402
    CAMERA_THRESHOLD_KEY_DEFAULTS,
    CORPUS_QUOTA_PER_LABEL_DAY_DEFAULT,
    TELEGRAM_PUSH_DEFAULTS,
)
from app.settings.defaults import default_camera  # noqa: E402
from app.settings.migrations import migrate_threshold_keys  # noqa: E402
from app.thresholds import (  # noqa: E402
    SOURCE_ADAPTED,
    SOURCE_CAMERA,
    SOURCE_DEFAULT,
    SOURCE_GLOBAL,
    resolve_effective,
)

# The shipped global push config, as it sits in settings.json today.
SHIPPED_PUSH = deepcopy(TELEGRAM_PUSH_DEFAULTS)


@pytest.fixture
def plain_cam() -> dict:
    """A camera as build_defaults creates it — no manual overrides."""
    return default_camera({"id": "reolink_cx810_werkstatt_183", "name": "Werkstatt"})


# ── push threshold · the layer that did not exist before THR-1 ──────────────


def test_push_threshold_camera_override_wins(plain_cam):
    plain_cam["push_thresholds"] = {"person": 0.5}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.push == pytest.approx(0.5)
    assert eff.source["push"] == SOURCE_CAMERA


def test_push_threshold_without_camera_entry_uses_global(plain_cam):
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.push == pytest.approx(0.85)
    assert eff.source["push"] == SOURCE_GLOBAL


def test_push_threshold_other_labels_unaffected_by_one_override(plain_cam):
    """A per-camera person value must not leak into squirrel."""
    plain_cam["push_thresholds"] = {"person": 0.5}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "squirrel")
    assert eff.push == pytest.approx(0.80)
    assert eff.source["push"] == SOURCE_GLOBAL


def test_push_threshold_falls_back_to_shipped_default(plain_cam):
    """Empty global push config → the shipped constant, marked as such."""
    eff = resolve_effective(plain_cam, {}, "person")
    assert eff.push == pytest.approx(0.85)
    assert eff.source["push"] == SOURCE_DEFAULT


def test_push_threshold_zero_is_a_real_value(plain_cam):
    """0.0 means "push everything", not "unset" — motion ships that way."""
    plain_cam["push_thresholds"] = {"bird": 0.0}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "bird")
    assert eff.push == pytest.approx(0.0)
    assert eff.source["push"] == SOURCE_CAMERA


def test_push_enabled_read_from_global(plain_cam):
    assert resolve_effective(plain_cam, SHIPPED_PUSH, "person").push_enabled is True
    cat = resolve_effective(plain_cam, SHIPPED_PUSH, "cat")
    assert cat.push_enabled is False
    assert cat.source["push_enabled"] == SOURCE_GLOBAL


# ── precedence · manual beats adapted beats global ─────────────────────────


def test_adapted_beats_global_but_never_the_camera(plain_cam):
    adapted = {"push": 0.70}
    # No manual value → the adaptation applies, above the global 0.85.
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person", adapted=adapted)
    assert eff.push == pytest.approx(0.70)
    assert eff.source["push"] == SOURCE_ADAPTED
    # Operator typed 0.5 → the adaptation must not overwrite it.
    plain_cam["push_thresholds"] = {"person": 0.5}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person", adapted=adapted)
    assert eff.push == pytest.approx(0.5)
    assert eff.source["push"] == SOURCE_CAMERA


def test_adapted_spawn_never_overwrites_label_thresholds(plain_cam):
    plain_cam["label_thresholds"] = {"person": 0.60}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person", adapted={"spawn": 0.30})
    assert eff.spawn == pytest.approx(0.60)
    assert eff.source["spawn"] == SOURCE_CAMERA


def test_the_camera_wide_tracker_knob_does_not_outrank_the_learner(plain_cam):
    """One „Vorsichtig" click on the Erkennung tab posts
    ``track_spawn_min_score: 0.55`` for the WHOLE camera. Ranked above
    ``adapted`` it silently reverted every axis the net had learned —
    every label without its own ``label_thresholds`` entry — with no
    control anywhere showing it and no line in any log.

    A per-class decision still wins. A camera-wide default does not.
    """
    plain_cam.pop("label_thresholds", None)
    plain_cam["track_spawn_min_score"] = 0.55
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "squirrel", adapted={"spawn": 0.62})
    assert eff.spawn == pytest.approx(0.62)
    assert eff.source["spawn"] == SOURCE_ADAPTED
    # With nothing learned yet the knob is still the camera's answer.
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "squirrel")
    assert eff.spawn == pytest.approx(0.55)
    assert eff.source["spawn"] == SOURCE_CAMERA
    # And a per-class value the operator set still beats both.
    plain_cam["label_thresholds"] = {"squirrel": 0.70}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "squirrel", adapted={"spawn": 0.62})
    assert eff.spawn == pytest.approx(0.70)
    assert eff.source["spawn"] == SOURCE_CAMERA


# ── the other three gates ──────────────────────────────────────────────────


def test_spawn_defaults_to_shipped_label_threshold(plain_cam):
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.spawn == pytest.approx(0.45)
    assert eff.source["spawn"] == SOURCE_CAMERA  # default_camera stores it


def test_spawn_for_unknown_label_uses_tracker_default():
    eff = resolve_effective({}, SHIPPED_PUSH, "aardvark")
    assert eff.spawn == pytest.approx(0.50)
    assert eff.source["spawn"] == SOURCE_DEFAULT


def test_detect_floor_default_and_camera_override(plain_cam):
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.detect == pytest.approx(0.20)
    assert eff.source["detect"] == SOURCE_DEFAULT
    plain_cam["track_continue_min_score"] = 0.30
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.detect == pytest.approx(0.30)
    assert eff.source["detect"] == SOURCE_CAMERA


def test_detect_never_exceeds_spawn(plain_cam):
    """A floor above the spawn gate would make the gate unreachable."""
    plain_cam["label_thresholds"] = {"person": 0.40}
    plain_cam["track_continue_min_score"] = 0.90
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.detect == pytest.approx(0.40)


def test_confirmation_window_camera_and_default(plain_cam):
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "squirrel")
    assert (eff.confirm_n, eff.confirm_seconds) == (2, pytest.approx(3.0))
    plain_cam["confirmation_window"] = {"squirrel": {"n": 4, "seconds": 6.0}}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "squirrel")
    assert (eff.confirm_n, eff.confirm_seconds) == (4, pytest.approx(6.0))
    assert eff.source["confirm_n"] == SOURCE_CAMERA


# ── the dead zone the whole package exists for ─────────────────────────────


def test_shipped_person_config_has_a_dead_zone(plain_cam):
    """Confirms at 0.45, pushes at 0.85 → everything in between is
    recorded and never sent. Derivable from one call, which is the
    point of the resolver."""
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.dead_zone is True
    assert eff.spawn < eff.push


def test_per_camera_push_threshold_closes_the_dead_zone(plain_cam):
    plain_cam["push_thresholds"] = {"person": 0.45}
    eff = resolve_effective(plain_cam, SHIPPED_PUSH, "person")
    assert eff.dead_zone is False


def test_none_inputs_do_not_raise():
    eff = resolve_effective(None, None, "person")
    assert eff.label == "person"
    assert eff.push == pytest.approx(0.85)


# ── the new keys · defaults, schema, migration ─────────────────────────────


def test_default_camera_carries_the_new_keys(plain_cam):
    assert plain_cam["push_thresholds"] == {}
    assert plain_cam["hybrid_mode"] == "off"
    assert plain_cam["label_veto"] == {}


def test_default_camera_dicts_are_not_shared():
    a = default_camera({"id": "a", "name": "A"})
    b = default_camera({"id": "b", "name": "B"})
    a["push_thresholds"]["person"] = 0.5
    assert b["push_thresholds"] == {}


def test_new_keys_are_in_the_camera_schema():
    for key in CAMERA_THRESHOLD_KEY_DEFAULTS:
        assert key in CAMERA_SCHEMA, f"{key} missing from CAMERA_SCHEMA"


def test_migration_backfills_every_camera_and_the_storage_quota():
    data = {
        "cameras": [
            {"id": "cam_a", "name": "A"},
            {"id": "cam_b", "name": "B", "push_thresholds": {"person": 0.5}},
        ]
    }
    migrate_threshold_keys(data)
    assert data["cameras"][0]["push_thresholds"] == {}
    assert data["cameras"][0]["hybrid_mode"] == "off"
    assert data["cameras"][0]["label_veto"] == {}
    # An operator value survives the backfill untouched.
    assert data["cameras"][1]["push_thresholds"] == {"person": 0.5}
    assert data["storage"]["corpus_quota_per_label_day"] == CORPUS_QUOTA_PER_LABEL_DAY_DEFAULT


def test_migration_is_idempotent():
    data = {"cameras": [{"id": "cam_a", "name": "A"}]}
    migrate_threshold_keys(data)
    once = deepcopy(data)
    migrate_threshold_keys(data)
    assert data == once


def test_migration_keeps_an_existing_storage_section():
    data = {"cameras": [], "storage": {"retention_days": 30}}
    migrate_threshold_keys(data)
    assert data["storage"]["retention_days"] == 30
    assert "corpus_quota_per_label_day" in data["storage"]


def _make_store(tmp_path: Path):
    """Real SettingsStore on a tmp tree, seeded with one camera."""
    sys.modules.pop("app.settings_store", None)
    from app.settings_store import SettingsStore

    storage = tmp_path / "storage"
    storage.mkdir(exist_ok=True)
    base_config = {
        "app": {"name": "Squirreling · Sightings"},
        "storage": {"root": str(storage), "retention_days": 14},
        "cameras": [
            {
                "id": "reolink_cx810_werkstatt_183",
                "name": "Werkstatt",
                "rtsp_url": "rtsp://192.0.2.183/h265Preview_01_main",
            }
        ],
        "telegram": {},
        "mqtt": {},
        "processing": {},
    }
    return SettingsStore(storage / "settings.json", base_config)


def test_roundtrip_adds_only_the_new_keys(tmp_path: Path):
    """A pre-THR-1 settings.json gets exactly the new keys back and
    every other field stays bit-identical."""
    _make_store(tmp_path)
    # Second load on purpose: migrate_telegram_push_defaults backfills
    # night_alert lat/lon from server.location, which a LATER migration
    # in the same pass creates — so those two fields only settle on the
    # second boot. Pre-existing and unrelated to THR-1; snapshotting the
    # settled file keeps this test about the keys it actually owns.
    store = _make_store(tmp_path)
    path = store.path
    full = json.loads(path.read_text(encoding="utf-8"))

    # Simulate the file as it looks on the live instance today: the
    # THR-1 keys simply aren't there yet.
    legacy = deepcopy(full)
    for cam in legacy["cameras"]:
        for key in CAMERA_THRESHOLD_KEY_DEFAULTS:
            cam.pop(key, None)
    legacy.pop("storage", None)
    path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")

    reloaded = json.loads(_make_store(tmp_path).path.read_text(encoding="utf-8"))
    assert reloaded == full, "migration changed a field outside its own keys"
