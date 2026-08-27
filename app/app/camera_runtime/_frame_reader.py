"""Newest-frame-wins capture for RTSP handles.

``cv2.VideoCapture.read()`` hands back the NEXT frame in the decoder's
queue, never the newest one. A consumer slower than the camera therefore
walks an ever-growing backlog: every read decodes a frame that is one
step older than the last. The main loop consumes roughly one frame per
``frame_interval_ms`` (350 ms by default, plus inference) while the
camera pushes 15 fps, so the queue grows by ~12 frames a second and the
picture the pipeline analyses drifts minutes behind reality.

``cap.set(CAP_PROP_BUFFERSIZE, 1)`` does not help: the FFmpeg backend
has no setter for that property and silently ignores it (it works on
V4L2 / DShow / GStreamer only).

The fix is to decouple decoding from consuming. :class:`LatestFrameReader`
owns one thread that reads for as long as the stream delivers, which
keeps the queue empty, and publishes the most recent frame into a single
slot the consumer reads at its own pace. It is not a spin loop: with an
empty queue ``grab()`` blocks inside FFmpeg until the next packet
arrives, so the thread runs at the camera's frame rate and no faster.

The cost is decoding every frame instead of every fifth one. That is not
avoidable: an inter-coded stream cannot be fast-forwarded, so the only
way to hold a recent frame is to have decoded everything before it.

Two things fall out of that:

* the consumer always gets the newest frame, whatever its own cadence;
* the timestamp on that frame is the moment it came off the wire, which
  — with the queue provably empty — is a REAL capture age, unlike a
  stamp written whenever we happened to decode.

:attr:`LatestFrameReader.lag_s` covers the one case the drain cannot fix
on its own: a decoder that is CPU-starved falls behind even while
reading flat out, and then the arrival stamp lies again. Media-time vs
wall-time drift catches exactly that.
"""

from __future__ import annotations

import logging
import threading
import time

import cv2

log = logging.getLogger(__name__)

# Consecutive failed grabs before the reader declares the handle dead.
# One failure is a timeout blip on a busy network; three in a row is a
# stream that stopped.
GRAB_FAIL_LIMIT = 3

# Pause after a failed grab. A handle that fails instantly (released
# underneath us, EOF on a file) must not spin a core between the retries.
GRAB_FAIL_PAUSE_S = 0.05

# How long a consumer waits for a frame before treating the stream as
# broken. Matches rtsp_options.READ_TIMEOUT_MS so the failure surfaces on
# the same schedule as before this module existed, well inside the main
# loop's 20 s watchdog.
READ_TIMEOUT_S = 6.0

# How long ``release()`` waits for the reader thread. A thread parked in
# a blocking grab() can take up to READ_TIMEOUT_S to notice; blocking the
# main loop that long during a forced reconnect is worse than handing the
# close over to the reader itself.
RELEASE_JOIN_TIMEOUT_S = 1.5


class LatestFrameReader:
    """Thread that keeps one capture handle drained and publishes the
    most recent frame.

    The thread is the ONLY owner of the handle: nothing else may call
    grab / retrieve / release on it while the reader runs, because a
    ``release()`` racing an in-flight ``grab()`` segfaults libav on a
    corrupt HEVC stream (the reason the main loop's watchdog hands
    reconnects back to the loop instead of releasing directly).
    :class:`DrainedCapture` is what enforces that ownership.
    """

    def __init__(
        self,
        capture,
        camera_id: str,
        fail_limit: int = GRAB_FAIL_LIMIT,
    ):
        self._cap = capture
        self.camera_id = camera_id
        self._fail_limit = max(1, int(fail_limit))
        self._cond = threading.Condition()
        self._frame = None
        self._frame_ts: float = 0.0
        self._dead = False
        self._error: str = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Handle-close bookkeeping — see close_handle / request_close.
        self._close_lock = threading.Lock()
        self._closed = False
        self._close_requested = False
        # Media-vs-wall reference point for the lag estimate.
        self._media_ref_ms: float | None = None
        self._wall_ref: float = 0.0
        self._lag_s: float | None = None

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"cam-reader-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, join_timeout: float = RELEASE_JOIN_TIMEOUT_S) -> bool:
        """Ask the reader to exit. Returns True when the thread is gone.

        False means it is still parked in a blocking grab(); the caller
        must NOT touch the handle in that case.
        """
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        t = self._thread
        if t is None or not t.is_alive():
            return True
        t.join(timeout=max(0.0, float(join_timeout)))
        return not t.is_alive()

    @property
    def alive(self) -> bool:
        return not self._dead and not self._stop.is_set()

    @property
    def error(self) -> str:
        return self._error

    @property
    def lag_s(self) -> float | None:
        """Seconds the newest decoded frame is behind real time, or None
        when the backend reports no usable presentation timestamps."""
        return self._lag_s

    # ── handle ownership ─────────────────────────────────────────────
    def close_handle(self) -> None:
        """Release the underlying handle, exactly once, from whichever
        thread is safe to do it."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._cap.release()
        except Exception:  # noqa: BLE001 — a handle we are discarding anyway
            pass

    def request_close(self) -> None:
        """Hand the close over to the reader thread, for when it did not
        exit in time and releasing from here would race its grab()."""
        with self._close_lock:
            self._close_requested = True
        t = self._thread
        if t is None or not t.is_alive():
            # It exited between the failed join and now — nobody left to
            # run the deferred close, so do it here.
            self.close_handle()

    # ── consumer API ─────────────────────────────────────────────────
    def peek(self) -> tuple[object | None, float]:
        """Newest frame plus its arrival timestamp, without waiting."""
        with self._cond:
            return self._frame, self._frame_ts

    def wait_frame(
        self,
        newer_than: float = 0.0,
        timeout: float = READ_TIMEOUT_S,
    ) -> tuple[object | None, float]:
        """Block until the slot holds a frame newer than ``newer_than``.

        Returns ``(None, 0.0)`` on timeout or once the reader is dead, so
        the caller raises and the existing reconnect/backoff path runs.
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while True:
                if self._frame is not None and self._frame_ts > newer_than:
                    return self._frame, self._frame_ts
                if self._dead:
                    return None, 0.0
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, 0.0
                self._cond.wait(remaining)

    # ── internals ────────────────────────────────────────────────────
    def _mark_dead(self, reason: str) -> None:
        with self._cond:
            self._dead = True
            if reason:
                self._error = reason
            self._cond.notify_all()

    def _update_lag(self, now: float) -> None:
        """Track media-time vs wall-time drift = age of the newest frame.

        ``CAP_PROP_POS_MSEC`` is the presentation timestamp of the frame
        just decoded, and a camera stamps those at capture time. With a
        zero-backlog reference taken right after open,
        ``wall_elapsed - media_elapsed`` is how far behind live the
        decoder output has fallen — a real age, not a decode-time stamp.
        A source that re-bases its clock re-baselines the reference
        instead of reporting a nonsense negative lag.
        """
        try:
            pos_ms = float(self._cap.get(cv2.CAP_PROP_POS_MSEC))
        except Exception:  # noqa: BLE001 — property is optional per backend
            return
        if pos_ms <= 0:
            return
        if self._media_ref_ms is None or pos_ms < self._media_ref_ms:
            self._media_ref_ms = pos_ms
            self._wall_ref = now
            self._lag_s = 0.0
            return
        media_elapsed = (pos_ms - self._media_ref_ms) / 1000.0
        self._lag_s = max(0.0, (now - self._wall_ref) - media_elapsed)

    def _run(self) -> None:
        fails = 0
        try:
            while not self._stop.is_set():
                try:
                    ok = bool(self._cap.grab())
                except Exception as exc:  # noqa: BLE001 — handle may die anytime
                    ok = False
                    self._error = f"{type(exc).__name__}: {exc}"
                if not ok:
                    fails += 1
                    if fails >= self._fail_limit:
                        self._mark_dead(self._error or "grab() failed")
                        return
                    if self._stop.wait(GRAB_FAIL_PAUSE_S):
                        break
                    continue
                fails = 0
                self._error = ""
                now = time.time()
                self._update_lag(now)
                # Every grabbed frame is converted. Rate-limiting the
                # retrieve to save the sws_scale looks tempting, but then
                # a burst arriving inside one interval leaves the slot
                # holding a frame from the START of that burst — which is
                # the bug this module exists to remove, in miniature.
                try:
                    ok2, frame = self._cap.retrieve()
                except Exception:  # noqa: BLE001 — same, never fatal
                    ok2, frame = False, None
                if not ok2 or frame is None:
                    continue
                with self._cond:
                    self._frame = frame
                    self._frame_ts = now
                    self._cond.notify_all()
        finally:
            self._mark_dead(self._error or "stopped")
            with self._close_lock:
                deferred = self._close_requested
            if deferred:
                self.close_handle()


class DrainedCapture:
    """``cv2.VideoCapture`` façade whose frames are always the newest.

    Wraps a real handle plus its :class:`LatestFrameReader` and exposes
    the slice of the cv2 API the runtime uses, so existing call sites
    keep working unchanged — including the forced-reconnect
    ``self.capture.release()`` in ``camera_runtime/_main_loop``, which
    now joins the reader BEFORE the handle dies instead of pulling it out
    from under an in-flight grab().
    """

    def __init__(
        self,
        capture,
        camera_id: str,
        read_timeout_s: float = READ_TIMEOUT_S,
        release_join_timeout_s: float = RELEASE_JOIN_TIMEOUT_S,
        **reader_kwargs,
    ):
        self._cap = capture
        self.camera_id = camera_id
        self.read_timeout_s = float(read_timeout_s)
        self._release_join_timeout = float(release_join_timeout_s)
        self.reader = LatestFrameReader(capture, camera_id, **reader_kwargs)
        self._released = False
        self.reader.start()

    # cv2 spells these in camelCase; keep the names so the façade is a
    # drop-in for the call sites that already exist.
    def isOpened(self) -> bool:  # noqa: N802 — cv2 API name
        if self._released or not self.reader.alive:
            return False
        try:
            return bool(self._cap.isOpened())
        except Exception:  # noqa: BLE001
            return False

    def read(self, newer_than: float = 0.0, timeout: float | None = None):
        ok, frame, _ts = self.read_latest(newer_than=newer_than, timeout=timeout)
        return ok, frame

    def read_latest(self, newer_than: float = 0.0, timeout: float | None = None):
        """``(ok, frame, arrival_ts)`` for the newest available frame."""
        wait_s = self.read_timeout_s if timeout is None else float(timeout)
        frame, ts = self.reader.wait_frame(newer_than=newer_than, timeout=wait_s)
        if frame is None:
            return False, None, 0.0
        return True, frame, ts

    def peek(self) -> tuple[object | None, float]:
        return self.reader.peek()

    @property
    def lag_s(self) -> float | None:
        return self.reader.lag_s

    def release(self) -> None:
        self._released = True
        if self.reader.stop(join_timeout=self._release_join_timeout):
            self.reader.close_handle()
        else:
            # Still inside a blocking grab(). Releasing from here would
            # pull the handle out from under libav mid-decode, so the
            # reader closes it itself as soon as grab() returns.
            log.debug(
                "[cam:%s] reader still in grab(), deferring handle close",
                self.camera_id,
            )
            self.reader.request_close()
