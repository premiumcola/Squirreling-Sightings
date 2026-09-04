"""The home page has to render.

`index.html` is the only route the operator ever types, and until now
nothing rendered it in a test — every partial, every Jinja global and
every `{% include %}` was verified only by someone loading the dashboard.
A template global that does not exist is a 500 on the front door, and it
would be found by the operator, not by CI.

The immediate reason for writing it: `shell_v()` was added to the head so
a tab can tell whether it is running the server's current build. A typo
there would have taken the whole app down while claiming to fix a
delivery problem.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.lifecycle import _file_hash, shell_hash  # noqa: E402

_TPL = Path(__file__).resolve().parents[1] / "web" / "templates"


@pytest.fixture
def rendered() -> str:
    """index.html rendered with the REAL Jinja globals server.py installs.

    Deliberately the real functions, not stubs: a global that is
    registered under a different name than the template calls is exactly
    the failure this test exists to catch, and a stub would paper over
    it.
    """
    env = Environment(loader=FileSystemLoader(str(_TPL)), autoescape=True)
    env.globals["static_v"] = _file_hash
    env.globals["shell_v"] = shell_hash
    return env.get_template("index.html").render()


def test_the_index_page_renders_at_all(rendered):
    assert "<body>" in rendered
    assert len(rendered) > 5000, "the page rendered but came out suspiciously thin"


def test_every_include_resolved(rendered):
    """A missing partial raises, but an EMPTY one renders silently."""
    for marker in ("shell", "main"):
        assert f'class="{marker}"' in rendered, f"the {marker} container is missing"


def test_the_build_is_stamped_into_the_document(rendered):
    """core/version-guard.js reads this to decide whether the tab is
    older than the server. Without it every tab reports itself stale."""
    m = re.search(r'<meta name="shell-version" content="([^"]*)"', rendered)
    assert m, "no shell-version stamp in the head"
    assert m.group(1).strip(), "the stamp rendered empty — the guard would cry wolf on every load"


def test_the_stamp_matches_the_endpoint(rendered):
    """The value in the document and the value /version.json serves must
    be the same function, or the guard compares two unrelated numbers and
    reports a permanent mismatch."""
    m = re.search(r'<meta name="shell-version" content="([^"]*)"', rendered)
    assert m.group(1) == shell_hash()


def test_the_entry_points_are_cache_busted(rendered):
    for asset in ("app.css", "js/main.js"):
        assert re.search(
            rf'{re.escape(asset)}\?v=[0-9a-f]+', rendered
        ), f"{asset} is served without a version query"
