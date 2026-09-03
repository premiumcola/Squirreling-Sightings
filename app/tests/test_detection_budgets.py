"""HYG · the detection-side packages stay inside their budgets.

The same mechanical guard `test_tracking_worker_budgets.py` puts on the
post-clip worker, over the four packages the recognition pipeline lives
in. It exists because both files it was written for had already grown
past the ceiling before anyone noticed: `tracker_core/__init__.py` to
951 lines with a 358-line `associate_detections`, and
`detectors/wildlife.py` to 520 with a 163-line `__init__`.

Two properties, both static:

  * the budgets from CLAUDE.md — 500 lines per file, 80 per function;
  * the import surface the rest of the app reaches for still resolves.
    The failure mode of a package split is a name that quietly stops
    being importable from the package root, and several of the call
    sites are lazy imports inside functions that no other test runs.

No detector is constructed, no model loaded, no video decoded.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

FILE_LIMIT = 500
FUNC_LIMIT = 80

PACKAGES = ("tracker_core", "detectors", "replay", "replay_batch")

# Exactly what the rest of the app imports from each package root.
# tracker_core: camera_runtime/runtime + routes/_sim_pipeline -> LiveTracker;
# tracking_worker/_video -> TrackerState + associate_detections;
# detect_setup, replay/_run, routes/cameras -> resolve_track_thresholds;
# tracking_worker/_payload -> the three threshold constants.
# detectors: server + camera_runtime build all three stages by name.
# replay: routes/replay and replay_batch/_run drive the whole flow.
PUBLIC_SURFACE = {
    "tracker_core": (
        "LiveTracker",
        "Track",
        "TrackerState",
        "associate_detections",
        "compute_miss_grace_samples",
        "nms_per_label",
        "resolve_track_thresholds",
        "MISS_GRACE_DEFAULT_SECONDS",
        "SPAWN_BLOCK_CONTAIN",
        "TRACK_FLOOR_SCORE",
        "TRACK_SPAWN_SCORE",
    ),
    "detectors": (
        "BirdSpeciesClassifier",
        "CoralObjectDetector",
        "WildlifeClassifier",
    ),
    "replay": (
        "build_comparison",
        "replay_clip",
        "resolve_replay_settings",
    ),
}


def _modules(pkg: str) -> list[Path]:
    mods = sorted((APP / pkg).glob("*.py"))
    assert mods, f"package {pkg} not found — did the path move?"
    return mods


ALL_MODULES = [m for pkg in PACKAGES for m in _modules(pkg)]


def _mid(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


@pytest.mark.parametrize("path", ALL_MODULES, ids=_mid)
def test_module_is_within_the_file_budget(path: Path):
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= FILE_LIMIT, f"{_mid(path)}: {lines} lines — split it before adding more"


@pytest.mark.parametrize("path", ALL_MODULES, ids=_mid)
def test_every_function_is_within_the_function_budget(path: Path):
    over = [
        (fn.name, fn.end_lineno - fn.lineno + 1)
        for fn in _functions(path)
        if (fn.end_lineno - fn.lineno + 1) > FUNC_LIMIT
    ]
    assert not over, f"{_mid(path)}: {over} — extract first, then add"


@pytest.mark.parametrize("pkg", sorted(PUBLIC_SURFACE), ids=str)
def test_the_split_kept_the_import_surface_reachable(pkg: str):
    mod = importlib.import_module(f"app.{pkg}")
    missing = [name for name in PUBLIC_SURFACE[pkg] if not hasattr(mod, name)]
    assert not missing, f"lost in the split: {missing}"


def test_the_tracker_package_root_declares_what_it_exports():
    """`tracker_core/__init__.py` is re-exports only, so `__all__` is the
    contract — and every name in it has to actually resolve."""
    mod = importlib.import_module("app.tracker_core")
    assert mod.__all__, "tracker_core must declare its public surface"
    unresolved = [name for name in mod.__all__ if not hasattr(mod, name)]
    assert not unresolved, f"declared but missing: {unresolved}"
    assert sorted(mod.__all__) == sorted(set(mod.__all__)), "duplicate entries in __all__"


def test_the_tracker_package_root_stays_a_thin_roof():
    """It is re-exports only by design. A function or class defined here
    is the first step back to the 951-line file this package replaced."""
    root = APP / "tracker_core" / "__init__.py"
    tree = ast.parse(root.read_text(encoding="utf-8"))
    defined = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert not defined, f"define these in a sibling module, not the roof: {defined}"


def test_only_the_inference_modules_touch_opencv():
    """cv2 import cost and the frame-decoding assumptions stay put; the
    tracker is pure geometry and must remain testable without OpenCV."""
    offenders = [
        _mid(p) for p in _modules("tracker_core") if "import cv2" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"tracker_core must not need OpenCV: {offenders}"
