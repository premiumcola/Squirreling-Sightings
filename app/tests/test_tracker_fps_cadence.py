"""The miss-grace is configured in seconds and enforced in ticks.

``compute_miss_grace_samples(seconds, fps)`` is the only bridge between
the two, so the ``fps`` handed to ``LiveTracker.step`` has to be the rate
at which the camera loop TICKS — one tracker step per iteration. Get that
number wrong and ``track_miss_grace_seconds`` stops meaning seconds:

* too LOW  → too few grace samples → tracks close early → fragmentation.
* too HIGH → too many → predicted ghost boxes linger long after the
  subject left.

The number used to be counted inside ``_rtsp_recording_step``, a strictly
smaller set of iterations than the loop's own: behind ``rtsp_url`` (a
snapshot camera never reaches it at all) and behind the recording-block
``continue`` (a camera with recording off, or outside its
``schedule_record`` window, skips it on exactly the frames that have
motion). A snapshot camera therefore never measured anything and ran on a
hard-coded 3.0 literal — at its real ~0.33 Hz cadence that is 9x too
high, and a 6 s grace became 54 s of ghost track.

These tests drive the real ``LoopCadenceMixin`` against a virtual clock,
step a real ``LiveTracker`` with what it produces, and assert on the one
number the operator can actually observe: how many WALL-CLOCK SECONDS a
track survives after its last detection.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# Same sys.path bootstrap the other tests in this folder use.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.camera_runtime import _cadence  # noqa: E402
from app.camera_runtime._cadence import LoopCadenceMixin, nominal_rate  # noqa: E402
from app.tracker_core import LiveTracker, compute_miss_grace_samples  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "app" / "camera_runtime"

# The operator's real numbers: track_miss_grace_seconds = 6.0 on all three
# cameras, measured main-loop cadence ~2.9 ticks/s on the RTSP ones.
GRACE_S = 6.0
RTSP_HZ = 2.9
RTSP_INTERVAL_S = 0.15  # frame_interval_ms = 150
# A snapshot-only camera loops on snapshot_interval_s (default 3 s).
SNAP_INTERVAL_S = 3.0
SNAP_HZ = 1.0 / SNAP_INTERVAL_S


@dataclass
class FakeDet:
    """associate_detections only reads .label / .score / .bbox."""

    label: str
    score: float
    bbox: tuple[int, int, int, int]


def _det() -> FakeDet:
    # Mid-frame on purpose: a box at the border would hit the K4 edge-grace
    # cap (EDGE_GRACE_SAMPLES) and mask the cadence math under test.
    return FakeDet("person", 0.80, (250, 180, 350, 300))


class _Clock:
    """Stands in for the ``time`` module inside ``_cadence``."""

    def __init__(self, t0: float = 1000.0):
        self.t = float(t0)

    def monotonic(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class _LoopSim(LoopCadenceMixin):
    """The camera loop reduced to the two statements this bug lives
    between: the cadence tick and the tracker step.

    Deliberately does NOT call ``_rtsp_recording_step`` — that models a
    snapshot camera, and equally a camera whose recording is blocked by
    ``recording_enabled=False`` or a closed ``schedule_record`` window.
    Both are loops that tick the tracker without ever reaching the
    recording step.
    """

    def __init__(self, clock: _Clock, *, tick_hz: float, interval_s: float):
        self._clock = clock
        self.tick_hz = float(tick_hz)
        self.interval_s = float(interval_s)
        # The three fields CameraRuntime.__init__ owns.
        self._main_fps: float = 0.0
        self._main_fps_frames: int = 0
        self._main_fps_window_start: float | None = None
        self._main_fps_last_tick: float | None = None
        self.tracker = LiveTracker("cam_sim", grace_seconds=GRACE_S)

    def tick(self, dets=()) -> float:
        self._clock.advance(1.0 / self.tick_hz)
        fps = self._tick_loop_cadence(self.interval_s)
        self.tracker.step(
            list(dets),
            t_s=self._clock.monotonic(),
            fps=fps,
            frame_w=640,
            frame_h=480,
        )
        return fps

    def run(self, seconds: float) -> None:
        for _ in range(max(1, int(round(seconds * self.tick_hz)))):
            self.tick()


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(_cadence, "time", c)
    return c


def _survival_seconds(sim: _LoopSim) -> float:
    """Wall-clock seconds a track outlives its last detection."""
    sim.tick([_det()])
    assert sim.tracker.active_count() == 1, "the fixture detection must spawn a track"
    misses = 0
    while sim.tracker.active_count() and misses < 2000:
        sim.tick()
        misses += 1
    return misses / sim.tick_hz


# ── The seconds→ticks contract ──────────────────────────────────────────────
def test_snapshot_camera_grace_stays_in_seconds(clock):
    """A snapshot camera ticks at ~0.33 Hz and never reaches the recording
    step. With the rate counted there it measured nothing at all and the
    tracker fell back to a 3.0 literal — 18 grace samples at 3 s each, so
    a 6 s grace kept a ghost track alive for 54 s."""
    sim = _LoopSim(clock, tick_hz=SNAP_HZ, interval_s=SNAP_INTERVAL_S)
    sim.run(seconds=60.0)
    assert sim._main_fps == pytest.approx(SNAP_HZ, rel=0.05)
    assert _survival_seconds(sim) == pytest.approx(GRACE_S, abs=1.6)


def test_rtsp_camera_grace_stays_in_seconds(clock):
    """The path that already worked must keep working: a 2.9 Hz loop
    resolves 6 s to 17 samples, which is 5.86 s of wall clock."""
    sim = _LoopSim(clock, tick_hz=RTSP_HZ, interval_s=RTSP_INTERVAL_S)
    sim.run(seconds=30.0)
    assert sim._main_fps == pytest.approx(RTSP_HZ, rel=0.05)
    assert _survival_seconds(sim) == pytest.approx(GRACE_S, abs=0.5)


def test_cadence_is_measured_without_the_recording_step(clock):
    """30 s of a camera that never reaches ``_rtsp_recording_step`` —
    recording off, or outside its schedule_record window. The loop still
    ticks the tracker, so the loop's rate must still be known."""
    sim = _LoopSim(clock, tick_hz=RTSP_HZ, interval_s=RTSP_INTERVAL_S)
    sim.run(seconds=30.0)
    assert sim._main_fps > 0.0, "a blocked recording must not blind the measurement"
    assert sim._main_fps == pytest.approx(RTSP_HZ, rel=0.05)


def test_measurement_is_unbiased(clock):
    """frames/elapsed must not count the tick that opened the window —
    an off-by-one there inflates the rate and with it the grace."""
    sim = _LoopSim(clock, tick_hz=10.0, interval_s=0.1)
    sim.run(seconds=40.0)
    assert sim._main_fps == pytest.approx(10.0, rel=0.02)


# ── Warm-up ────────────────────────────────────────────────────────────────
def test_cold_start_uses_the_configured_cadence(clock):
    """Before the second tick there is nothing to measure. The estimate
    must come from the camera's own configured interval, not from one
    literal that happens to suit RTSP cameras."""
    snap = _LoopSim(clock, tick_hz=SNAP_HZ, interval_s=SNAP_INTERVAL_S)
    assert snap.tick() == pytest.approx(SNAP_HZ, rel=0.01)
    rtsp = _LoopSim(_Clock(), tick_hz=RTSP_HZ, interval_s=RTSP_INTERVAL_S)
    assert rtsp.tick() == pytest.approx(1.0 / RTSP_INTERVAL_S, rel=0.01)


def test_warm_up_hands_over_to_the_measurement_within_a_second(clock):
    """The part-window rate takes over as soon as two ticks have landed,
    so the configured-cadence estimate covers a startup blip, not the
    whole first window."""
    sim = _LoopSim(clock, tick_hz=RTSP_HZ, interval_s=RTSP_INTERVAL_S)
    rates = [sim.tick() for _ in range(4)]
    assert rates[-1] == pytest.approx(RTSP_HZ, rel=0.05)


# ── Stalls ─────────────────────────────────────────────────────────────────
def test_a_reconnect_gap_is_not_averaged_into_the_rate(clock):
    """The loop ``continue``s past the tracker on a forced reconnect, so a
    30 s outage is dead time, not a slow cadence. Folding it into the
    window would publish ~0.2 Hz and collapse the grace to 2 ticks for the
    whole window that follows — right when the subject may still be
    there."""
    sim = _LoopSim(clock, tick_hz=RTSP_HZ, interval_s=RTSP_INTERVAL_S)
    sim.run(seconds=30.0)
    assert sim._main_fps == pytest.approx(RTSP_HZ, rel=0.05)
    clock.advance(30.0)  # capture wedged; no tracker ticks either
    sim.run(seconds=4.0)
    assert sim._main_fps == pytest.approx(RTSP_HZ, rel=0.05)
    sim.run(seconds=20.0)
    assert sim._main_fps == pytest.approx(RTSP_HZ, rel=0.05)


def test_a_slow_camera_is_not_mistaken_for_a_stall(clock):
    """Every tick of a 25 s snapshot camera is a 25 s gap. The stall guard
    is relative to the configured interval so it never fires there."""
    sim = _LoopSim(clock, tick_hz=0.04, interval_s=25.0)
    sim.run(seconds=600.0)
    assert sim._main_fps == pytest.approx(0.04, rel=0.1)


def test_nominal_rate_is_bounded():
    assert nominal_rate(0.0) > 0.0
    assert nominal_rate(-1.0) > 0.0
    assert nominal_rate(None) > 0.0
    assert nominal_rate(1e-9) <= 60.0


# ── The 1.0 Hz floor ───────────────────────────────────────────────────────
def test_sub_hertz_cadence_is_not_floored_to_one(clock):
    """``max(1.0, fps)`` rewrote every sub-1 Hz camera to 1 Hz, which at a
    real 0.33 Hz triples the grace. compute_miss_grace_samples already
    floors the SAMPLE count at 1, so the rate floor only ever distorted."""
    assert compute_miss_grace_samples(GRACE_S, SNAP_HZ) == 2
    assert compute_miss_grace_samples(GRACE_S, 1.0) == 6, "what the floor used to produce"
    sim = _LoopSim(clock, tick_hz=SNAP_HZ, interval_s=SNAP_INTERVAL_S)
    sim.run(seconds=60.0)
    assert sim._main_fps < 1.0


def test_a_slow_loop_still_reports_a_rate(clock):
    """Rounding to one decimal turned a 0.04 Hz camera into 0.0, i.e. into
    "never measured". Two decimals keep it a number."""
    sim = _LoopSim(clock, tick_hz=0.04, interval_s=25.0)
    sim.run(seconds=600.0)
    assert sim._main_fps > 0.0


# ── The measurement must not drift back to the recording step ──────────────
def test_recording_step_no_longer_owns_the_counter():
    src = (SRC / "_recording_step.py").read_text(encoding="utf-8")
    assert "_main_fps_frames" not in src, "counting here understates the loop's own rate"
    assert "_main_fps_window_start" not in src


def test_the_loop_asks_the_cadence_mixin():
    src = (SRC / "_main_loop.py").read_text(encoding="utf-8")
    assert "_tick_loop_cadence(interval)" in src
    assert "or 3.0" not in src, "no hard-coded cadence literal"
    assert 'max(1.0, float(getattr(self, "_main_fps"' not in src


def test_the_mixin_is_wired_into_the_runtime():
    """A cadence module nothing inherits from measures nothing."""
    from app.camera_runtime import CameraRuntime

    assert issubclass(CameraRuntime, LoopCadenceMixin)
    assert callable(getattr(CameraRuntime, "_tick_loop_cadence", None))
