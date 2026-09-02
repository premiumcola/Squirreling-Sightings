"""The Simulieren panel must run production's configuration.

"Die Erkennung und Simu soll mit exakt dem gleichen Setup laufen!" The
panel had drifted into a pipeline of its own: its own tiling mode from a
URL query arg, a hard-coded 0.20 inference threshold, no bottom crop, no
exclusion masks, no inclusion zones, ``object_filter`` applied AFTER the
tracker instead of before it, and a tracker whose miss-grace was computed
against the camera's configured frame rate while its ticks arrived at
about 1 Hz.

These tests pin the parts of that which are testable without a camera:
the shared configuration object and the shared gates in production's
order.

They also pin what deliberately did NOT change — the ``_LABEL_MIN_BBOX``
size floor stays unreachable — and the state boundary: the panel takes
production's numbers and keeps its own objects.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import pytest

from app import mask_zones
from app.detect_setup import (
    apply_bottom_crop,
    apply_object_filter,
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


def _poly(pts, **extra):
    return {"points": [{"x": x, "y": y} for x, y in pts], **extra}


# ── the size floor stays where it was: unreachable ──────────────────────


def test_the_size_floor_is_not_armed_on_the_alarm_path():
    """``_LABEL_MIN_BBOX`` is (0.15 height OR 0.02 area) and the AREA rule
    is the one that binds: at 2560×1440 a 0.35-aspect standing person is
    dropped below h≈500 px, i.e. roughly beyond 5.4 m on a 4 mm lens.
    Werkstatt and Garten are security cameras where a person at 6–15 m is
    the normal case. Arming that on the live path is a production
    behaviour change needing a per-camera setting and an operator
    decision, not a side effect of a diagnostic-panel commit."""
    src = (APP / "camera_runtime" / "_main_loop.py").read_text(encoding="utf-8")

    assert "size_floor" not in src
    assert "apply_size_floor" not in src


def test_the_size_floor_is_not_armed_on_the_panel_path_either():
    """A panel that drops what production keeps is the same class of lie
    as a panel that keeps what production drops."""
    for name in ("_sim_pipeline.py", "_sim_trace.py", "coral_test_detection.py"):
        src = (APP / "routes" / name).read_text(encoding="utf-8")
        assert "apply_size_floor" not in src, name


def test_the_size_floor_math_is_what_the_revert_says_it_is():
    """The numbers in the note above, checked rather than asserted: a
    0.35-aspect person box at 2560×1440 needs h ≥ 500 px to clear the 2 %
    area rule, so 30 % of frame height is dropped and the 15 % HEIGHT rule
    never decides anything for a human-shaped box."""
    from app.detectors._filters import LabelFilterMixin

    min_h_frac, min_area_frac = LabelFilterMixin._LABEL_MIN_BBOX["person"]
    frame_w, frame_h = 2560, 1440
    frame_area = frame_w * frame_h

    def survives(h_px):
        w_px = 0.35 * h_px
        return h_px >= min_h_frac * frame_h and w_px * h_px >= min_area_frac * frame_area

    assert not survives(432), "30 % of frame height is dropped by the area rule"
    assert survives(500), "the real cutoff is ~35 % of frame height"
    # The height rule alone would have passed the 432 px box — it is the
    # area rule that binds, which is why "15 % of frame height" understates
    # the guard by more than a factor of two.
    assert 432 >= min_h_frac * frame_h


def test_the_size_floor_table_still_has_exactly_one_owner():
    """Two copies of the table is how it went dead the first time."""
    filters = (APP / "detectors" / "_filters.py").read_text(encoding="utf-8")

    assert filters.count("(0.15, 0.02)") == 1


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


# A mask over the left third of a 960×540 frame (recorded against the
# 1280×720 canvas the editor saves in) and a zone over its right half.
_MASK_LEFT = _poly([(0, 0), (420, 0), (420, 720), (0, 720)])
_ZONE_RIGHT = _poly([(640, 0), (1280, 0), (1280, 720), (640, 720)])
_GARTEN_CFG = {"masks": [_MASK_LEFT], "zones": [_ZONE_RIGHT]}


def _fresh_sim_caches():
    _sim_pipeline._SIM_MASK_ZONES.pop(CAM, None)
    _sim_pipeline.trackers().pop(CAM, None)


def test_masks_and_zones_reach_the_panel_as_named_verdicts():
    """The operator drew an 11-vertex exclusion mask on Garten and the
    panel never applied it. Applying it silently would be no better: a
    box that simply vanishes is indistinguishable from a detector that
    missed it."""
    _fresh_sim_caches()
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    setup = build_detection_setup(CAM, _GARTEN_CFG)
    raw = [
        _det("cat", 0.60, (10, 10, 200, 300)),  # centre in the mask
        _det("bird", 0.60, (400, 10, 500, 200)),  # centre outside the zone
        _det("person", 0.60, (600, 40, 800, 500)),  # inside the zone, unmasked
    ]

    kept, drops = _sim_pipeline.run_gates(_GARTEN_CFG, frame, raw, setup)

    assert [d.label for d in kept] == ["person"]
    by_label = {d.label: (verdict, reason) for d, verdict, reason in drops}
    assert by_label["cat"][0] == _sim_pipeline.VERDICT_MASKED
    assert by_label["bird"][0] == _sim_pipeline.VERDICT_OUTSIDE_ZONE
    for _verdict, reason in by_label.values():
        assert reason, "a dropped box must name the gate in German"


def test_the_panel_and_the_loop_run_the_same_mask_geometry():
    """Same polygons, same verdicts — the point of sharing the functions
    rather than the state."""
    _fresh_sim_caches()
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    dets = [_det("cat", 0.60, (10, 10, 200, 300)), _det("person", 0.60, (600, 40, 800, 500))]

    cache = mask_zones.MaskZoneCache()
    loop_side = cache.zoned(
        cache.masked(list(dets), frame, _GARTEN_CFG["masks"], CAM),
        frame,
        _GARTEN_CFG["zones"],
        CAM,
    )
    setup = build_detection_setup(CAM, _GARTEN_CFG)
    panel_side, _ = _sim_pipeline.run_gates(_GARTEN_CFG, frame, list(dets), setup)

    assert [d.label for d in loop_side] == [d.label for d in panel_side] == ["person"]


def test_the_object_filter_runs_before_the_tracker():
    """It used to run after, as a display verdict only — so filtered
    boxes still entered the association and consumed track ids, and the
    #N badges drifted against production's identities."""
    _fresh_sim_caches()
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    setup = build_detection_setup(CAM, {"object_filter": ["person"]})
    raw = [
        _det("person", 0.60, (500, 40, 700, 500)),
        _det("truck", 0.60, (10, 10, 300, 300)),
    ]

    kept, drops = _sim_pipeline.run_gates({}, frame, raw, setup)

    assert [d.label for d in kept] == ["person"]
    assert drops[0][1] == _sim_pipeline.VERDICT_FILTERED
    # …and the gate order itself, read off the source: class filter,
    # mask, zone — the loop's order.
    src = (APP / "routes" / "_sim_pipeline.py").read_text(encoding="utf-8")
    body = src[src.index("def run_gates") :]
    order = [
        body.index("apply_object_filter"),
        body.index("cache.masked("),
        body.index("cache.zoned("),
    ]
    assert order == sorted(order)


# ── the mask cache: same configuration, different object ────────────────


class _LiveRuntimeSpy:
    """The fields the alarm loop reads between two of its own frames.

    ``_motion.py`` reads ``self._mask_image`` / ``self._zone_image``
    directly after an ``_ensure_*`` call, so anything that writes them
    from another thread writes into the running detector.
    """

    def __init__(self):
        self.camera_id = CAM
        self._mask_image = None
        self._mask_sig = None
        self._zone_image = None
        self._zone_sig = None


def test_the_panel_takes_no_runtime_and_cannot_reach_one():
    """The worst version of this bug: a diagnostic tick that DISABLES the
    operator's exclusion mask in production. ``run_gates`` used to call
    ``rt._filter_masked_detections`` on the live runtime, which rebuilds
    ``rt._mask_image`` in place."""
    params = list(inspect.signature(_sim_pipeline.run_gates).parameters)

    assert params[0] == "cam_cfg", "the gates take the CONFIG, never the runtime"
    src = (APP / "routes" / "_sim_pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    reaches_in = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "rt"
    ]
    assert reaches_in == []
    # …and no runtime cache field is ACCESSED anywhere in the module.
    # Attribute nodes, not a substring search: the module comment has to
    # be able to name the fields it explains staying away from.
    forbidden = {"_mask_image", "_mask_sig", "_zone_image", "_zone_sig", "_tracker"}
    touched = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} & forbidden
    assert touched == set()


def test_a_sim_tick_leaves_the_live_cache_fields_untouched():
    """Behavioural companion to the source check above."""
    _fresh_sim_caches()
    live = _LiveRuntimeSpy()
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    setup = build_detection_setup(CAM, _GARTEN_CFG)

    kept, drops = _sim_pipeline.run_gates(
        _GARTEN_CFG, frame, [_det("cat", 0.60, (10, 10, 200, 300))], setup
    )

    assert kept == [] and drops[0][1] == _sim_pipeline.VERDICT_MASKED
    assert live._mask_image is None and live._mask_sig is None
    assert live._zone_image is None and live._zone_sig is None
    # The panel built its own raster instead.
    assert _sim_pipeline.sim_mask_zones(CAM).mask_image is not None


def test_the_raster_is_published_after_the_image_it_describes():
    """``_ensure_mask_image`` used to set the signature FIRST. A reader
    entering that window saw "cache current" beside a stale or unbuilt
    image — the mask silently off for those frames. Pinned on the cache
    and on the runtime mirror that copies from it."""
    for path, image_attr, sig_attr in (
        (APP / "mask_zones.py", "self.mask_image", "self.mask_sig"),
        (APP / "camera_runtime" / "_zones.py", "self._mask_image", "self._mask_sig"),
    ):
        src = path.read_text(encoding="utf-8")
        assert src.index(f"{image_attr} = ") < src.index(f"{sig_attr} = "), path.name


def test_two_caches_do_not_share_a_raster():
    a, b = mask_zones.MaskZoneCache(), mask_zones.MaskZoneCache()
    a.refresh_mask([_MASK_LEFT])

    assert a.mask_image is not None
    assert b.mask_image is None and b.mask_sig is None


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


# ── what a tick costs, measured rather than claimed ─────────────────────


class _CountingDetector:
    """Counts invokes. The TPU has one owner and three live cameras."""

    def __init__(self):
        self.invokes = 0

    def detect_frame_raw(self, frame, threshold=0.2):
        self.invokes += 1
        return []


@pytest.mark.parametrize(
    "mode, motion_box, expected",
    [
        ("off", None, 1),
        ("2x2", None, 5),
        ("3x3", None, 10),
        ("roi", None, 1),  # no motion box → no crop worth magnifying
        ("roi", (1100, 600, 300, 300), 2),  # small blob → one crop
        ("roi", (200, 200, 1600, 900), 5),  # blob spanning the frame → four
    ],
)
def test_the_reported_invoke_count_is_the_one_actually_spent(mode, motion_box, expected):
    """The docstring used to claim ``full_dets=`` cut a 2×2 tick from
    1+1+4 to 1+4. It never was 1+1+4 — the old sim ran no separate full
    pass, so ``tiled_detect`` paid for the only one. Both the count spent
    and the count reported to the admission gate are checked, because the
    gate paces the client watchdog off the reported number."""
    detector = _CountingDetector()
    frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
    setup = build_detection_setup(CAM, {})

    _dets, diag, reported, _scan = _sim_pipeline.detect(detector, frame, setup, mode, motion_box)

    assert detector.invokes == expected
    assert reported == expected
    assert reported == 1 + int(diag.get("tiles") or 0)


def test_off_mode_still_reports_the_full_tiling_diag():
    """A hand-rolled ``{"mode": "off", "tiles": 0}`` dropped raw / merged
    / tile_hits / magnification / crop_px from the Diagnose panel."""
    detector = _CountingDetector()
    frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
    setup = build_detection_setup(CAM, {})

    _dets, diag, _n, _scan = _sim_pipeline.detect(detector, frame, setup, "off", None)

    for key in ("mode", "tiles", "raw", "merged", "tile_hits", "magnification", "crop_px"):
        assert key in diag, key
    assert diag["mode"] == "off"


# ── the loop resolves its configuration once, not per frame ─────────────


def test_the_loop_does_not_rebuild_the_setup_every_frame():
    """A frozen dataclass, two dict copies, a frozenset and a
    resolve_track_thresholds call, ~20×/s across three cameras, for
    values that only change on a runtime rebuild."""
    loop = (APP / "camera_runtime" / "_main_loop.py").read_text(encoding="utf-8")
    runtime = (APP / "camera_runtime" / "runtime.py").read_text(encoding="utf-8")

    assert "build_detection_setup(" not in loop
    assert "setup = self.detect_setup" in loop
    assert "self.detect_setup = build_detection_setup(" in runtime


def test_every_camera_config_change_restarts_the_runtime():
    """Which is what makes resolving once safe: the setup's lifetime is
    the runtime's, exactly like self._tracker's.

    ``app.server`` cannot be imported here (module-level boot side
    effects — see test_no_server_import), so the diff function is
    executed out of its own source.
    """
    src = (APP / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_compute_camera_diff"
    )
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "server.py", "exec"), ns)

    _rm, _add, restart = ns["_compute_camera_diff"](
        {CAM}, {CAM: {"roi_mode": "off"}}, {CAM: {"roi_mode": "3x3"}}
    )

    assert restart == {CAM}


# ── the panel says what it does not do ──────────────────────────────────


def test_every_unsimulated_gate_is_declared():
    """Anything that legitimately differs has to be visible, or the
    operator is again reading a number that describes a configuration
    nobody runs."""
    # Lives in _sim_debug since the orchestrator hit its file ceiling.
    src = (APP / "routes" / "_sim_debug.py").read_text(encoding="utf-8")
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
