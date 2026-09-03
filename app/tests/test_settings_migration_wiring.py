"""Every migration this package defines must actually run on a load.

There is no registry. Two docstrings used to claim `store.load()`
iterates "the ordered MIGRATIONS list at the bottom" of
``settings/migrations`` — no such list has ever existed. The real
sequence is a hand-written block of explicit calls in
``SettingsStore.load``, so adding a function to the migrations package
is NOT enough to make it run, and nothing failed if you forgot to wire
it up.

That is the "migration that never runs" failure mode, and a settings
migration that silently does not run is invisible until an operator hits
the missing key months later.

This test closes it behaviourally: wrap every exported ``migrate_*``
wherever it is bound, drive one real load, and require each to have been
called. It is deliberately not a source-text scan — the wiring has to be
observed happening, and the assertion has to survive the file moving.

``migrate_threshold_keys`` is included on purpose: it is chained from
``migrate_camera_defaults`` rather than listed in ``store.load()``, so it
is bound only inside ``migrations._camera``. Wrapping every holder of the
name is what lets one rule cover both wiring styles.
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

import app.settings.migrations as migrations_pkg  # noqa: E402
import app.settings.store as store_mod  # noqa: E402
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

_LEGACY_CAM = {
    "id": "reolink_rlc810a_garden_183",
    "name": "Garden",
    "manufacturer": "Reolink",
    "model": "RLC-810A",
    "rtsp_url": "rtsp://user:pass@192.0.2.183/h265Preview_01_main",
    "recording_schedule_enabled": True,
}


def _migration_names() -> list[str]:
    return sorted(n for n in dir(migrations_pkg) if n.startswith("migrate_"))


def _holders():
    """Every module that could hold a reference to a migration."""
    mods = [migrations_pkg, store_mod]
    pkg_dir = Path(migrations_pkg.__file__).parent
    for f in sorted(pkg_dir.glob("_*.py")):
        mods.append(importlib.import_module(f"app.settings.migrations.{f.stem}"))
    return mods


def test_the_package_still_exports_migrations():
    """Guards the premise — an empty list would make the next test vacuous."""
    names = _migration_names()
    assert len(names) >= 10, f"only {len(names)} migrations found — did the export list break?"


def test_every_declared_migration_runs_on_a_load(tmp_path, monkeypatch):
    names = _migration_names()
    called: set[str] = set()
    holders = _holders()

    for name in names:
        original = getattr(migrations_pkg, name)

        def _wrapped(*args, _n=name, _f=original, **kwargs):
            called.add(_n)
            return _f(*args, **kwargs)

        for mod in holders:
            if getattr(mod, name, None) is not None:
                monkeypatch.setattr(mod, name, _wrapped, raising=False)

    storage = tmp_path / "storage"
    storage.mkdir()
    path = storage / "settings.json"
    path.write_text(json.dumps({"cameras": [dict(_LEGACY_CAM)]}, indent=2), encoding="utf-8")

    SettingsStore(path, _BASE_CONFIG)  # __init__ loads

    never_ran = sorted(set(names) - called)
    assert not never_ran, (
        f"declared but never called during a load: {never_ran} — "
        "wire them into SettingsStore.load() (or chain them from a migration "
        "that is already wired), or delete them"
    )
