"""``storage`` has to survive the trip into the effective config.

``export_effective_config`` merged app / server / telegram / mqtt /
cameras / weather / processing and simply never mentioned ``storage``.
The section survived only because ``cfg`` starts as a deepcopy of
config.yaml — so what came out was always the base layer, and every
settings-level ``storage.*`` value was dropped on the floor.

Most ``storage.*`` readers dodge it by reading ``settings.data``
directly (``maintenance._storage_setting``,
``storage_retention.keep_judged_events``, ``routes/bootstrap``).
``media_limit_default`` does not: ``/api/camera/<id>/media`` resolves its
page size through ``get_effective_config()["storage"]``, so a saved
value could not reach its only reader at all.

Pinned here: settings wins over config.yaml for ``storage`` (the same
precedence ``server`` already has, and the order
``maintenance._storage_setting`` documents), base-only keys such as
``root`` survive the merge, and the other sections' precedence is not
disturbed. Plus the export/import round-trip, which dropped ``storage``
for the same reason — it was missing from ``import_text``'s allowlist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.settings.store import SettingsStore  # noqa: E402

_BASE = {
    "app": {"name": "Squirreling · Sightings"},
    "server": {"host": "0.0.0.0", "port": 8099, "default_discovery_subnet": "192.0.2.0/24"},
    "cameras": [],
    "storage": {
        "root": "/app/storage",
        "retention_days": 14,
        "media_limit_default": 24,
    },
}


def _store(tmp_path: Path) -> SettingsStore:
    root = tmp_path / "storage"
    root.mkdir(parents=True)
    return SettingsStore(root / "settings.json", json.loads(json.dumps(_BASE)))


def test_saved_media_limit_reaches_the_effective_config(tmp_path: Path):
    store = _store(tmp_path)
    store.update_section("storage", {"media_limit_default": 96})
    eff = store.export_effective_config(json.loads(json.dumps(_BASE)))
    assert eff["storage"]["media_limit_default"] == 96


def test_base_only_storage_keys_survive_the_merge(tmp_path: Path):
    """`root` lives in config.yaml alone — a merge that replaced the
    section instead of layering it would break every path join."""
    store = _store(tmp_path)
    store.update_section("storage", {"media_limit_default": 96})
    eff = store.export_effective_config(json.loads(json.dumps(_BASE)))
    assert eff["storage"]["root"] == "/app/storage"


def test_base_storage_survives_when_settings_has_no_override(tmp_path: Path):
    store = _store(tmp_path)
    eff = store.export_effective_config(json.loads(json.dumps(_BASE)))
    assert eff["storage"]["media_limit_default"] == 24
    assert eff["storage"]["retention_days"] == 14


def test_other_sections_keep_their_precedence(tmp_path: Path):
    """The storage merge must be additive — server still layers over the
    base, and app/telegram/mqtt still come from settings alone."""
    store = _store(tmp_path)
    store.update_section("server", {"public_base_url": "https://cam.lan"})
    eff = store.export_effective_config(json.loads(json.dumps(_BASE)))
    assert eff["server"]["port"] == 8099
    assert eff["server"]["public_base_url"] == "https://cam.lan"
    assert eff["app"] == store.data["app"]


def test_storage_survives_an_export_import_round_trip(tmp_path: Path):
    store = _store(tmp_path)
    store.update_section("storage", {"media_limit_default": 96})
    text = store.export_text()

    fresh = _store(tmp_path / "second")
    fresh.import_text(text)
    assert fresh.data["storage"]["media_limit_default"] == 96
