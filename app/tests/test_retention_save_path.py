"""The save path, end to end, and the nightly job that reads it.

`test_retention_catalog.py` pins the catalog helper. This file pins the
two places that have to CALL it, because a helper nobody calls is the
same unreachable setting in a different disguise — which is exactly what
`SECTION_SCHEMAS["trash"]` was before `POST /api/settings/app` learned to
walk the section.

Two hazards:

  * a saved window that is not acknowledged can be raised and never
    lowered (the guard keeps deferring to the wider one);
  * a LOWERED Papierkorb-Frist hard-deletes trashed files — the trash is
    the last copy, there is no second trash behind it — so the unattended
    sweep goes through the same widening guard the archive does, while
    every attended caller keeps the plain configured value.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import flask
import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state, maintenance, storage_retention, trash  # noqa: E402
from app.retention_catalog import RETENTION_ROWS  # noqa: E402
from app.settings.store import SettingsStore  # noqa: E402

_BASE = {
    "app": {"name": "Squirreling · Sightings"},
    "server": {"host": "0.0.0.0", "port": 8099, "default_discovery_subnet": "192.0.2.0/24"},
    "cameras": [],
    "storage": {"root": "/app/storage", "retention_days": 14},
}

#: The payload the panel's DOM-walk collector produces — every section it
#: touches, every row it renders.
_PANEL_SAVE = {
    "storage": {
        "retention_days": 21,
        "retention_camera_timelapses_days": 60,
        "auto_cleanup_enabled": True,
    },
    "weather": {
        "retention_sightings_days": 45,
        "retention_event_timelapses_days": 60,
        "retention_sun_timelapses_days": 14,
        "retention_recaps_days": 200,
        "retention_manual_events_days": 300,
        "auto_cleanup_enabled": False,
    },
    "trash": {"grace_days": 3},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.routes.app_settings import bp

    root = tmp_path / "storage"
    root.mkdir(parents=True)
    store = SettingsStore(root / "settings.json", json.loads(json.dumps(_BASE)))
    runtime: dict = {}
    store.runtime_get = lambda key, default=None: runtime.get(key, default)  # type: ignore[method-assign]
    store.runtime_set = runtime.__setitem__  # type: ignore[method-assign]
    monkeypatch.setattr(app_state, "settings", store, raising=False)
    monkeypatch.setattr(app_state, "base_cfg", json.loads(json.dumps(_BASE)), raising=False)
    monkeypatch.setattr(app_state, "get_effective_config", lambda: {}, raising=False)
    monkeypatch.setattr(app_state, "rebuild_runtimes", lambda: None, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client(), store, runtime


# ── the save persists every section ────────────────────────────────────


def test_one_save_persists_every_row_of_the_panel(client):
    c, store, _ = client
    assert c.post("/api/settings/app", json=_PANEL_SAVE).status_code == 200
    for section, fields in _PANEL_SAVE.items():
        for field, value in fields.items():
            assert store.data[section][field] == value, f"{section}.{field} did not persist"


def test_the_save_is_schema_coerced(client):
    """The number inputs POST numbers, but a hand-rolled call may not."""
    c, store, _ = client
    c.post(
        "/api/settings/app",
        json={"storage": {"retention_camera_timelapses_days": "60"}, "trash": {"grace_days": "3"}},
    )
    assert store.data["storage"]["retention_camera_timelapses_days"] == 60
    assert isinstance(store.data["trash"]["grace_days"], int)


def test_the_save_leaves_sibling_settings_alone(client):
    """`update_section` deep-merges, so the panel may send only its own
    keys — the corpus quota next door must survive."""
    c, store, _ = client
    store.update_section("storage", {"corpus_quota_per_label_day": 99})
    c.post("/api/settings/app", json=_PANEL_SAVE)
    assert store.data["storage"]["corpus_quota_per_label_day"] == 99


# ── ...and confirms every window it persisted ──────────────────────────


def test_every_saved_window_is_confirmed_against_the_guard(client):
    """THE regression. A section the save path forgets is a category
    that can never be lowered again."""
    c, _, runtime = client
    c.post("/api/settings/app", json=_PANEL_SAVE)
    for row in RETENTION_ROWS:
        expected = _PANEL_SAVE[row.section][row.field]
        assert runtime.get(row.runtime_key) == expected, (
            f"{row.key} was persisted but not acknowledged — nightly_window will keep "
            "enforcing the previous, wider window"
        )


def test_lowering_a_window_through_the_api_actually_takes_effect(client):
    c, _, runtime = client
    c.post("/api/settings/app", json={"storage": {"retention_days": 30}})
    c.post("/api/settings/app", json={"storage": {"retention_days": 7}})
    assert storage_retention.nightly_window(7, 30) == 7


def test_a_save_without_retention_keys_confirms_nothing(client):
    c, _, runtime = client
    c.post("/api/settings/app", json={"storage": {"corpus_quota_per_label_day": 10}})
    assert runtime == {}


# ── the nightly job ────────────────────────────────────────────────────


@pytest.fixture
def trash_root(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    (root / ".trash").mkdir(parents=True)
    monkeypatch.setattr(app_state, "store", SimpleNamespace(root=str(root)), raising=False)
    return root / ".trash"


def _trashed(root: Path, event_id: str, age_days: int) -> Path:
    from datetime import datetime, timedelta

    d = root / "cam" / event_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps(
            {
                "cam_id": "cam",
                "event_id": event_id,
                "trashed_at": (datetime.now() - timedelta(days=age_days)).isoformat(
                    timespec="seconds"
                ),
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    return d


def test_a_shortened_papierkorb_frist_is_deferred_until_confirmed(trash_root, monkeypatch):
    """30 → 3 without a save would hard-delete everything between the two
    numbers on the next nightly run, and the trash is the last copy."""
    entry = _trashed(trash_root, "ev-10d", 10)
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(
            data={"trash": {"grace_days": 3}},
            runtime_get=lambda key, default=None: {"trash_grace_enforced_days": 30}.get(
                key, default
            ),
            runtime_set=lambda *a: None,
        ),
        raising=False,
    )
    monkeypatch.setattr(app_state, "base_cfg", {}, raising=False)
    maintenance._sweep_trash(logging.getLogger(__name__))
    assert entry.exists(), "the unattended sweep acted on an unconfirmed narrowing"


def test_a_confirmed_papierkorb_frist_is_enforced(trash_root, monkeypatch):
    entry = _trashed(trash_root, "ev-10d", 10)
    runtime = {"trash_grace_enforced_days": 3}
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(
            data={"trash": {"grace_days": 3}},
            runtime_get=lambda key, default=None: runtime.get(key, default),
            runtime_set=runtime.__setitem__,
        ),
        raising=False,
    )
    monkeypatch.setattr(app_state, "base_cfg", {}, raising=False)
    maintenance._sweep_trash(logging.getLogger(__name__))
    assert not entry.exists()


def test_the_attended_callers_keep_the_plain_configured_value(trash_root, monkeypatch):
    """`cleanup_expired()` with no argument is what POST /api/trash/empty
    and the tests call. It must not start consulting the guard."""
    entry = _trashed(trash_root, "ev-10d", 10)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"trash": {"grace_days": 3}}), raising=False
    )
    assert trash.cleanup_expired() == 1
    assert not entry.exists()


def test_the_daily_job_runs_both_archive_sweeps(monkeypatch):
    """Camera timelapses joined the nightly job; the motion sweep must
    still be in it."""
    import inspect

    src = inspect.getsource(maintenance._run_daily_cleanup)
    assert "_sweep_motion_clips" in src
    assert "_sweep_camera_timelapses" in src
    assert "_sweep_trash" in src
