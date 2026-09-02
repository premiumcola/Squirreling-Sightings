"""A ledger that cannot be read must not be overwritten.

``_load_achievements`` could not tell "no file yet" from "file is there
but does not parse" — both returned ``{}``, and the read failure was
swallowed without even a log line::

    try:
        p = _ach_path()
        if p.exists():
            return _json_mod.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

``/api/achievements/unlock`` then took that ``{}`` for a fresh install,
added the one species being unlocked, and wrote it back — replacing the
whole file. Species, ``quests`` and ``quests_archive`` (both read back by
``GET /api/achievements``) went with it. The response was ``200`` with
``ok: True``, so the UI painted the unlock it had just destroyed the
ledger to record.

``quests.reevaluate_and_save`` calls the same pair on the hourly timer,
so the same truncation ran unattended. Its caller
(``maintenance._run_hourly_quest_eval``) already wraps the call in
``except Exception`` and re-arms the timer, so a raise there is caught,
logged, and — the point — writes nothing.

The write half was the same shape: ``_save_achievements`` swallowed the
failure and returned ``None``, and the route returned ``ok: True``
regardless, so a full disk looked exactly like a successful unlock.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import flask
import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state  # noqa: E402
from app.routes import sichtungen  # noqa: E402

_INTACT = {
    "amsel": {"date": "2026-01-01T10:00:00", "species": "Amsel", "count": 4},
    "quests": {"q1": {"state": "active"}},
    "quests_archive": {"q0": {"state": "done"}},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_state, "storage_root", tmp_path, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(sichtungen.bp)
    return app.test_client()


def _ledger(tmp_path: Path) -> Path:
    return tmp_path / "achievements.json"


def test_a_corrupt_ledger_is_not_replaced_by_an_unlock(client, tmp_path):
    """The whole point. A half-written file is still the user's data."""
    _ledger(tmp_path).write_text('{"amsel": {"count": 4}, "quest', encoding="utf-8")
    before = _ledger(tmp_path).read_text(encoding="utf-8")

    r = client.post("/api/achievements/unlock", json={"id": "rotkehlchen"})

    assert _ledger(tmp_path).read_text(encoding="utf-8") == before
    assert r.get_json()["ok"] is False


def test_an_unreadable_ledger_does_not_report_a_successful_unlock(client, tmp_path):
    _ledger(tmp_path).write_text("not json at all", encoding="utf-8")
    r = client.post("/api/achievements/unlock", json={"id": "rotkehlchen"})
    assert r.status_code >= 400
    assert r.get_json()["ok"] is False


def test_a_failed_write_is_not_reported_as_ok(client, tmp_path, monkeypatch):
    _ledger(tmp_path).write_text(json.dumps(_INTACT), encoding="utf-8")

    def _boom(*_a, **_kw):
        raise OSError("No space left on device")

    monkeypatch.setattr(sichtungen, "_atomic_write_text", _boom)
    r = client.post("/api/achievements/unlock", json={"id": "rotkehlchen"})
    assert r.get_json()["ok"] is False
    assert r.status_code >= 400


def test_a_fresh_install_still_unlocks(client, tmp_path):
    """No file at all is a legitimate empty ledger, not a read failure."""
    r = client.post("/api/achievements/unlock", json={"id": "amsel"})
    body = r.get_json()
    assert body["ok"] is True
    assert body["already_had"] is False
    assert json.loads(_ledger(tmp_path).read_text(encoding="utf-8"))["amsel"]["count"] == 1


def test_an_intact_ledger_keeps_its_siblings_through_an_unlock(client, tmp_path):
    _ledger(tmp_path).write_text(json.dumps(_INTACT), encoding="utf-8")
    r = client.post("/api/achievements/unlock", json={"id": "rotkehlchen"})
    assert r.get_json()["ok"] is True
    stored = json.loads(_ledger(tmp_path).read_text(encoding="utf-8"))
    assert stored["amsel"]["count"] == 4
    assert stored["quests"] == _INTACT["quests"]
    assert stored["quests_archive"] == _INTACT["quests_archive"]
    assert stored["rotkehlchen"]["count"] == 1


def test_the_read_failure_is_logged(client, tmp_path, caplog):
    """It was silent, which is why nobody noticed the ledger resetting."""
    _ledger(tmp_path).write_text("{{{", encoding="utf-8")
    with caplog.at_level("WARNING"):
        client.get("/api/achievements")
    assert any("achievements" in rec.message.lower() for rec in caplog.records)


def test_the_reader_still_degrades_to_an_empty_board(client, tmp_path):
    """GET is a display path — it must not 500 the Sichtungen page just
    because the file is damaged. It reports empty and logs; only the
    write paths refuse."""
    _ledger(tmp_path).write_text("{{{", encoding="utf-8")
    r = client.get("/api/achievements")
    assert r.status_code == 200
    assert r.get_json()["achievements"] == {}
