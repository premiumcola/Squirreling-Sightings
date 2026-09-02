"""``?debug=1`` — the raw boxes and the tracker's own state.

The panel already shows what production DECIDED. To re-simulate a tick
somewhere else you need what it decided FROM: every box the model
returned, including the ones the tracker floor discarded before any gate
saw them, and every track the association step is holding, with the
numbers that kept it alive.

The flag exists because that view cannot be the default — it is bulky,
and a sub-floor box on screen invites exactly the misreading this panel
was built to end. So the property that matters most here is not what the
flag ADDS but what it must not change:

  · the same number of inferences (the sub-floor look rides on the
    full-frame pass the tick already pays for);
  · the same detections reaching the gates, the tracker and the verdict.

A debug switch that alters the thing being debugged is worse than no
switch at all, so both are pinned below.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from app.detect_setup import build_detection_setup
from app.detectors._types import STAGE_DETECTOR, Detection
from app.routes import _sim_debug, _sim_pipeline
from app.tracker_core import Track

APP = Path(__file__).resolve().parent.parent / "app"
CAM = "reolink_cx810_hof_198"


def _det(label, score, bbox, model=STAGE_DETECTOR):
    return Detection(label=label, score=score, bbox=bbox, model=model)


class _ScriptedDetector:
    """Returns a fixed set of boxes, honouring the score cut the caller
    asks for — which is exactly what pycoral does with its
    ``score_threshold``: it drops rows after inference, so a lower cut
    can only ADD boxes."""

    def __init__(self, dets):
        self._dets = list(dets)
        self.invokes = 0
        self.thresholds: list = []

    def detect_frame_raw(self, frame, threshold=0.2):
        self.invokes += 1
        self.thresholds.append(threshold)
        return [d for d in self._dets if float(d.score) >= float(threshold)]


def _setup(cam=None):
    return build_detection_setup(CAM, cam or {})


def _frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def _entry(cam_id: str, setup):
    """A fresh panel tracker, isolated from the module-global map."""
    _sim_pipeline.trackers().pop(cam_id, None)
    entry = _sim_pipeline.get_test_tracker(cam_id, setup)
    entry["last_call_ts"] = time.monotonic()
    return entry


# ── the flag changes nothing about the tick ───────────────────────────────


def test_the_flag_costs_no_extra_inference():
    """The sub-floor look rides on the full-frame pass the tick already
    pays for. A second pass would be a second TPU invoke on a device
    with one owner and three cameras queueing."""
    setup = _setup()
    plain = _ScriptedDetector([_det("person", 0.9, (10, 10, 60, 200))])
    debug = _ScriptedDetector([_det("person", 0.9, (10, 10, 60, 200))])

    _sim_pipeline.detect(plain, _frame(), setup, "off", None)
    _sim_pipeline.detect(debug, _frame(), setup, "off", None, raw_threshold=0.05)

    assert plain.invokes == debug.invokes == 1


def test_a_sub_floor_box_never_reaches_the_pipeline():
    """The boxes below the floor are REPORTING. If one reached the gates
    the flag would change the verdict it is supposed to explain."""
    setup = _setup()
    dets = [
        _det("person", 0.90, (10, 10, 60, 200)),
        _det("cat", 0.08, (400, 300, 460, 360)),
    ]
    plain, _d1, _n1, scan_plain = _sim_pipeline.detect(
        _ScriptedDetector(dets), _frame(), setup, "off", None
    )
    debug, _d2, _n2, scan_debug = _sim_pipeline.detect(
        _ScriptedDetector(dets), _frame(), setup, "off", None, raw_threshold=0.05
    )

    assert [(d.label, d.score) for d in plain] == [(d.label, d.score) for d in debug]
    assert [d.label for d in plain] == ["person"], "the 0.08 cat is under the floor"
    assert [d.label for d in scan_plain] == ["person"]
    assert sorted(d.label for d in scan_debug) == ["cat", "person"]


def test_the_debug_cut_never_rises_above_the_floor():
    """``raw_threshold`` may only lower the cut. Handed a value above the
    floor it must not start hiding boxes production would have seen."""
    setup = _setup()
    det = _ScriptedDetector([_det("person", 0.4, (10, 10, 60, 200))])

    merged, _diag, _n, _scan = _sim_pipeline.detect(
        det, _frame(), setup, "off", None, raw_threshold=0.9
    )

    assert det.thresholds == [pytest.approx(setup.floor)]
    assert [d.label for d in merged] == ["person"]


# ── what the flag adds ────────────────────────────────────────────────────


def test_every_raw_box_carries_class_score_bbox_and_stage():
    setup = _setup()
    sim = _sim_pipeline.SimPass(
        full_scan=[
            _det("person", 0.90, (10, 20, 70, 220)),
            _det("cat", 0.08, (400, 300, 460, 360)),
        ]
    )

    block = _sim_debug.build_debug(entry=_entry(CAM, setup), sim=sim, setup=setup)

    rows = block["raw_detections"]
    assert [r["label"] for r in rows] == ["person", "cat"], "highest score first"
    assert rows[0] == {
        "label": "person",
        "score": 0.9,
        # [x, y, w, h] — the same shape the overlay rows use.
        "bbox": [10, 20, 60, 200],
        "model": STAGE_DETECTOR,
        "above_floor": True,
    }
    assert rows[1]["above_floor"] is False
    assert block["raw_below_floor"] == 1
    assert block["track_floor"] == pytest.approx(setup.floor)


def test_a_live_track_reports_the_state_that_kept_it_alive():
    setup = _setup()
    entry = _entry("cam_live_debug", setup)
    box = (100, 100, 200, 300)
    _sim_pipeline.run_tracker(entry, [_det("person", 0.9, box)], setup, 1280, 720, 1.0)
    # Second tick, slightly moved — this is the one that MATCHES, and
    # matching is what produces an overlap to report.
    moved = (110, 104, 210, 304)
    _sim_pipeline.run_tracker(entry, [_det("person", 0.8, moved)], setup, 1280, 720, 1.0)

    rows = _sim_debug.track_rows(entry, time.monotonic())

    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "active"
    assert row["id"] == 1, "the badge the overlay draws"
    assert row["label"] == "person"
    assert row["model"] == STAGE_DETECTOR
    assert row["misses"] == 0
    assert row["score"] == pytest.approx(0.8), "the newest sample, not the best one"
    assert row["best_score"] == pytest.approx(0.9)
    assert row["age_s"] >= 0.0 and row["idle_s"] >= 0.0
    assert 0.0 < row["last_iou"] <= 1.0


def test_a_spawn_reports_no_overlap_because_there_was_none():
    """``last_iou`` is None, not 0.0, for a track that has not yet been
    matched — nothing overlapped it, and 0.0 would read as "matched with
    no overlap", which the association step cannot do."""
    setup = _setup()
    entry = _entry("cam_spawn_debug", setup)
    _sim_pipeline.run_tracker(
        entry, [_det("person", 0.9, (100, 100, 200, 300))], setup, 1280, 720, 1.0
    )

    row = _sim_debug.track_rows(entry, time.monotonic())[0]

    assert row["last_iou"] is None
    assert row["samples"] == 1


def test_a_coasting_track_is_not_reported_as_active():
    """A track alive only on its miss-grace window is the most common
    reason an id outlives what the operator can see on screen."""
    setup = _setup()
    entry = _entry("cam_coast_debug", setup)
    _sim_pipeline.run_tracker(
        entry, [_det("person", 0.9, (100, 100, 200, 300))], setup, 1280, 720, 1.0
    )
    _sim_pipeline.run_tracker(entry, [], setup, 1280, 720, 1.0)

    row = _sim_debug.track_rows(entry, time.monotonic())[0]

    assert row["state"] == "coasting"
    assert row["misses"] >= 1


def test_a_closed_track_stays_visible_with_its_reason():
    setup = _setup()
    entry = _entry("cam_closed_debug", setup)
    tracker = entry["tracker"]
    _sim_pipeline.run_tracker(
        entry, [_det("person", 0.9, (100, 100, 200, 300))], setup, 1280, 720, 1.0
    )
    track = tracker.state.active.pop()
    track.active = False
    track.end_reason = "aged_out"
    tracker.state.close_track(track)

    rows = _sim_debug.track_rows(entry, time.monotonic())

    assert [r["state"] for r in rows] == ["closed"]
    assert rows[0]["end_reason"] == "aged_out"


def test_the_track_list_is_bounded():
    """A panel left open for an hour must not answer with a thousand
    dead tracks. The tracker's own ``closed`` list is already capped for
    the live session; this caps what the payload carries out of it."""
    setup = _setup()
    entry = _entry("cam_bounded_debug", setup)
    tracker = entry["tracker"]
    now = time.monotonic()
    for i in range(_sim_debug.CLOSED_TRACKS + 5):
        track = Track(f"t{i:02d}", "person", i)
        track.add_sample(i, now, {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, 0.9, "detect", "person")
        track.active = False
        tracker.state.close_track(track)

    rows = _sim_debug.track_rows(entry, now)

    assert len(rows) == _sim_debug.CLOSED_TRACKS
    assert rows[-1]["track_id"] == "t12", "the newest closed track is the interesting one"


# ── the modes block, on every tick ────────────────────────────────────────


class _Backend:
    mode = "coral"
    _cpu_mode = False
    reason = "ok"


def test_the_modes_block_names_the_device_the_job_and_the_framing():
    setup = _setup()
    cam_cfg = {"id": CAM, "role": "wildlife", "alarm_profile": "nacht"}

    class _RT:
        detector = _Backend()

    modes = _sim_debug.modes_block(rt=_RT(), cam_cfg=cam_cfg, setup=setup, det_mode="3x3")

    assert modes["inference"]["device"] == "tpu"
    assert modes["inference"]["api"] == "pycoral"
    assert modes["role"] == "wildlife"
    assert modes["alarm_profile"] == "nacht"
    # Configured vs actually run — a reader that sees only one cannot
    # tell an experiment from production.
    assert modes["roi_mode"] == setup.det_mode
    assert modes["roi_mode_active"] == "3x3"


def test_a_cpu_fallback_is_not_reported_as_a_tpu():
    class _CPU:
        mode = "cpu"
        _cpu_mode = True
        reason = "no delegate"

    class _RT:
        detector = _CPU()

    modes = _sim_debug.modes_block(rt=_RT(), cam_cfg={}, setup=_setup(), det_mode="off")

    assert modes["inference"]["device"] == "cpu"
    assert modes["inference"]["api"] == "tflite-cpu"


# ── the wiring ────────────────────────────────────────────────────────────


def test_the_handler_only_lowers_the_cut_behind_the_flag():
    """Pinned in the source because the alternative is a live TPU: the
    handler must pass ``raw_threshold`` only when the flag is set."""
    src = (APP / "routes" / "coral_test_detection.py").read_text(encoding="utf-8")
    assert "raw_threshold=(_sim_debug.DEBUG_RAW_FLOOR if debug else None)" in src
    assert 'body["debug"] = _sim_debug.build_debug(' in src
    # …and the modes block is NOT behind the flag.
    assert '"modes": _sim_debug.modes_block(' in src
