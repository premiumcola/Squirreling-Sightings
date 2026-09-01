"""TPU busy ratio — ``detectors._utilisation``.

The rolling class takes its clock as an argument, so every test below
moves a fake clock by hand: no sleeps, no wall time, and a window edge
that lands exactly where the test says it does.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

from app import app_state
from app.detectors._utilisation import (
    WINDOW_S,
    RollingUtilisation,
    combine,
    fleet_tpu_utilisation,
    tpu_utilisation,
)
from app.detectors.coral_object import CoralObjectDetector


class _Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _util(clock: _Clock, window_s: float = WINDOW_S) -> RollingUtilisation:
    return RollingUtilisation(window_s=window_s, clock=clock)


# ── RollingUtilisation ────────────────────────────────────────────────────


def test_empty_before_the_first_inference():
    clock = _Clock()
    u = _util(clock)
    clock.t += 5.0
    snap = u.snapshot()
    assert snap["count"] == 0
    assert snap["mean_ms"] is None
    assert snap["per_s"] == 0.0
    assert snap["busy"] == 0.0


def test_readouts_over_a_full_window():
    clock = _Clock()
    u = _util(clock)
    clock.t += WINDOW_S  # older than the window: span is the window itself
    # 20 inferences of 25 ms spread over the last 10 s.
    for i in range(20):
        u.record(0.025, at=clock.t - 9.5 + i * 0.5)
    snap = u.snapshot()
    assert snap["count"] == 20
    assert snap["mean_ms"] == 25.0
    assert snap["per_s"] == 2.0
    assert snap["busy"] == pytest.approx(0.05)
    assert snap["span_s"] == WINDOW_S


def test_samples_older_than_the_window_fall_out():
    clock = _Clock()
    u = _util(clock)
    clock.t += WINDOW_S
    u.record(0.1, at=clock.t - 9.0)
    u.record(0.1, at=clock.t - 1.0)
    assert u.snapshot()["count"] == 2
    clock.t += 5.0  # the first sample is now 14 s old
    assert u.snapshot()["count"] == 1


def test_young_interpreter_divides_by_its_age_not_the_window():
    clock = _Clock()
    u = _util(clock)
    clock.t += 2.0  # alive for two seconds
    u.record(0.5, at=clock.t - 1.0)
    u.record(0.5, at=clock.t)
    snap = u.snapshot()
    assert snap["span_s"] == 2.0
    assert snap["per_s"] == 1.0
    assert snap["busy"] == 0.5


def test_busy_is_capped_at_one():
    clock = _Clock()
    u = _util(clock)
    clock.t += WINDOW_S
    for i in range(10):
        u.record(2.0, at=clock.t - i)
    assert u.snapshot()["busy"] == 1.0


def test_negative_durations_do_not_count_as_idle_time():
    clock = _Clock()
    u = _util(clock)
    clock.t += WINDOW_S
    u.record(-0.5, at=clock.t)
    assert u.snapshot()["busy_s"] == 0.0


# ── combine ───────────────────────────────────────────────────────────────


def _snap(count, busy_s, span_s):
    return {"count": count, "busy_s": busy_s, "span_s": span_s}


def test_combine_adds_busy_time_and_takes_the_longest_span():
    out = combine([_snap(10, 1.0, 10.0), _snap(5, 2.0, 4.0)])
    assert out["count"] == 15
    assert out["busy_s"] == 3.0
    assert out["span_s"] == 10.0
    assert out["mean_ms"] == 200.0
    assert out["per_s"] == 1.5
    assert out["busy"] == 0.3


def test_combine_caps_and_handles_nothing():
    assert combine([_snap(50, 30.0, 10.0), _snap(50, 30.0, 10.0)])["busy"] == 1.0
    assert combine([])["count"] == 0
    assert combine([None, {}])["busy"] == 0.0


# ── per runtime / per fleet ───────────────────────────────────────────────


@dataclass
class _Stage:
    mode: str
    snap: dict
    _cpu_mode: bool = False
    reason: str = "ok"
    active_model_path: str | None = None
    _inat_interpreter: object = None
    _inat_cpu_mode: bool = True
    _inat_timing: object = None

    def utilisation(self) -> dict:
        return self.snap


@dataclass
class _Runtime:
    detector: object = None
    bird_classifier: object = None
    wildlife_classifier: object = None
    cfg: dict = field(default_factory=dict)


def test_only_stages_on_the_tpu_count():
    rt = _Runtime(
        detector=_Stage("coral", _snap(10, 1.0, 10.0)),
        bird_classifier=_Stage("cpu", _snap(99, 9.0, 10.0)),
        wildlife_classifier=_Stage("coral", _snap(2, 0.5, 10.0)),
    )
    util = tpu_utilisation(rt)
    assert util["count"] == 12
    assert util["busy"] == 0.15


def test_none_when_the_camera_runs_on_cpu_or_without_detection():
    assert tpu_utilisation(_Runtime(detector=_Stage("cpu", _snap(9, 1.0, 10.0)))) is None
    assert tpu_utilisation(_Runtime()) is None


def test_inat_stage_counts_when_it_sits_on_the_tpu():
    inat = _Stage("none", _snap(4, 0.4, 10.0))
    wild = _Stage(
        "cpu",
        _snap(1, 0.9, 10.0),
        _inat_interpreter=object(),
        _inat_cpu_mode=False,
        _inat_timing=inat,
    )
    util = tpu_utilisation(_Runtime(wildlife_classifier=wild))
    assert util["count"] == 4
    assert util["busy"] == 0.04


def test_fleet_sums_per_camera_and_keeps_each():
    fleet = fleet_tpu_utilisation(
        {
            "a": _Runtime(detector=_Stage("coral", _snap(10, 2.0, 10.0))),
            "b": _Runtime(detector=_Stage("coral", _snap(30, 3.0, 10.0))),
            "c": _Runtime(detector=_Stage("cpu", _snap(30, 3.0, 10.0))),
        }
    )
    assert fleet["window_s"] == WINDOW_S
    assert sorted(fleet["cameras"]) == ["a", "b"]
    assert fleet["cameras"]["a"]["busy"] == 0.2
    assert fleet["total"] == {
        "count": 40,
        "busy_s": 5.0,
        "span_s": 10.0,
        "mean_ms": 125.0,
        "per_s": 4.0,
        "busy": 0.5,
    }


def test_fleet_without_a_tpu_is_all_zero():
    fleet = fleet_tpu_utilisation({})
    assert fleet["cameras"] == {}
    assert fleet["total"]["busy"] == 0.0


# ── the mixin hook ────────────────────────────────────────────────────────


def test_record_timing_feeds_the_utilisation_window():
    det = CoralObjectDetector({})
    assert det.utilisation()["count"] == 0
    t0 = time.perf_counter()
    det._record_timing(t0 - 0.030, t0 - 0.025, t0 - 0.020, t0)
    snap = det.utilisation()
    assert snap["count"] == 1
    assert snap["mean_ms"] == 20.0
    assert snap["busy"] > 0.0


def test_warmup_inferences_are_not_load():
    det = CoralObjectDetector({})
    det._warming = True
    t0 = time.perf_counter()
    det._record_timing(t0 - 0.5, t0 - 0.4, t0 - 0.3, t0)
    assert det.utilisation()["count"] == 0


# ── the endpoints ─────────────────────────────────────────────────────────


def test_status_and_telemetry_expose_the_totals(monkeypatch):
    flask = pytest.importorskip("flask")
    from app.routes import bootstrap, telemetry

    runtimes = {"a": _Runtime(detector=_Stage("coral", _snap(10, 2.0, 10.0)))}

    class _Settings:
        data = {}

    class _Registry:
        def list_profiles(self):
            return []

    monkeypatch.setattr(app_state, "runtimes", runtimes, raising=False)
    monkeypatch.setattr(app_state, "settings", _Settings(), raising=False)
    monkeypatch.setattr(app_state, "cat_registry", _Registry(), raising=False)
    monkeypatch.setattr(app_state, "person_registry", _Registry(), raising=False)
    monkeypatch.setattr(app_state, "get_effective_config", lambda: {"cameras": []}, raising=False)
    monkeypatch.setattr(telemetry, "_usb_line", lambda: None)
    monkeypatch.setattr(telemetry, "_versions", lambda: {})
    telemetry._CACHE["payload"] = None

    app = flask.Flask(__name__)
    app.register_blueprint(bootstrap.bp)
    app.register_blueprint(telemetry.bp)
    c = app.test_client()

    status = c.get("/api/status").get_json()
    assert status["tpu"]["total"]["busy"] == 0.2
    assert status["tpu"]["cameras"]["a"]["per_s"] == 1.0

    tele = c.get("/api/telemetry/inference").get_json()
    assert tele["utilisation"]["total"]["count"] == 10
    assert tele["utilisation"]["cameras"]["a"]["mean_ms"] == 200.0
