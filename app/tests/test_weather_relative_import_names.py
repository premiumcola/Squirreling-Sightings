"""HYG · every project-relative import in the weather packages must name
something that exists.

`scripts/check_import_graph.py` proves each relative import resolves to a
MODULE. It cannot see whether the NAMES pulled out of that module are
still there, and `ruff --select F401` cannot help either: the weather
mixins all carry a file-wide `# ruff: noqa: F401` so methods can move
between them without import bookkeeping.

That blind spot cost the weather index its automatic rescan.
`_lifecycle.py`'s `_bg_rescan` did

    from ..routes.weather import api_weather_rescan

inside a `try: … except Exception as e: log.warning(...)`. `5cf94ea2`
moved the view into `routes/weather_maintenance.py`, so from that commit
on the import raised ImportError before the rescan could start — and the
marker write sits in a SECOND, separate try, so
`storage/.last_weather_rescan.json` was stamped anyway and the 24-hour
throttle suppressed every retry. Net effect: an index drift above 30 %
that never got repaired, one warning line per boot, and every weather
card falling through to the slow tolerant-resolve path.

The import was not even used — the call goes through
`current_app.test_client().post("/api/weather/rescan")`. It was a dead
name whose only remaining function was to throw.

Static: parses the source, imports the target modules, checks attributes.
Nothing is executed from the packages under test.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parent.parent / "app"
_PACKAGES = ("weather_service", "weather_episodes")


def _sources() -> list[Path]:
    out: list[Path] = []
    for pkg in _PACKAGES:
        out.extend(sorted((_PKG_ROOT / pkg).rglob("*.py")))
    assert out, "weather packages not found — did a directory move?"
    return out


def _module_name(path: Path) -> str:
    rel = path.relative_to(_PKG_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["app", *parts])


def _relative_imports():
    """(source file, resolved module, imported name) for every relative
    `from .x import y`, at module scope or nested inside a function."""
    for path in _sources():
        here = _module_name(path)
        pkg = here.rsplit(".", 1)[0] if not (path.name == "__init__.py") else here
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            base = pkg.split(".")
            # level 1 = this package, 2 = parent, ...
            for _ in range(node.level - 1):
                if base:
                    base.pop()
            target = ".".join([*base, node.module] if node.module else base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                yield path, target, alias.name


_CASES = list(_relative_imports())


def test_the_scan_found_something_to_check():
    assert len(_CASES) > 50, f"only {len(_CASES)} relative imports — scan is broken"


@pytest.mark.parametrize(
    ("src", "module", "name"),
    _CASES,
    ids=[f"{s.name}:{m.rsplit('.', 1)[-1]}.{n}" for s, m, n in _CASES],
)
def test_the_imported_name_exists(src: Path, module: str, name: str):
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - a broken module path
        pytest.fail(f"{src.name}: cannot import {module} — {exc}")
    if hasattr(mod, name):
        return
    # `from ..x import y` also legally names a SUBMODULE, which is not an
    # attribute of the package until something imports it.
    try:
        importlib.import_module(f"{module}.{name}")
        return
    except ImportError:
        pass
    assert hasattr(mod, name), (
        f"{src.name} imports '{name}' from {module}, which no longer has it. "
        f"A file-wide `noqa: F401` means ruff cannot see this, and if the "
        f"import sits in a try/except the failure is a log line, not a crash."
    )
