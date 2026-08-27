"""The capture path must hand out the NEWEST frame, never the oldest.

``cv2.VideoCapture.read()`` pops the decoder's FIFO. The main loop
consumes ~3 frames/s while the camera pushes 15, so before this the
queue grew by ~12 frames a second and the pipeline analysed a picture
that fell further behind every iteration — the reported symptom being a
simulation that replayed a walk-past minutes after it happened, frame by
frame in order.

``FakeCapture`` below is that FIFO: ``grab()`` pops the oldest queued
frame, ``retrieve()`` returns whatever was grabbed last, and ``read()``
is the two together — exactly the semantics that produce the bug. Every
test here fails against the pre-fix code:

* the drain tests, because the old ``_grab_frame`` returned frame 0 of
  100 queued;
* the teardown test, because no reader thread existed to leak;
* the age test, because nothing recorded when a frame arrived.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from app.camera_runtime._capture import CaptureMixin
from app.camera_runtime._frame_reader import DrainedCapture, LatestFrameReader

CAM = "reolink_cx810_werkstatt_172"

# Bounds every wait in this file so a regression fails instead of hanging.
DEADLINE_S = 5.0


def _frame(marker: int):
    """8x8 BGR frame whose every pixel encodes its sequence number."""
    return np.full((8, 8, 3), marker % 256, dtype=np.uint8)


def _marker(frame) -> int:
    return int(frame[0, 0, 0])


class FakeCapture:
    """A decoder queue with the same FIFO semantics as a real handle."""

    def __init__(self, frames=(), stall_timeout_s: float = 2.0):
        self._queue = list(frames)
        self._cond = threading.Condition()
        self._grabbed = None
        self._stall_timeout = stall_timeout_s
        self.grabs = 0
        self.retrieves = 0
        self.released = False
        self.die_after: int | None = None
        # Media clock, 15 fps. Advanced per grab so a consumer that keeps
        # up sees media time track wall time.
        self.pos_ms = 0.0
        self.media_step_ms = 1000.0 / 15.0

    # ── producer side (the camera) ───────────────────────────────────
    def push(self, *frames):
        with self._cond:
            self._queue.extend(frames)
            self._cond.notify_all()

    @property
    def queued(self) -> int:
        with self._cond:
            return len(self._queue)

    # ── cv2.VideoCapture surface ─────────────────────────────────────
    def grab(self) -> bool:
        with self._cond:
            if self.die_after is not None and self.grabs >= self.die_after:
                return False
            if not self._queue and not self._cond.wait(self._stall_timeout):
                return False  # stalled stream: nothing arrived in time
            if not self._queue:
                return False
            self._grabbed = self._queue.pop(0)
            self.grabs += 1
            self.pos_ms += self.media_step_ms
            return True

    def retrieve(self):
        self.retrieves += 1
        if self._grabbed is None:
            return False, None
        return True, self._grabbed

    def read(self):
        if not self.grab():
            return False, None
        return self.retrieve()

    def get(self, _prop):
        return self.pos_ms

    def isOpened(self) -> bool:
        return not self.released

    def release(self):
        self.released = True
        with self._cond:
            self._cond.notify_all()


class _Runtime(CaptureMixin):
    """Smallest object CaptureMixin's grab path touches."""

    def __init__(self, capture=None, rtsp: bool = True):
        self.camera_id = CAM
        self.capture = capture
        self.lock = threading.Lock()
        self.frame = None
        self.frame_ts = 0.0
        self.running = True
        self._force_reconnect = False
        self.reopen_calls = 0
        self._cfg = {"rtsp_url": "rtsp://cam.lan/h265Preview_01_main"} if rtsp else {}

    @property
    def cfg(self):
        return self._cfg

    def _open_capture(self):
        """Hermetic stand-in: count the reconnect the real one would do.

        A dead reader must send _grab_frame back through _open_capture —
        that is the existing recovery path — and no test here may touch
        a network.
        """
        self.reopen_calls += 1
        raise RuntimeError(f"Kamera {self.camera_id}: RTSP konnte nicht geöffnet werden")


def _wait_until(predicate, timeout: float = DEADLINE_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def drained():
    """DrainedCapture factory that always tears its reader down."""
    made: list[DrainedCapture] = []

    def _make(fake: FakeCapture, **kw) -> DrainedCapture:
        # Short join at teardown: a reader parked in a blocking grab
        # hands its close over rather than holding the suite up.
        kw.setdefault("release_join_timeout_s", 0.05)
        cap = DrainedCapture(fake, CAM, **kw)
        made.append(cap)
        return cap

    yield _make
    for cap in made:
        cap.release()


# ── the bug ──────────────────────────────────────────────────────────
def test_a_bare_read_serves_the_oldest_frame():
    """Pin the behaviour every other test here is measured against, and
    with it the fake's fidelity to cv2: one read of a 100-deep queue
    returns frame 0. That is what the old capture path did on every
    iteration, which is why the picture fell further behind each time."""
    fake = FakeCapture(_frame(i) for i in range(100))

    ok, frame = fake.read()

    assert ok and _marker(frame) == 0
    assert fake.queued == 99, "a read consumes one frame, it does not skip ahead"


def test_grab_frame_returns_newest_not_oldest(drained):
    """100 frames queued, consumer asks once: it must get frame 99."""
    fake = FakeCapture(_frame(i) for i in range(100))
    rt = _Runtime(capture=drained(fake))

    assert _wait_until(lambda: fake.queued == 0), "reader never drained the queue"
    frame = rt._grab_frame()

    assert _marker(frame) == 99, "consumer was served a frame from the backlog"
    assert fake.grabs == 100, "the whole queue must be decoded, not skipped over"


def test_backlog_does_not_grow_across_iterations(drained):
    """Producer 5x faster than the consumer: the gap must not accumulate."""
    fake = FakeCapture()
    rt = _Runtime(capture=drained(fake))
    seq = 0
    seen = []
    for _ in range(4):
        fake.push(*[_frame(seq + i) for i in range(5)])
        seq += 5
        assert _wait_until(lambda: fake.queued == 0)
        seen.append(_marker(rt._grab_frame()))

    assert seen == [4, 9, 14, 19], f"consumer fell behind the producer: {seen}"


def test_slot_holds_the_newest_frame_of_a_burst(drained):
    """A burst arriving between two consumer polls must leave the NEWEST
    of it in the slot. Rate-limiting the colour conversion would leave
    the first frame of the burst there instead — the same bug in
    miniature."""
    fake = FakeCapture()
    cap = drained(fake)
    fake.push(*[_frame(i) for i in range(30)])

    assert _wait_until(lambda: fake.queued == 0)
    assert _marker(cap.peek()[0]) == 29


# ── failure modes ────────────────────────────────────────────────────
def test_stalled_stream_times_out_instead_of_serving_stale(drained):
    """A stream that goes quiet must surface as a read failure — never
    as the last frame handed out a second time — so the main loop's
    existing backoff/reconnect path runs."""
    fake = FakeCapture([_frame(7)])
    cap = drained(fake, read_timeout_s=0.2)
    rt = _Runtime(capture=cap)

    assert _marker(rt._grab_frame()) == 7
    assert cap.reader.alive, "a quiet stream is not a dead one"

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="Frame lesen fehlgeschlagen"):
        rt._grab_frame()
    assert time.monotonic() - started < DEADLINE_S, "read blocked past its timeout"
    assert rt.reopen_calls == 0, "a quiet stream must not force a reconnect"


def test_stream_dying_mid_drain_kills_the_reader(drained):
    """Handle dies halfway through the queue: no spin, no hang, and the
    capture reports itself closed so _grab_frame reconnects."""
    fake = FakeCapture((_frame(i) for i in range(50)), stall_timeout_s=0.01)
    fake.die_after = 20
    cap = drained(fake)
    rt = _Runtime(capture=cap)

    assert _wait_until(lambda: not cap.reader.alive)
    assert fake.grabs == 20
    assert cap.isOpened() is False
    with pytest.raises(RuntimeError):
        rt._grab_frame()
    assert rt.reopen_calls == 1, "a dead reader must route back through _open_capture"


def test_no_reader_thread_survives_teardown():
    """Every reader must be gone once the capture is released."""
    before = {t.name for t in threading.enumerate()}
    caps = [
        DrainedCapture(FakeCapture([_frame(1)], stall_timeout_s=0.2), f"{CAM}_{i}")
        for i in range(3)
    ]
    assert _wait_until(
        lambda: sum(1 for t in threading.enumerate() if t.name.startswith("cam-reader-")) == 3
    )

    for cap in caps:
        cap.release()

    assert _wait_until(
        lambda: not [t for t in threading.enumerate() if t.name.startswith("cam-reader-")]
    ), "reader thread outlived its capture"
    assert {t.name for t in threading.enumerate()} <= before | {
        t.name for t in threading.enumerate()
    }
    assert all(c._cap.released for c in caps), "underlying handle was never released"


def test_release_defers_close_when_reader_is_blocked():
    """release() must never pull the handle out from under an in-flight
    grab() — that segfaults libav on a corrupt HEVC stream. It hands the
    close to the reader instead."""
    fake = FakeCapture(stall_timeout_s=0.6)
    cap = DrainedCapture(fake, CAM, release_join_timeout_s=0.05)
    assert _wait_until(lambda: fake.grabs == 0 and cap.reader.alive)

    cap.release()
    assert fake.released is False, "handle released while grab() was in flight"
    assert _wait_until(lambda: fake.released, timeout=DEADLINE_S), "deferred close never ran"


# ── the age signal ───────────────────────────────────────────────────
def test_capture_age_is_arrival_time_not_decode_time(drained):
    """_frame_capture_ts must date the frame's arrival. The main loop's
    frame_ts is written when the frame is decoded, which is why a
    minutes-old picture used to carry a fresh timestamp."""
    fake = FakeCapture([_frame(3)])
    rt = _Runtime(capture=drained(fake))
    assert _wait_until(lambda: fake.queued == 0)
    arrived_at = time.time()

    time.sleep(0.15)
    rt._grab_frame()

    captured_ts = rt._frame_capture_ts
    assert captured_ts == pytest.approx(arrived_at, abs=0.1)
    assert time.time() - captured_ts >= 0.15, "age collapsed to the moment of consumption"


def test_lag_tracks_media_versus_wall_clock():
    """A decoder that cannot keep up delivers old pixels that still
    arrive 'just now'. Media-vs-wall drift is what catches that."""
    fake = FakeCapture()
    reader = LatestFrameReader(fake, CAM)
    now = time.time()
    # Reference point, then 3 s of wall time against 1 s of media time.
    fake.pos_ms = 1000.0
    reader._update_lag(now)
    fake.pos_ms = 2000.0
    reader._update_lag(now + 3.0)

    assert reader.lag_s == pytest.approx(2.0, abs=0.01)

    # Draining the backlog: media time runs ahead of wall time again.
    fake.pos_ms = 5000.0
    reader._update_lag(now + 4.0)
    assert reader.lag_s == pytest.approx(0.0, abs=0.01)


def test_lag_beyond_threshold_requests_a_reconnect(drained, monkeypatch):
    """No amount of reading recovers a decoder that has fallen seconds
    behind — an inter-coded stream cannot be fast-forwarded. Reopening
    is the only way back to live, via the existing _force_reconnect."""
    import app.camera_runtime._capture as capture_mod

    monkeypatch.setattr(capture_mod, "_LAG_RECONNECT_S", 1.0)
    fake = FakeCapture([_frame(1)])
    cap = drained(fake)
    rt = _Runtime(capture=cap)
    assert _wait_until(lambda: fake.queued == 0)

    cap.reader._lag_s = 4.0
    rt._grab_frame()

    assert rt._force_reconnect is True
