"""R01.6 guard — nothing may import server.py by its dotted name.

Production runs ``python -m app.server``, so that file executes as
``__main__`` and ``app.server`` is NOT registered in ``sys.modules``.
The first ``from ..server import X`` anywhere therefore re-executes
server.py top-to-bottom as a *second* module object, which reaches its
own module-level ``rebuild_runtimes()`` and constructs a duplicate
camera-runtime set plus a second ``TelegramService`` on the same bot
token — the T61 ``Conflict: terminated by other getUpdates request``.

The trap is that it fires lazily, long after boot: every offending
import sat inside a function body, so boot logs showed exactly one
poller while the duplicate appeared on the first settings save, the
first ``/api/system`` dashboard call, or the first bot ``/menu`` tap.
That is why it survived three rounds of mitigation.

This test locks the fix in place. If it fails, do not "just add the
import back" — route the call through ``app_state`` instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# `from ..server import X`, `from ...server import X`, `from .. import server`,
# `from ... import server`, `import app.server`.
_FORBIDDEN = re.compile(
    r"^\s*(?:from\s+\.{2,}server\s+import\b"
    r"|from\s+\.{2,}\s+import\s+(?:[^\n#]*[,\s])?server\b"
    r"|import\s+app\.server\b)",
    re.MULTILINE,
)


def _python_files():
    for path in sorted(APP_DIR.rglob("*.py")):
        # server.py may of course refer to itself; it is the module that
        # must never be imported by name from elsewhere.
        if path.name == "server.py" and path.parent == APP_DIR:
            continue
        yield path


@pytest.mark.parametrize("path", list(_python_files()), ids=lambda p: str(p.name))
def test_no_module_imports_server_by_name(path: Path):
    text = path.read_text(encoding="utf-8")
    hits = []
    for match in _FORBIDDEN.finditer(text):
        line_no = text.count("\n", 0, match.start()) + 1
        hits.append(f"{path}:{line_no}: {match.group(0).strip()}")
    assert not hits, (
        "server.py must never be imported by name — it re-executes the "
        "whole boot block as a second module (duplicate camera runtimes + "
        "a second Telegram poller). Route the call through app_state "
        "instead.\n" + "\n".join(hits)
    )


def test_app_state_exposes_the_boot_hooks():
    """The replacement path must actually exist, or the guard above is
    just forcing callers into a different broken shape."""
    from app import app_state

    assert hasattr(app_state, "rebuild_runtimes")
    assert hasattr(app_state, "restart_single_camera")
