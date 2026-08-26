"""HYG · the post-clip tracking package stays inside its budgets.

`tracking_worker/__init__.py` had grown to 1203 lines with a 180-line
`_run_one` and a 100-line `_update_event_achievement` in it — the
largest single offender left in `app/app`. It is now one module per
concern, and two properties keep it that way:

  * the budgets from CLAUDE.md (500 lines per file, 80 per function),
    checked mechanically over this one package;
  * the import surface the rest of the app reaches for still resolves.
    The failure mode of a package split is a name that quietly stops
    being importable from the package root, and the call sites are
    lazy imports inside functions (`camera_runtime/_recording`,
    `telegram_bot/_outbound/_best_frame`, `migrations`) that no other
    test exercises.

Pure static analysis plus attribute lookups. No worker is started, no
thread, no video decoded.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "app" / "tracking_worker"

FILE_LIMIT = 500
FUNC_LIMIT = 80

# Exactly what the rest of the app imports from the package root.
# server.py -> build_worker; camera_runtime/_recording -> TrackingJob +
# singleton; routes/tracking -> all four; routes/detection_cloud and the
# Telegram best-frame picker -> tracks_path_for; migrations -> TRACKS_SCHEMA.
PUBLIC_SURFACE = (
    "TRACKS_SCHEMA",
    "TrackingJob",
    "TrackingWorker",
    "build_worker",
    "singleton",
    "tracks_path_for",
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


def test_the_split_kept_the_import_surface_reachable():
    mod = importlib.import_module("app.tracking_worker")
    missing = [name for name in PUBLIC_SURFACE if not hasattr(mod, name)]
    assert not missing, f"lost in the split: {missing}"
    assert sorted(mod.__all__) == sorted(PUBLIC_SURFACE)


def test_only_the_video_module_touches_opencv():
    """cv2 import cost and the frame-decoding assumptions stay in one
    place; every other module must be testable without OpenCV."""
    offenders = []
    for path in _modules():
        if path.name == "_video.py":
            continue
        if "import cv2" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders, f"cv2 belongs in _video.py, not in {offenders}"
