"""Python-3.9 floor guard — one tree, two interpreters.

The main service image is ``python:3.11-slim``. The Coral image
(``app/docker/Dockerfile.coral``) is Python **3.9**, because pycoral 2.0
publishes wheels for 3.7–3.9 only, and pycoral 2.0 + tflite-runtime 2.5.0
+ libedgetpu1-std is the one combination Google actually ships and tests
against for the EdgeTPU. Everything newer reproduces the failure that
motivated this guard: ``load_delegate`` succeeds, then *every* compiled
model dies with "Node N (EdgeTpuDelegateForCustomOp) failed to invoke /
Encountered an unresolved custom op", and the detector silently drops to
the CPU fallback at roughly 10x the latency.

So the same source tree must import on 3.9. This test is the enforcement:
the suite itself runs on 3.11 and would happily accept ``datetime.UTC``
forever, because on 3.11 it simply works.

Two independent checks, because they fail on different things:

* :func:`test_file_parses_under_the_39_grammar` — ``ast.parse`` with
  ``feature_version=(3, 9)`` restricts CPython's PEG parser to the 3.9
  grammar. This catches *syntax* (``match``/``case``, ``except*``) and
  nothing else; the parser does not know what ``datetime.UTC`` is.
* :func:`test_file_uses_no_post_39_stdlib` — an AST walk for names that
  parse fine on 3.9 but raise ``ImportError`` / ``AttributeError`` there.
  This is the half that catches the regressions people actually type.

If this test fails, do **not** widen the allow-list. Rewrite the call in
the form that works on both — the 3.9-safe spelling is almost always
just as readable on 3.11:

    datetime.UTC              ->  timezone.utc        (from datetime import timezone)
    zip(a, b, strict=False)   ->  zip(a, b)           (False is the pre-3.10 default)
    n.bit_count()             ->  bin(n).count("1")   (n >= 0)
    isinstance(x, int | str)  ->  isinstance(x, (int, str))

Note the last one especially: ``from __future__ import annotations``
makes PEP-604 unions safe in *annotations*, which is why they are allowed
there and why this test does not flag them. It does **not** cover
``isinstance``/``issubclass``, whose second argument is evaluated eagerly
at runtime. ``pyproject.toml`` pins ``target-version = "py39"`` so ruff's
UP038 stops suggesting that rewrite at ~27 sites; this test is the
backstop for when someone runs ``ruff --fix --unsafe-fixes`` with an
overridden target anyway.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [APP_ROOT / "app", APP_ROOT / "scripts", APP_ROOT / "tests"]

# Attribute / imported-name -> the version that introduced it. Matched on
# the bare identifier, so it fires on `from datetime import UTC`,
# `datetime.UTC` and `x.bit_count()` alike. Deliberately name-based: an
# import-graph-accurate check would need to resolve every alias, and a
# false positive here costs one rename while a false negative costs a
# container that boots into CPU fallback.
POST_39_NAMES = {
    # 3.10
    "aclosing": "3.10 contextlib.aclosing",
    "aiter": "3.10 builtin aiter()",
    "anext": "3.10 builtin anext()",
    "bit_count": "3.10 int.bit_count() — use bin(n).count('1')",
    "Concatenate": "3.10 typing.Concatenate",
    "pairwise": "3.10 itertools.pairwise",
    "ParamSpec": "3.10 typing.ParamSpec",
    "TypeAlias": "3.10 typing.TypeAlias",
    "TypeGuard": "3.10 typing.TypeGuard",
    # 3.11
    "add_note": "3.11 BaseException.add_note",
    "assert_never": "3.11 typing.assert_never",
    "assert_type": "3.11 typing.assert_type",
    "BaseExceptionGroup": "3.11 BaseExceptionGroup",
    "dataclass_transform": "3.11 typing.dataclass_transform",
    "ExceptionGroup": "3.11 ExceptionGroup",
    "file_digest": "3.11 hashlib.file_digest",
    "getLevelNamesMapping": "3.11 logging.getLevelNamesMapping",
    "LiteralString": "3.11 typing.LiteralString",
    "Never": "3.11 typing.Never",
    "NotRequired": "3.11 typing.NotRequired",
    "Required": "3.11 typing.Required",
    "Self": "3.11 typing.Self",
    "StrEnum": "3.11 enum.StrEnum",
    "TaskGroup": "3.11 asyncio.TaskGroup",
    "TypeVarTuple": "3.11 typing.TypeVarTuple",
    "Unpack": "3.11 typing.Unpack",
    "UTC": "3.11 datetime.UTC — use timezone.utc",
}

# Top-level modules that do not exist on 3.9.
POST_39_MODULES = {"tomllib": "3.11 tomllib"}

# dataclass() keyword arguments added after 3.9.
POST_39_DATACLASS_KWARGS = {
    "kw_only": "3.10",
    "match_args": "3.10",
    "slots": "3.10",
    "weakref_slot": "3.10",
}


def _python_files():
    for directory in SCAN_DIRS:
        if not directory.is_dir():
            continue
        yield from sorted(directory.rglob("*.py"))


ALL_FILES = list(_python_files())


def _rel(path: Path) -> str:
    return str(path.relative_to(APP_ROOT))


def _has_bitor(node: ast.AST) -> bool:
    """True if `node` contains a `|` — i.e. a PEP-604 union."""
    return any(
        isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr) for sub in ast.walk(node)
    )


class _Post39Visitor(ast.NodeVisitor):
    def __init__(self, path: Path, has_future_annotations: bool):
        self.path = path
        self.has_future_annotations = has_future_annotations
        self.hits: list[str] = []

    def _hit(self, node: ast.AST, msg: str) -> None:
        self.hits.append(f"{_rel(self.path)}:{getattr(node, 'lineno', '?')}: {msg}")

    # -- syntax that ast.parse(feature_version=...) also catches, kept here
    # -- so a single failing test names the construct rather than "invalid
    # -- syntax".
    def visit_Match(self, node):
        self._hit(node, "3.10 match/case statement")
        self.generic_visit(node)

    def visit_TryStar(self, node):
        self._hit(node, "3.11 except* (exception groups)")
        self.generic_visit(node)

    # -- imports
    def visit_Import(self, node):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in POST_39_MODULES:
                self._hit(node, f"{POST_39_MODULES[top]}: import {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        top = module.split(".")[0]
        if top in POST_39_MODULES:
            self._hit(node, f"{POST_39_MODULES[top]}: from {module} import ...")
        for alias in node.names:
            if alias.name in POST_39_NAMES:
                self._hit(node, f"{POST_39_NAMES[alias.name]}: from {module} import {alias.name}")
        self.generic_visit(node)

    # -- attribute access + bare names
    def visit_Attribute(self, node):
        if node.attr in POST_39_NAMES:
            self._hit(node, f"{POST_39_NAMES[node.attr]}: .{node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in ("ExceptionGroup", "BaseExceptionGroup", "aiter", "anext"):
            self._hit(node, POST_39_NAMES[node.id])
        self.generic_visit(node)

    # -- calls
    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            name = ""

        if name == "zip":
            for kw in node.keywords:
                if kw.arg == "strict":
                    self._hit(node, "3.10 zip(strict=...) — drop it, False is the 3.9 default")

        if name in ("isinstance", "issubclass") and len(node.args) > 1:
            # The classinfo argument is evaluated eagerly, so PEP-604 here
            # is a runtime TypeError on 3.9 even with __future__ annotations.
            if _has_bitor(node.args[1]):
                self._hit(
                    node,
                    f"3.10 PEP-604 union evaluated at runtime in {name}() "
                    f"— use a tuple: {name}(x, (A, B))",
                )

        if name == "dataclass":
            for kw in node.keywords:
                if kw.arg in POST_39_DATACLASS_KWARGS:
                    self._hit(
                        node,
                        f"{POST_39_DATACLASS_KWARGS[kw.arg]} dataclass({kw.arg}=...)",
                    )

        self.generic_visit(node)

    # -- annotations, but ONLY where they are evaluated at runtime.
    # With `from __future__ import annotations` every annotation is stored
    # as a string and never evaluated, so PEP-604 there is fine on 3.9.
    def _check_annotation(self, node, annotation) -> None:
        if annotation is None or self.has_future_annotations:
            return
        if _has_bitor(annotation):
            self._hit(
                node,
                "3.10 PEP-604 union in a runtime-evaluated annotation — add "
                "`from __future__ import annotations` to this file, or use "
                "typing.Optional/typing.Union",
            )

    def visit_AnnAssign(self, node):
        self._check_annotation(node, node.annotation)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
            if arg is not None:
                self._check_annotation(node, arg.annotation)
        self._check_annotation(node, node.returns)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def test_the_scan_actually_found_files():
    """A typo in SCAN_DIRS would make every check below vacuously pass."""
    assert len(ALL_FILES) > 100, f"expected the whole tree, scanned {len(ALL_FILES)} files"


@pytest.mark.parametrize("path", ALL_FILES, ids=_rel)
def test_file_parses_under_the_39_grammar(path: Path):
    """CPython's parser, restricted to the 3.9 grammar.

    This is the closest thing to a real 3.9 compile check that is
    available from a 3.11 interpreter — it is the same PEG parser the
    3.9 interpreter uses, with the post-3.9 productions switched off.
    """
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path), feature_version=(3, 9))
    except SyntaxError as exc:
        pytest.fail(
            f"{_rel(path)}:{exc.lineno}: not valid Python 3.9 syntax — {exc.msg}\n"
            "The Coral image runs 3.9; see this module's docstring."
        )


@pytest.mark.parametrize("path", ALL_FILES, ids=_rel)
def test_file_uses_no_post_39_stdlib(path: Path):
    """Names that parse on 3.9 but blow up there at import or call time."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    has_future_annotations = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )
    visitor = _Post39Visitor(path, has_future_annotations)
    visitor.visit(tree)
    assert not visitor.hits, (
        "post-3.9 construct(s) found — the Coral image (Python 3.9) shares "
        "this source tree and will fail to import.\n"
        + "\n".join(visitor.hits)
        + "\nRewrite in the 3.9-safe form; do not add the name to "
        "POST_39_NAMES. See this module's docstring for the table."
    )


def test_the_guard_detects_a_known_violation():
    """The guard must fail on bad input, or it is decoration.

    Without this, a refactor that quietly broke the visitor would leave
    every parametrised case green and the floor unenforced.
    """
    bad = (
        "from datetime import UTC\n"
        "import tomllib\n"
        "def f(x):\n"
        "    return isinstance(x, int | str), zip([], [], strict=True)\n"
    )
    visitor = _Post39Visitor(Path(__file__), has_future_annotations=False)
    visitor.visit(ast.parse(bad))
    found = "\n".join(visitor.hits)
    assert "datetime.UTC" in found
    assert "tomllib" in found
    assert "PEP-604 union evaluated at runtime" in found
    assert "zip(strict=" in found

    # And the grammar check must reject 3.10-only syntax.
    with pytest.raises(SyntaxError):
        ast.parse("match x:\n    case 1:\n        pass\n", feature_version=(3, 9))
