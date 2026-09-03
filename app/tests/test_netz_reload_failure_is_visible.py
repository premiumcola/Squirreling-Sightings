"""A Netz commit that the pipeline never picked up has to say so.

``netz._reload_runtimes`` named its own failure mode in its docstring —
*"A threshold the pipeline does not yet read is a threshold that silently
did nothing for the rest of the day"* — and then guaranteed it::

    with contextlib.suppress(Exception):
        rebuild = getattr(app_state, "rebuild_runtimes", None)
        if callable(rebuild):
            rebuild()

``contextlib.suppress`` has no ``except`` body to log from, so a failed
rebuild left no trace anywhere. Worse, the three callers
(``PATCH /api/netz/<cam>/axes``, ``POST /api/netz/<cam>/reset``,
``POST /api/netz/archive/<eid>/restore``) each emit a confident
``log.info`` *after* the swallow — "Netz-Achsen gesetzt", "Netz
zurückgesetzt", "Netz wiederhergestellt" — so ``docker logs`` reported
success on a run where the detector kept its old thresholds. The
settings are persisted, so re-reading the panel shows the new value and
everything looks right; only detection behaviour is stale.

The same pattern one function up wraps ``net_archive.record_net_change``,
whose docstring says it *"is what makes „Netz zu diesem Zeitpunkt
wiederherstellen" möglich"* — a silent failure there disables the restore
feature for that commit.

``test_netz_api.py:53`` stubs ``rebuild_runtimes`` with a lambda that
cannot raise, so nothing in the existing suite ever exercised the failing
path. ``routes/coral/_models.py`` makes the same rebuild call and does
log the failure; that is the pattern being applied here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state  # noqa: E402
from app.routes import netz  # noqa: E402


def _boom():
    raise RuntimeError("camera runtime refused to restart")


def test_a_failed_runtime_reload_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(app_state, "rebuild_runtimes", _boom, raising=False)
    with caplog.at_level("WARNING"):
        netz._reload_runtimes()
    assert any(
        "reload" in r.message.lower() or "rebuild" in r.message.lower() for r in caplog.records
    ), f"the swallowed reload left no log line: {[r.message for r in caplog.records]}"


def test_a_missing_boot_hook_is_logged(monkeypatch, caplog):
    """`rebuild_runtimes` is published onto app_state by server.py at
    boot. If it is absent the commit is equally invisible, and the
    `callable()` guard used to turn that into a silent no-op too."""
    monkeypatch.setattr(app_state, "rebuild_runtimes", None, raising=False)
    with caplog.at_level("WARNING"):
        netz._reload_runtimes()
    assert caplog.records, "a missing rebuild hook was swallowed silently"


def test_a_successful_reload_stays_quiet(monkeypatch, caplog):
    calls: list[int] = []
    monkeypatch.setattr(app_state, "rebuild_runtimes", lambda: calls.append(1), raising=False)
    with caplog.at_level("WARNING"):
        netz._reload_runtimes()
    assert calls == [1]
    assert not caplog.records


def test_a_failed_archive_record_is_logged(monkeypatch, caplog):
    """`_archive_manual` swallows per-axis archive failures. Its own
    docstring makes that record the precondition for restoring a
    hand-set Netz, so losing it silently loses the feature."""

    def _explode(*_a, **_kw):
        raise OSError("read-only file system")

    monkeypatch.setattr(app_state, "storage_root", Path("/tmp"), raising=False)
    monkeypatch.setattr(netz.net_archive, "record_net_change", _explode)
    monkeypatch.setattr(netz, "push_for", lambda _label, _e: 0.5, raising=False)
    monkeypatch.setattr(netz, "rails", lambda: {}, raising=False)
    with caplog.at_level("WARNING"):
        netz._archive_manual(
            "cam1",
            {"name": "Garten"},
            {"bird": 50},
            {"bird": {"E": 60, "push": 0.6}},
            {"axes": [{"label": "bird"}]},
        )
    assert caplog.records, "the archive write failed and nothing said so"


@pytest.mark.parametrize("attr", ["_reload_runtimes", "_archive_manual"])
def test_the_helpers_do_not_use_bare_suppress(attr):
    """A `suppress` block has no place to log from, which is how both of
    these went silent in the first place.

    Asserted against the parsed function, not its source text: the
    docstrings here and in `netz.py` both name the construct they are
    warning about, and a substring check over the source would trip on
    the prose explaining the fix.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(netz, attr))))
    suppressors = [
        item
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        for item in node.items
        if isinstance(item.context_expr, ast.Call)
        and "suppress" in ast.unparse(item.context_expr.func)
    ]
    assert (
        not suppressors
    ), f"{attr} still swallows through a suppress block — it cannot log the failure"
