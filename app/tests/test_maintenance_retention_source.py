"""The retention number on screen must be the one being enforced.

Two defects locked out here:

  * ``_run_daily_cleanup`` read ``retention_days`` from ``config.yaml``
    only, while the Aufbewahrung slider writes ``settings.json``. Moving
    the slider changed the manual "Jetzt bereinigen" button and nothing
    else; the nightly sweep kept using a number the UI never showed.
  * ``auto_cleanup_enabled`` was written by the UI, validated by the
    schema and echoed back by ``/api/bootstrap`` — and read by nothing.
    Turning Auto-Cleanup off did not stop the sweep.

Plus the boot race: ``cleanup_stale_timelapse_frames`` must no longer
delete ``tl_*.json``, because a second daemon thread six statements
later recreates them and the winner decided how many timelapse tiles
the Mediathek showed.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state, maintenance, migrations  # noqa: E402


@pytest.fixture
def layers(monkeypatch):
    """Both config layers, independently settable."""

    def _apply(settings_storage: dict, base_storage: dict):
        monkeypatch.setattr(
            app_state,
            "settings",
            SimpleNamespace(data={"storage": settings_storage}),
            raising=False,
        )
        monkeypatch.setattr(app_state, "base_cfg", {"storage": base_storage}, raising=False)

    return _apply


def test_settings_json_wins_over_config_yaml(layers):
    layers({"retention_days": 30}, {"retention_days": 14})
    assert maintenance.resolve_retention_days() == 30


def test_config_yaml_is_the_fallback(layers):
    layers({}, {"retention_days": 21})
    assert maintenance.resolve_retention_days() == 21


def test_explicit_override_wins_over_both(layers):
    layers({"retention_days": 30}, {"retention_days": 14})
    assert maintenance.resolve_retention_days(7) == 7


def test_garbage_falls_back_instead_of_crashing_the_sweep(layers):
    layers({"retention_days": "dreissig"}, {})
    assert maintenance.resolve_retention_days() == 14


def test_auto_cleanup_toggle_is_actually_read(layers):
    layers({"auto_cleanup_enabled": False}, {})
    assert maintenance.auto_cleanup_enabled() is False
    layers({"auto_cleanup_enabled": True}, {})
    assert maintenance.auto_cleanup_enabled() is True


def test_auto_cleanup_defaults_to_on_for_untouched_installs(layers):
    layers({}, {})
    assert maintenance.auto_cleanup_enabled() is True


def test_boot_migration_no_longer_deletes_timelapse_events():
    """The deleter raced the registrar at every boot. It is gone."""
    # Strip the docstring: it explains the removed behaviour on purpose,
    # so match against the executable body only.
    src = inspect.getsource(migrations.cleanup_stale_timelapse_frames)
    body = src.split('"""')[-1]
    assert 'glob("tl_*.json")' not in body
    assert "unlink" not in body
    assert not hasattr(migrations, "migrate_timelapse_events")
