"""HYG-2 · the push package stays inside its budgets, and stays complete.

`_outbound/__init__.py` reached 922 lines with a 247-line
`send_event_alert` in it, which is why nothing could be added to the
push path any more. Two properties keep that from happening again:

  * the budgets from CLAUDE.md (500 lines per file, 80 per function),
    checked mechanically over this one package;
  * the composed mixin still answers to every method the rest of the
    app calls on it — the failure mode of a split is a method that
    quietly stops resolving, and nothing else in the suite would notice
    a lost scheduled-job body.

Pure static analysis plus attribute lookups. Nothing is instantiated, no
bot, no network.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.telegram_bot import TelegramService

PKG = Path(__file__).resolve().parent.parent / "app" / "telegram_bot" / "_outbound"

FILE_LIMIT = 500
FUNC_LIMIT = 80

# Every method the rest of the app reaches into OutboundMixin for.
# camera_runtime calls the first four, the scheduler the _job_* bodies,
# routes/telegram.py and the achievement push the sync wrapper.
PUBLIC_SURFACE = (
    "send",
    "send_alert",
    "send_alert_sync",
    "send_event_alert",
    "send_quest_completed",
    "send_timelapse_alert",
    "_job_daily_report",
    "_job_highlight",
    "_job_watchdog",
    "_best_frame_jpeg",
    "_storage_today_delta_gb",
)


def _modules() -> list[Path]:
    mods = sorted(PKG.glob("*.py"))
    assert mods, "package not found — did the path move?"
    return mods


def _functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_module_is_within_the_file_budget(path: Path):
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= FILE_LIMIT, f"{path.name}: {lines} lines — split it before adding more"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_every_function_is_within_the_function_budget(path: Path):
    over = [
        (fn.name, fn.end_lineno - fn.lineno + 1)
        for fn in _functions(path)
        if (fn.end_lineno - fn.lineno + 1) > FUNC_LIMIT
    ]
    assert not over, f"{path.name}: {over} — extract first, then add"


def test_the_split_kept_every_method_reachable():
    missing = [name for name in PUBLIC_SURFACE if not hasattr(TelegramService, name)]
    assert not missing, f"lost in the split: {missing}"


def test_the_package_root_only_composes():
    """__init__.py holds the seam list and nothing else — the moment a
    method lands back in it, the file starts growing again."""
    tree = ast.parse((PKG / "__init__.py").read_text(encoding="utf-8"))
    bodies = [
        n.name
        for cls in tree.body
        if isinstance(cls, ast.ClassDef)
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert bodies == [], f"__init__.py should compose, not implement: {bodies}"
