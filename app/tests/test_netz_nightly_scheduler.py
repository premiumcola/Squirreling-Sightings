"""The nightly threshold learner must not depend on Telegram.

Four months of `cameras[].net_auto` doing nothing, for a reason that has
no connection to what the job does: the 03:30 run was registered inside
``TelegramService.register_default_jobs``, which is reached only through
``start()`` (returns early on ``not self.enabled``) and then returns
early itself on ``not push.enabled``. Switch the bot off — or keep the
bot and switch pushes off — and the Netz stops adapting detection
thresholds, silently. The comment beside the registration asserted the
opposite: "Both are unconditional."

The learner reads a verdict corpus off disk and writes ``net_adapted``
back into settings.json. Neither end involves a bot.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import app_state
from app.thresholds import _nightly

_APP = Path(__file__).resolve().parents[1] / "app"
_TG_LIFECYCLE = (_APP / "telegram_bot" / "_lifecycle.py").read_text(encoding="utf-8")
_SERVER = (_APP / "server.py").read_text(encoding="utf-8")


def _function_body(src: str, name: str) -> list[ast.stmt]:
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node.body
    raise AssertionError(f"{name}() not found")


# ── where the job is registered ───────────────────────────────────────────


def test_the_learner_is_not_registered_on_telegrams_scheduler():
    """``register_default_jobs`` sits behind two enabled-flags. Anything
    registered there inherits both, whether it wants them or not."""
    assert "netz_learner" not in _TG_LIFECYCLE, (
        "the nightly learner is back on the Telegram scheduler — it dies "
        "there whenever the bot or its pushes are switched off"
    )


def test_the_question_release_stays_with_telegram():
    """The other Netz job genuinely IS a Telegram job — sending the
    message is all it does. Moving it here would be the mirror mistake."""
    assert "netz_question_release" in _TG_LIFECYCLE


def test_the_stale_unconditional_claim_is_gone():
    """The comment said both Netz jobs were unconditional while both were
    behind two early returns. A wrong comment is how the gap survived
    long enough to cost four months of adaptation."""
    assert "Both are\n        # unconditional" not in _TG_LIFECYCLE


def test_boot_registers_the_learner_unconditionally():
    """Not inside an ``if`` and not behind a service being enabled —
    ``rebuild_services`` runs at boot and on every settings reload, and
    the call has to be on its straight-line path."""
    body = _function_body(_SERVER, "rebuild_services")
    top_level_calls = {
        stmt.value.func.id
        for stmt in body
        if isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
    }
    assert "register_nightly_jobs" in top_level_calls, (
        "register_nightly_jobs() must be called straight from "
        "rebuild_services(), not nested in a conditional — nesting it is "
        "how the job became a hostage of Telegram's enabled flag"
    )


# ── the registration itself ───────────────────────────────────────────────


@pytest.fixture
def netz_scheduler():
    _nightly.register_nightly_jobs()
    yield _nightly._scheduler
    if _nightly._scheduler is not None:
        _nightly._scheduler.shutdown(wait=False)
        _nightly._scheduler = None


def test_the_job_lands_at_0330(netz_scheduler):
    assert _nightly.scheduled_job_ids() == [_nightly.JOB_ID]
    job = netz_scheduler.get_job(_nightly.JOB_ID)
    assert (job.next_run_time.hour, job.next_run_time.minute) == (3, 30)


def test_registering_again_does_not_double_the_firing(netz_scheduler):
    """``rebuild_services`` runs on every settings save. Without
    ``replace_existing`` keyed by job id that would stack a second 03:30
    pass on every reload — and two passes in the same night would spend
    the per-axis rails twice."""
    _nightly.register_nightly_jobs()
    _nightly.register_nightly_jobs()
    assert _nightly.scheduled_job_ids() == [_nightly.JOB_ID]


# ── the job body ──────────────────────────────────────────────────────────


def test_the_nightly_pass_runs_with_no_telegram_service(monkeypatch, tmp_path):
    """The regression, end to end: no bot, no push config, learner still
    runs. It used to be a method on TelegramService and could not even be
    reached without one."""
    calls = []

    class _Store:
        data = {"cameras": []}

    def _fake_run_pass(storage_root, settings_store, push_cfg):
        calls.append((storage_root, settings_store, push_cfg))
        return {"changed": 0}

    monkeypatch.setattr(app_state, "telegram_service", None, raising=False)
    monkeypatch.setattr(app_state, "settings", _Store(), raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(app_state, "get_effective_config", lambda: {}, raising=False)
    monkeypatch.setattr("app.thresholds._learner.run_pass", _fake_run_pass)

    _nightly.run_nightly_pass()

    assert len(calls) == 1, "the learner never ran"
    assert calls[0][0] == tmp_path
    assert calls[0][2] == {}, "an absent telegram section must not abort the pass"


def test_a_changed_pass_rebuilds_the_runtimes_once(monkeypatch, tmp_path):
    rebuilds = []

    class _Store:
        data = {"cameras": []}

    monkeypatch.setattr(app_state, "settings", _Store(), raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(app_state, "get_effective_config", lambda: {}, raising=False)
    monkeypatch.setattr(app_state, "rebuild_runtimes", lambda: rebuilds.append(1), raising=False)
    monkeypatch.setattr(
        "app.thresholds._learner.run_pass",
        lambda *_a, **_k: {"changed": 2},
        raising=True,
    )

    _nightly.run_nightly_pass()

    assert rebuilds == [1], "one rebuild at the end, not one per adapted axis"


def test_an_unbuilt_store_is_survived_not_raised(monkeypatch):
    """The scheduler starts at boot; a firing before the stores exist
    must log and return, never take the scheduler thread down."""
    monkeypatch.setattr(app_state, "settings", None, raising=False)
    monkeypatch.setattr(app_state, "storage_root", None, raising=False)
    _nightly.run_nightly_pass()
