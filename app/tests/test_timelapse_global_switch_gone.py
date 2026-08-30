"""``timelapse_settings.global_enabled`` was a master switch wired to
nothing at either end, and it is now gone rather than wired.

The key was seeded by ``build_defaults`` and by
``migrate_timelapse_settings``, echoed by ``/api/timelapse/status``, and
writable through ``POST /api/settings/timelapse``. Nothing read it: the
capture threads start from ``_timelapse_thread_supervisor``, which
consults only the per-camera ``timelapse.profiles.<name>.enabled``. No
frontend module ever called the save route either, so the switch had no
UI at the near end and no gate at the far end.

Wiring it was the tempting fix — the supervisor is an obvious single
gate. It is also the wrong one: the seeded default is ``False``, so
every existing settings.json carries ``global_enabled: false``, and
honouring it would silently stop timelapse capture on every install
that has been happily recording for months. A switch whose only honest
wiring is a fleet-wide outage is not a switch, so the key is removed
and the per-profile toggles stay the single source of truth.

Pinned: the key is gone from every layer at once, not half of them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import flask

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.settings.defaults import build_defaults  # noqa: E402


def test_fresh_install_seeds_no_timelapse_settings_section():
    assert "timelapse_settings" not in build_defaults({"cameras": []})


def test_no_migration_backfills_the_section():
    import app.settings.migrations as migrations

    assert not hasattr(migrations, "migrate_timelapse_settings")


def test_the_save_route_is_gone():
    from app.routes import register_blueprints

    app = flask.Flask(__name__)
    register_blueprints(app)
    assert "/api/settings/timelapse" not in {str(r) for r in app.url_map.iter_rules()}


def test_status_payload_no_longer_advertises_a_global_switch(monkeypatch):
    """The status endpoint reported `global_enabled` to a frontend that
    never read it — an inert field is still a promise."""
    from types import SimpleNamespace

    from app import app_state
    from app.routes.timelapse import bp

    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={"cameras": []}), raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    r = app.test_client().get("/api/timelapse/status")
    assert r.status_code == 200
    assert "global_enabled" not in r.get_json()


def test_a_booted_store_carries_no_timelapse_settings(tmp_path):
    """End to end: defaults plus the whole migration sequence, on a
    fresh install. The section must not reappear from either half."""
    from app.settings.store import SettingsStore

    root = tmp_path / "storage"
    root.mkdir(parents=True)
    store = SettingsStore(
        root / "settings.json",
        {
            "app": {"name": "Squirreling · Sightings"},
            "server": {"default_discovery_subnet": "192.0.2.0/24"},
            "cameras": [],
        },
    )
    assert "timelapse_settings" not in store.data


def test_a_legacy_settings_file_does_not_resurrect_the_switch(tmp_path):
    """A settings.json that predates the removal still carries the key.
    It must survive as inert data (additive-merge rule) without any
    layer re-seeding or re-reading it."""
    from app.settings.store import SettingsStore

    root = tmp_path / "storage"
    root.mkdir(parents=True)
    (root / "settings.json").write_text(
        json.dumps({"cameras": [], "timelapse_settings": {"global_enabled": False}}),
        encoding="utf-8",
    )
    store = SettingsStore(
        root / "settings.json",
        {"app": {}, "server": {"default_discovery_subnet": "192.0.2.0/24"}, "cameras": []},
    )
    assert store.data["timelapse_settings"] == {"global_enabled": False}
    assert "timelapse_settings" not in build_defaults({"cameras": []})
