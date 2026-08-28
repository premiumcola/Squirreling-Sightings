"""The Simulieren panel must run production's configuration.

"Die Erkennung und Simu soll mit exakt dem gleichen Setup laufen!" The
panel had drifted into a pipeline of its own: its own tiling mode from a
URL query arg, a hard-coded 0.20 inference threshold, no bottom crop, no
exclusion masks, no inclusion zones, ``object_filter`` applied AFTER the
tracker instead of before it, and a tracker whose miss-grace was computed
against the camera's configured frame rate while its ticks arrived at
about 1 Hz.

These tests pin the parts of that which are testable without a camera:
the shared configuration object, the shared gates in production's order,
and the revived ``_LABEL_MIN_BBOX`` size floor — dead on BOTH live paths
because both call ``detect_frame_raw``, which runs no label filters.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from app.detect_setup import (
    apply_bottom_crop,
    apply_object_filter,
    apply_size_floor,
    build_detection_setup,
    make_spawn_for,
)
from app.detectors._types import Detection
from app.routes import _sim_pipeline
from app.tracker_core import TRACK_FLOOR_SCORE, TRACK_SPAWN_SCORE

APP = Path(__file__).resolve().parent.parent / "app"
CAM = "reolink_cx810_garten_172"


def _det(label, score, bbox):
    return Detection(label=label, score=score, bbox=bbox)


# ── the size floor, revived on both live paths ──────────────────────────


def test_a_sub_floor_person_is_dropped():
    """The guard exists for exactly the operator's twilight false
    positives: at 960×540 a real person is at least 81 px tall. A 40 px
    "person" is wood grain, a shadow or a distant silhouette."""
    small = _det("person", 0.80, (100, 100, 130, 140))
    kept, dropped = apply_size_floor([small], 960, 540)

    assert kept == []
    assert len(dropped) == 1
    assert "size_floor" in dropped[0][1]


def test_a_full_size_person_survives_the_floor():
    """Guard against a floor so high nothing gets through."""
    big = _det("person", 0.60, (100, 50, 260, 480))
    kept, dropped = apply_size_floor([big], 960, 540)

    assert len(kept) == 1 and dropped == []


def test_the_floor_only_applies_to_labels_that_have_one():
    """A squirrel at 30 px is the whole point of this project."""
    tiny = _det("squirrel", 0.55, (10, 10, 40, 40))
    kept, _ = apply_size_floor([tiny], 960, 540)

    assert len(kept) == 1


def test_the_production_path_applies_the_size_floor():
    """``camera_runtime/_main_loop`` calls ``detect_frame_raw``, which
    runs no label filters — so the guard is only live if the loop applies
    it itself. It did not for months."""
    src = (APP / "camera_runtime" / "_main_loop.py").read_text(encoding="utf-8")

    assert "apply_size_floor" in src, "the alarm loop must apply the size floor"
    assert (
        src.count("apply_size_floor(") >= 2
    ), "both the full-frame pass and the ROI rescue produce boxes that need the floor"


def test_the_sim_path_applies_the_size_floor():
    src = (APP / "routes" / "_sim_pipeline.py").read_text(encoding="utf-8")

    assert "apply_size_floor" in src


def test_the_size_floor_table_has_exactly_one_owner():
    """Two copies of the table is how it went dead the first time."""
    filters = (APP / "detectors" / "_filters.py").read_text(encoding="utf-8")

    assert filters.count("(0.15, 0.02)") == 1
    assert "_LABEL_MIN_BBOX: dict[str, tuple[float, float]] = LABEL_MIN_BBOX" in filters


# ── one source of configuration ─────────────────────────────────────────


def test_the_setup_reads_the_tracker_floor_not_a_literal():
    """The panel inferred at a hard-coded 0.20 while the loop inferred at
    the tracker's continuation floor — identical only by coincidence at
    the defaults."""
    setup = build_detection_setup(CAM, {"track_continue_min_score": 0.35})

    assert setup.floor == pytest.approx(0.35)
    assert _sim_pipeline.detect.__doc__ and "floor" in _sim_pipeline.detect.__doc__


def test_the_defaults_match_the_tracker_module():
    setup = build_detection_setup(CAM, {})

    assert setup.floor == pytest.approx(TRACK_FLOOR_SCORE)
    assert setup.spawn_default == pytest.approx(TRACK_SPAWN_SCORE)


def test_the_tiling_mode_defaults_to_the_cameras_own():
    """The panel could be tiling 3×3 while the camera ran ``off``."""
    assert build_detection_setup(CAM, {"roi_mode": "2x2"}).det_mode == "2x2"
    assert build_detection_setup(CAM, {}).det_mode == "off"


def test_the_global_min_score_is_carried_but_never_a_gate():
    """``detection_min_score`` stopped being the live cutoff when the
    two-tier tracker landed. The panel still applied it as a hard reject,
    which is how a 0.52 person read REJECTED in the panel and alerted in
    production."""
    setup = build_detection_setup(CAM, {"detection_min_score": 0.55})

    assert setup.min_score == pytest.approx(0.55)
    dets = [_det("cat", 0.30, (0, 0, 200, 200))]
    kept, dropped = apply_object_filter(dets, setup.object_filter)
    assert kept == dets and dropped == [], "no gate may consult min_score"


def test_the_bottom_crop_is_shared():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    assert apply_bottom_crop(frame, 0).shape[0] == 480
    assert apply_bottom_crop(frame, 40).shape[0] == 440
    # A crop taller than the frame would leave nothing to infer on.
    assert apply_bottom_crop(frame, 480).shape[0] == 480


def test_spawn_for_has_one_implementation():
    spawn_for = make_spawn_for({"person": 0.72}, 0.50)

    assert spawn_for("person") == pytest.approx(0.72)
    assert spawn_for("cat") == pytest.approx(0.50)
    loop = (APP / "camera_runtime" / "_main_loop.py").read_text(encoding="utf-8")
    assert "make_spawn_for(" in loop, "the loop must not rebuild the closure itself"


# ── gates, in production's order ────────────────────────────────────────


class _MaskingRuntime:
    """Runtime stub whose mask drops cats and whose zone drops birds."""

    def _filter_masked_detections(self, frame, dets):
        return [d for d in dets if d.label != "cat"]

    def _filter_zoned_detections(self, frame, dets):
        return [d for d in dets if d.label != "bird"]


def test_masks_and_zones_reach_the_panel_as_named_verdicts():
    """The operator drew an 11-vertex exclusion mask on Garten and the
    panel never applied it. Applying it silently would be no better: a
    box that simply vanishes is indistinguishable from a detector that
    missed it."""
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    setup = build_detection_setup(CAM, {})
    raw = [
        _det("cat", 0.60, (10, 10, 200, 300)),
        _det("bird", 0.60, (300, 10, 400, 200)),
        _det("person", 0.60, (500, 40, 700, 500)),
    ]

    kept, drops = _sim_pipeline.run_gates(_MaskingRuntime(), frame, raw, setup)

    assert [d.label for d in kept] == ["person"]
    by_label = {d.label: (verdict, reason) for d, verdict, reason in drops}
    assert by_label["cat"][0] == _sim_pipeline.VERDICT_MASKED
    assert by_label["bird"][0] == _sim_pipeline.VERDICT_OUTSIDE_ZONE
    for _verdict, reason in by_label.values():
        assert reason, "a dropped box must name the gate in German"


def test_the_object_filter_runs_before_the_tracker():
    """It used to run after, as a display verdict only — so filtered
    boxes still entered the association and consumed track ids, and the
    #N badges drifted against production's identities."""
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    setup = build_detection_setup(CAM, {"object_filter": ["person"]})
    raw = [
        _det("person", 0.60, (500, 40, 700, 500)),
        _det("truck", 0.60, (10, 10, 300, 300)),
    ]

    kept, drops = _sim_pipeline.run_gates(_MaskingRuntime(), frame, raw, setup)

    assert [d.label for d in kept] == ["person"]
    assert drops[0][1] == _sim_pipeline.VERDICT_FILTERED
    # …and the gate order itself, read off the source: size floor, class
    # filter, mask, zone — the loop's order.
    src = (APP / "routes" / "_sim_pipeline.py").read_text(encoding="utf-8")
    body = src[src.index("def run_gates") :]
    order = [
        body.index("apply_size_floor"),
        body.index("apply_object_filter"),
        body.index("_filter_masked_detections"),
        body.index("_filter_zoned_detections"),
    ]
    assert order == sorted(order)


# ── the tracker: same configuration, different object ───────────────────


def test_the_panel_never_touches_the_live_tracker():
    """Stepping ``rt._tracker`` would inject ~1 Hz sim ticks into the
    live association: real track ids shift, real miss-grace windows get
    consumed, and the operator's Telegram alerts change because they
    opened a diagnostic panel."""
    src = (APP / "routes" / "_sim_pipeline.py").read_text(encoding="utf-8")
    # Attribute access, not a substring search — the module's docstring
    # explains WHY it must not touch rt._tracker, and a text match would
    # fail on the explanation.
    reaches_in = [
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Attribute)
        and node.attr == "_tracker"
        and isinstance(node.value, ast.Name)
    ]

    assert reaches_in == []
    assert "LiveTracker(" in src, "the panel builds its own instance"


def test_the_panel_tracker_gets_the_cameras_parameters():
    setup = build_detection_setup(
        CAM,
        {
            "track_spawn_min_score": 0.62,
            "track_continue_min_score": 0.31,
            "track_miss_grace_seconds": 4.0,
            "track_iou_match_threshold": 0.4,
        },
    )
    _sim_pipeline.trackers().pop(CAM, None)
    tracker = _sim_pipeline.get_test_tracker(CAM, setup)["tracker"]

    assert tracker.spawn_default == pytest.approx(0.62)
    assert tracker.floor == pytest.approx(0.31)
    assert tracker.grace_seconds == pytest.approx(4.0)
    assert tracker.iou_threshold == pytest.approx(0.4)
    _sim_pipeline.trackers().pop(CAM, None)


def test_the_grace_clock_is_the_measured_tick_cadence():
    """``1000 / frame_interval_ms`` is the camera's rate, not the panel's.
    At 150 ms and an 8 s grace that was 53 samples at a ~1 Hz tick — 53 s
    of grace, and a dead subject keeping its #N for a minute."""
    entry = {"last_tick_ts": 0.0, "tick_fps": 1.0}
    first = _sim_pipeline.measure_tick_fps(entry)
    second = _sim_pipeline.measure_tick_fps(entry)

    assert first == pytest.approx(1.0), "the first tick has nothing to measure"
    # Two calls back to back look very fast; the clamp keeps that from
    # collapsing the grace to nothing.
    assert second <= 15.0


def test_there_is_no_second_death_clock():
    """A shadow emitter on a wall-clock grace reported deaths the tracker
    had not performed — the Trace tab and the tracker disagreed by ~45 s."""
    src = (APP / "routes" / "_sim_pipeline.py").read_text(encoding="utf-8")

    assert "grace_ms" not in src
    body = src[src.index("def _emit_deaths") :]
    assert "tracker.state.active" in body, "DEATH must come from the tracker's own state"


# ── the panel says what it does not do ──────────────────────────────────


def test_every_unsimulated_gate_is_declared():
    """Anything that legitimately differs has to be visible, or the
    operator is again reading a number that describes a configuration
    nobody runs."""
    src = (APP / "routes" / "coral_test_detection.py").read_text(encoding="utf-8")
    block = src[src.index('"not_simulated"') :][:600]
    for gate in ("motion_gate", "confirmation_window", "wildlife_cascade", "frame_validator"):
        assert gate in block


def test_the_trace_states_the_gates_it_skips():
    src = (APP / "routes" / "_sim_trace.py").read_text(encoding="utf-8")
    body = src[src.index("def stated_gate_lines") :]
    for tag in ("[motion]", "[confirmation]", "[wildlife]", "[event_cooldown]", "[recording]"):
        assert tag in body
    assert "NICHT" in body, "the lines must say the gate is not run, in German"


def test_no_function_exceeds_the_budget():
    """CLAUDE.md: 80 lines per Python function, 500 per file. The endpoint
    was 1191 lines before this split."""
    for path in sorted((APP / "routes").glob("_sim_*.py")) + [
        APP / "routes" / "coral_test_detection.py",
        APP / "detect_setup.py",
    ]:
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 500, f"{path.name} over the file budget"
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                span = (node.end_lineno or node.lineno) - node.lineno
                assert span <= 80, f"{path.name}:{node.name} over the function budget"
