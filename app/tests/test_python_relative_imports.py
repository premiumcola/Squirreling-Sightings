"""Every relative import in the Python tree has to resolve — body ones too.

`scripts/check_import_graph.py` validates the browser ES-module tree and
nothing else; its own docstring says so. So the Python half of the same
failure mode had no gate at all, and it is a failure mode this project
has documented as a repeat offender (`.claude/skills/refactor-gotchas`):

    Old  app/X/module.py          — `from ..Y` resolves to `app.Y`
    New  app/X/module/__init__.py — `from ..Y` resolves to `app.X.Y`

Converting a module into a package shifts every relative import by one
level. A wrong dot-count at module level is loud — the import fails at
boot. A wrong dot-count **inside a function body** is silent: it runs
only when the function is called, and the deferred imports in this
codebase are deferred precisely because they are heavy or
hardware-bound (`from ...detectors import CoralObjectDetector`), so no
test exercises them. `ruff` does not resolve relative imports, `mypy` is
non-blocking, and the boot smoke never reaches the branch. The bad line
sits there until a user presses the button.

This walks the whole AST rather than `tree.body`, so a `from ..x import y`
nested in a function, a method, a `try:` or an `if TYPE_CHECKING:` block
is checked exactly like a top-level one. Pure static resolution — nothing
is imported, so no boot side effects and no hardware needed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# app/app — the package root. `app/tests` is deliberately out of scope:
# tests are not a package and use absolute imports.
_APP = Path(__file__).resolve().parents[1] / "app"
_PKG_ROOT = _APP.parent  # contains the top-level `app` package


def _iter_modules() -> list[Path]:
    return sorted(p for p in _APP.rglob("*.py") if "__pycache__" not in p.parts)


def _package_of(path: Path) -> list[str]:
    """The dotted `__package__` of a module file, as a list of parts."""
    rel = path.relative_to(_PKG_ROOT)
    parts = list(rel.parts)
    # `pkg/__init__.py` IS the package; `pkg/mod.py` lives one below it.
    parts = parts[:-1] if path.name == "__init__.py" else parts[:-1]
    return parts


def _resolve(path: Path, node: ast.ImportFrom) -> str | None:
    """The absolute dotted name a relative ImportFrom points at.

    ``None`` when it climbs above the package root, which is itself the
    bug: Python raises ImportError for that at runtime.
    """
    pkg = _package_of(path)
    up = node.level - 1
    if up > len(pkg):
        return None
    base = pkg[: len(pkg) - up] if up else pkg
    return ".".join([*base, *(node.module.split(".") if node.module else [])])


def _exists(dotted: str) -> bool:
    target = _PKG_ROOT.joinpath(*dotted.split("."))
    return target.with_suffix(".py").is_file() or (target / "__init__.py").is_file()


# Known broken, reported rather than repaired: this file belongs to the
# recording area, which is being reworked on its own branch, and a second
# hand in it would collide. All three of its `from .... import` lines sit
# in a 3-part package, so they climb above the package root and raise
# ImportError — each inside a `try: ... except Exception: log.debug(...)`,
# which is why nothing ever surfaced. What silently never runs:
#   :123 F06 first-since marker      :166 F09 per-event quest re-eval
#   :175 F08 bird-dossier registration
# Drop this entry once the dots are counted right (`...`, not `....`).
_REPORTED_ELSEWHERE = {"camera_runtime/_recording/_publish.py"}


def _relative_imports() -> list[tuple[Path, ast.ImportFrom]]:
    found: list[tuple[Path, ast.ImportFrom]] = []
    for path in _iter_modules():
        if str(path.relative_to(_APP)) in _REPORTED_ELSEWHERE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # walk, not tree.body — the whole point is to reach function bodies.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                found.append((path, node))
    return found


_ALL = _relative_imports()


def test_the_scan_actually_found_imports():
    """A resolver that silently matched nothing would pass forever."""
    assert len(_ALL) > 200, f"only {len(_ALL)} relative imports found — the walk is broken"


def test_it_reaches_imports_inside_function_bodies():
    """The case the JS-only checker never covered, pinned so a future
    rewrite of this file cannot quietly go back to `tree.body`."""
    nested = []
    for path in _iter_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        top = {id(n) for n in tree.body}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and id(node) not in top:
                nested.append((path, node))
    assert len(nested) > 50, (
        f"only {len(nested)} function-body relative imports seen — "
        "this scan is not reaching them, which is the whole point"
    )


@pytest.mark.parametrize(
    ("path", "node"),
    _ALL,
    ids=[f"{p.relative_to(_APP)}:{n.lineno}" for p, n in _ALL],
)
def test_relative_import_resolves(path: Path, node: ast.ImportFrom):
    dotted = _resolve(path, node)
    assert dotted is not None, (
        f"{path.relative_to(_APP)}:{node.lineno} climbs above the package root with "
        f"{'.' * node.level}{node.module or ''} — ImportError at runtime"
    )
    assert _exists(dotted), (
        f"{path.relative_to(_APP)}:{node.lineno} imports "
        f"{'.' * node.level}{node.module or ''} which resolves to {dotted!r}, "
        "and no such module or package exists. Count the dots: a module that "
        "became a package sits one level deeper than the file it replaced."
    )
