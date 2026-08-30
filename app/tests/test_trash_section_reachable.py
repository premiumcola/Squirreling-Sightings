"""``trash.grace_days`` must be settable by something other than vi.

``trash._grace_days`` has always read ``settings.json`` → ``trash`` →
``grace_days``, and ``cleanup_expired`` has always hard-deleted against
it, so the soft-delete grace period is genuinely live. What was missing
was every way of setting it:

* ``POST /api/settings/app`` walks a hardcoded
  ``("app", "server", "ui", "storage")`` tuple, so a payload carrying
  ``trash`` was accepted with 200 and silently dropped;
* ``import_text``'s allowlist omitted it too, so a settings restore
  could not carry it either.

``SECTION_SCHEMAS["trash"]`` was already in place — the validation for a
call nobody could make. Reachable-by-API is the bar here; no new UI
control ships with this, the point is that the value can be written at
all and that the write is schema-checked like its siblings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import flask
import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state  # noqa: E402
from app.settings.store import SettingsStore  # noqa: E402

_BASE = {
    "app": {"name": "Squirreling · Sightings"},
    "server": {"host": "0.0.0.0", "port": 8099, "default_discovery_subnet": "192.0.2.0/24"},
    "cameras": [],
    "storage": {"root": "/app/storage"},
}


def _store(tmp_path: Path) -> SettingsStore:
    root = tmp_path / "storage"
    root.mkdir(parents=True)
    return SettingsStore(root / "settings.json", json.loads(json.dumps(_BASE)))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.routes.app_settings import bp

    store = _store(tmp_path)
    monkeypatch.setattr(app_state, "settings", store, raising=False)
    monkeypatch.setattr(app_state, "get_effective_config", lambda: {}, raising=False)
    monkeypatch.setattr(app_state, "rebuild_runtimes", lambda: None, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client(), store


def test_post_settings_app_persists_the_trash_section(client):
    c, store = client
    r = c.post("/api/settings/app", json={"trash": {"grace_days": 21}})
    assert r.status_code == 200
    assert store.data["trash"]["grace_days"] == 21


def test_the_persisted_value_is_what_the_sweep_reads(client, monkeypatch):
    """The write path and `trash._grace_days` must agree on the key —
    a save that lands somewhere the sweep doesn't look is the same
    unreachable setting in a different disguise."""
    from app import trash

    c, store = client
    c.post("/api/settings/app", json={"trash": {"grace_days": 21}})
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data=store.data), raising=False)
    assert trash._grace_days() == 21


def test_the_write_is_schema_coerced_like_its_siblings(client):
    c, store = client
    r = c.post("/api/settings/app", json={"trash": {"grace_days": "21"}})
    assert r.status_code == 200
    assert store.data["trash"]["grace_days"] == 21
    assert isinstance(store.data["trash"]["grace_days"], int)


def test_trash_survives_an_export_import_round_trip(tmp_path: Path):
    store = _store(tmp_path)
    store.update_section("trash", {"grace_days": 21})
    fresh = _store(tmp_path / "second")
    fresh.import_text(store.export_text())
    assert fresh.data["trash"]["grace_days"] == 21
