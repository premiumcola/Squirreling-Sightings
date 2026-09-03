"""A migrating load must not burn a backup generation.

``SettingsStore.save`` keeps a 2-deep rotation:

    settings.json.bak  -> settings.json.bak2
    settings.json      -> settings.json.bak
    new content        -> settings.json

``load`` ended with two saves whenever ``migrate_schedules`` reported a
change:

    if schedule_migrated:
        self.save()
    self.save()          # unconditional persist of additive defaults

The second save rotates again immediately, against a settings.json the
first save had already rewritten. Measured on the first boot after an
upgrade, starting from settings.json = S0, .bak = S-1, .bak2 = S-2:

    single save  ->  .bak = S0,  .bak2 = S-1      two distinct generations
    double save  ->  .bak = S0', .bak2 = S0       one, plus a duplicate

S-1 is destroyed, and .bak comes out byte-identical to the live file —
a slot that can restore nothing. The operator is left with one recoverable
generation instead of two, on precisely the boot where the old state
matters most.

``settings.json`` carries the RTSP passwords and the Telegram token, so a
thinner history here is the most expensive kind in this project.

The last test pins the round-trip the operating manual demands of any
settings change: load -> modify -> save -> reload, with only the touched
field different.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

sys.modules.pop("app.settings_store", None)
import app.settings_store  # noqa: E402

importlib.reload(app.settings_store)

from app.settings_store import SettingsStore  # noqa: E402

_BASE_CONFIG = {
    "app": {"name": "Squirreling · Sightings"},
    "server": {
        "host": "0.0.0.0",
        "port": 8099,
        "default_discovery_subnet": "192.0.2.0/24",
    },
    "cameras": [],
}

# A camera in the LEGACY schedule shape — no "actions" key — so
# migrate_schedules reports a change and load takes the two-save path.
_LEGACY_CAM = {
    "id": "reolink_rlc810a_garden_183",
    "name": "Garden",
    "manufacturer": "Reolink",
    "model": "RLC-810A",
    "rtsp_url": "rtsp://user:pass@192.0.2.183/h265Preview_01_main",
    "recording_schedule_enabled": True,
    "recording_schedule_start": "08:00",
    "recording_schedule_end": "22:00",
}


def _seed(tmp_path: Path, *, with_history: bool) -> Path:
    """A settings.json that needs migrating, optionally with the two
    older generations a running install would already have."""
    storage = tmp_path / "storage"
    storage.mkdir()
    path = storage / "settings.json"
    path.write_text(
        json.dumps({"cameras": [dict(_LEGACY_CAM)], "gen": "S0"}, indent=2),
        encoding="utf-8",
    )
    if with_history:
        path.with_suffix(path.suffix + ".bak").write_text(
            json.dumps({"gen": "S-1"}, indent=2), encoding="utf-8"
        )
        path.with_suffix(path.suffix + ".bak2").write_text(
            json.dumps({"gen": "S-2"}, indent=2), encoding="utf-8"
        )
    return path


def test_a_migrating_boot_keeps_two_distinct_generations(tmp_path: Path):
    """The previous generation must survive the upgrade boot."""
    path = _seed(tmp_path, with_history=True)

    SettingsStore(path, _BASE_CONFIG)  # __init__ loads

    bak = path.with_suffix(path.suffix + ".bak")
    bak2 = path.with_suffix(path.suffix + ".bak2")
    kept = [p.read_text(encoding="utf-8") for p in (bak, bak2) if p.exists()]
    assert any('"gen": "S0"' in t for t in kept), "the pre-upgrade file was not retained"
    assert any('"gen": "S-1"' in t for t in kept), (
        "the previous generation was destroyed — load() rotated twice and "
        "pushed it out of the 2-deep history"
    )


def test_neither_backup_slot_is_a_copy_of_the_live_file(tmp_path: Path):
    """A slot holding a byte-identical copy of settings.json can restore
    nothing; it is a wasted generation."""
    path = _seed(tmp_path, with_history=True)

    SettingsStore(path, _BASE_CONFIG)

    live = path.read_text(encoding="utf-8")
    bak = path.with_suffix(path.suffix + ".bak")
    assert bak.exists(), "no .bak written on a migrating boot"
    assert bak.read_text(encoding="utf-8") != live, (
        ".bak is a byte-identical copy of settings.json — the rotation ran "
        "twice and one slot now restores nothing"
    )


def test_a_first_boot_still_preserves_the_pre_upgrade_file(tmp_path: Path):
    """With no prior history, the file as it stood before the migration
    must still land in a backup."""
    path = _seed(tmp_path, with_history=False)
    pre_upgrade = path.read_text(encoding="utf-8")

    SettingsStore(path, _BASE_CONFIG)

    kept = [
        p.read_text(encoding="utf-8")
        for p in (
            path.with_suffix(path.suffix + ".bak"),
            path.with_suffix(path.suffix + ".bak2"),
        )
        if p.exists()
    ]
    assert pre_upgrade in kept, "the pre-upgrade file is not recoverable from any backup"


def test_a_section_update_round_trips_with_only_that_field_changed(tmp_path: Path):
    """load -> modify -> save -> reload, and the modified field is the
    only difference. The rule the operating manual puts above all others
    for this file."""
    path = _seed(tmp_path, with_history=False)
    store = SettingsStore(path, _BASE_CONFIG)
    before = json.loads(path.read_text(encoding="utf-8"))

    store.update_section("ui", {"theme": "dark"})

    after = json.loads(path.read_text(encoding="utf-8"))
    reloaded = SettingsStore(path, _BASE_CONFIG)

    assert (after.get("ui") or {}).get("theme") == "dark"
    assert (reloaded.data.get("ui") or {}).get("theme") == "dark", "the change did not survive"
    for key in set(before) | set(after):
        if key == "ui":
            continue
        assert before.get(key) == after.get(key), f"section {key!r} changed on an unrelated write"
    cams = after.get("cameras") or []
    assert cams and cams[0]["rtsp_url"] == _LEGACY_CAM["rtsp_url"], "the RTSP credential was lost"
