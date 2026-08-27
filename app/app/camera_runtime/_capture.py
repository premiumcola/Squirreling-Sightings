from __future__ import annotations

import contextlib

# ruff: noqa: F401
# Comprehensive import block — some symbols are unused in this mixin
# but kept for parity so methods can be moved between mixins without
# import bookkeeping. Trim later if a mixin grows enough to warrant it.
import json as _json_mod
import logging
import shutil as _shutil
import subprocess as _subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests

from ..detection_confirmer import DetectionConfirmer
from ..detectors import (
    BirdSpeciesClassifier,
    CoralObjectDetector,
    Detection,
    WildlifeClassifier,
    draw_detections,
)
from ..event_logic import (
    choose_alarm_level,
    compute_severity_from_matrix,
    is_schedule_window_active,
    schedule_action_active,
)
from ..rtsp_options import capture_options, timeout_params
from ._consts import (
    _FFMPEG_AVAILABLE,
    _PROFILE_PERIOD_DEFAULTS,
    _PROFILES,
    _SPECIES_TO_ACH_ID,
    _WILDLIFE_BBOX_DONORS,
    _bbox_iou,
    _refine_wildlife_bbox,
    _suppress_overlap,
    log,
    log_cam,
    log_tl,
)
from ._frame_reader import DrainedCapture

# How far behind live the decoder may fall before the stream gets
# dropped and reopened. The reader keeps the decode queue empty, so a lag
# this large means decoding itself cannot keep up — and an inter-coded
# stream cannot be fast-forwarded, so reading harder never recovers it.
# Reopening snaps straight back to live.
_LAG_RECONNECT_S = 5.0

# Minimum gap between two lag-triggered reconnects, so a camera that is
# permanently too expensive to decode does not reconnect-loop.
_LAG_RECONNECT_COOLDOWN_S = 30.0

# Wait for a replacement after discarding a pink frame. A pink frame
# proves the stream IS delivering, so the full read timeout would only
# stall the loop; the next frame is one frame-interval away.
_PINK_RETRY_TIMEOUT_S = 1.0


class CaptureMixin:
    """RTSP open/grab + frame validity guards + sub-stream preview loop.

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (frame buffers, lock, config, etc.) which live on the concrete class.

    Both streams are drained by a thread of their own so what the
    pipeline analyses is always the CURRENT scene: the main stream via
    :class:`DrainedCapture`, the sub-stream via :meth:`_preview_loop`.
    Without that, ``read()`` walks a FIFO backlog and the picture drifts
    minutes behind reality — see :mod:`._frame_reader`.
    """

    @staticmethod
    def _sub_stream_url(url: str) -> str | None:
        """Derive H.264 sub-stream URL from main-stream URL.
        Handles both Reolink H.264 and H.265 main streams:
          - h264Preview_01_main → h264Preview_01_sub (RLC-810A, older firmware)
          - h265Preview_01_main → h264Preview_01_sub (CX810, newer firmware — H.265 on main, H.264 on sub)
        """
        if "/h264Preview_01_main" in url:
            return url.replace("/h264Preview_01_main", "/h264Preview_01_sub")
        if "/h265Preview_01_main" in url:
            # Newer Reolink cameras (CX810 etc.) use H.265 on main stream.
            # Sub-stream is always H.264 regardless of main-stream codec.
            return url.replace("/h265Preview_01_main", "/h264Preview_01_sub")
        return None

    def _open_capture(self):
        src = self.cfg.get("rtsp_url") or self.cfg.get("snapshot_url")
        if not src:
            raise RuntimeError(f"Kamera {self.camera_id}: keine Quelle gesetzt")
        if self.cfg.get("rtsp_url"):
            import os

            rtsp_url = self.cfg["rtsp_url"]

            # ── Main stream: motion detection + event snapshots ──────────────
            # TCP + software decode to prevent H.265 tile-split pink artifact.
            #
            # Open/read timeouts ride the constructor's params vector, not
            # cap.set() — the FFmpeg backend ignores those properties after
            # construction, which used to leave a dead stream blocking
            # read() for the backend's 30 s default while the 20 s watchdog
            # fired uselessly. See rtsp_options for the full story.
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = capture_options(extra="hwaccel;none")
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, timeout_params())
            _RES_MAP = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
            _res = self.cfg.get("resolution", "auto")
            if _res in _RES_MAP:
                _w, _h = _RES_MAP[_res]
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, _w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _h)
            if not cap.isOpened():
                with contextlib.suppress(Exception):
                    cap.release()
                raise RuntimeError(f"Kamera {self.camera_id}: RTSP konnte nicht geöffnet werden")
            # Retire the previous handle first — _grab_frame reopens on
            # `not isOpened()` without releasing, which leaked one FFmpeg
            # context per reconnect.
            self._close_capture()
            # Newest-frame-wins. A bare handle returns the OLDEST queued
            # frame, and CAP_PROP_BUFFERSIZE is silently ignored by the
            # FFmpeg backend, so a consumer slower than the camera walks
            # an ever-growing backlog. See _frame_reader.
            self.capture = DrainedCapture(cap, self.camera_id)
            # Mark the RTSP-open moment so the [cam:<id>] RTSP opened line
            # can include the first-frame latency. Picked up by _loop()
            # the next time a fresh frame is decoded.
            self._rtsp_opened_at = time.time()
            self._rtsp_first_frame_logged = False

            # ── Sub-stream: H.264 preview for dashboard (no pink) ────────────
            # Opened under _preview_cap_lock so _preview_loop sees a consistent handle.
            sub_url = self._sub_stream_url(rtsp_url)
            if sub_url:
                try:
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = capture_options()
                    # No BUFFERSIZE call here either — it is a no-op on the
                    # FFmpeg backend. The sub-stream stays current because
                    # _preview_loop below reads it on its own thread as fast
                    # as it arrives, which is the same drain the main stream
                    # gets from DrainedCapture.
                    pcap = cv2.VideoCapture(sub_url, cv2.CAP_FFMPEG, timeout_params())
                    with self._preview_cap_lock:
                        old = self.preview_cap
                        if pcap.isOpened():
                            self.preview_cap = pcap
                            log_cam.info(
                                "[%s] Sub-stream opened for preview: %s",
                                self.camera_id,
                                self._masked_rtsp_url(sub_url),
                            )
                        else:
                            pcap.release()
                            self.preview_cap = None
                    # Release old handle outside the lock to avoid blocking _preview_loop
                    if old is not None:
                        with contextlib.suppress(Exception):
                            old.release()
                except Exception as e:
                    log_cam.warning("[%s] Sub-stream open failed: %s", self.camera_id, e)
                    with self._preview_cap_lock:
                        self.preview_cap = None

            self.connect_time = time.time()
            self.prev_gray = None  # reset motion state on reconnect
        else:
            # Snapshot (HTTP) camera: no handle to drain, and any handle
            # left over from an earlier RTSP config must not keep a
            # reader thread alive.
            self._close_capture()

    def _preview_loop(self):
        """Dedicated thread: sole reader of self.preview_cap (sub-stream).
        Stores clean frames into self._preview_frame under self.lock.
        No other thread touches preview_cap or _preview_frame directly.
        """
        while self.running:
            with self._preview_cap_lock:
                cap = self.preview_cap
            if cap is None:
                time.sleep(0.5)
                continue
            try:
                with self._preview_cap_lock:
                    # Re-check under lock: cap may have been replaced during reconnect
                    cap = self.preview_cap
                    if cap is None or not cap.isOpened():
                        time.sleep(0.2)
                        continue
                    ok, frame = cap.read()
                if ok and frame is not None:
                    r = float(frame[:, :, 2].mean())
                    b = float(frame[:, :, 0].mean())
                    if not (r > b * 2.5 and r > 150):  # skip pink/artifact frames
                        h, w = frame.shape[:2]
                        self._preview_resolution = f"{w}×{h}"
                        with self.lock:
                            self._preview_frame = frame
                            # C41 · mirror of frame_ts on the main path.
                            # Read by routes/coral_test_detection to gate
                            # the sub-stream tier on freshness.
                            self._preview_frame_ts = time.time()
                        # Wetter-Sichtungen prebuffer hook — only spends CPU
                        # on JPEG encoding when a WeatherService has actually
                        # attached a buffer to this camera.
                        if self.weather_prebuffer is not None:
                            self.weather_prebuffer.push(frame)
                        # Measure sub-stream FPS over a rolling 5s window
                        self._preview_fps_frames += 1
                        elapsed = time.time() - self._preview_fps_window_start
                        if elapsed >= 5.0:
                            self._preview_fps = round(self._preview_fps_frames / elapsed, 1)
                            self._preview_fps_frames = 0
                            self._preview_fps_window_start = time.time()
            except Exception:
                time.sleep(0.2)

    def _close_capture(self) -> None:
        """Retire the current main-stream handle, if any."""
        cap = self.capture
        self.capture = None
        if cap is None:
            return
        with contextlib.suppress(Exception):
            cap.release()

    def _note_capture_age(self, captured_ts: float) -> None:
        """Record when the frame we are about to return arrived.

        ``self.frame_ts`` is stamped by the main loop when the frame is
        DECODED, so a minutes-old picture carries a fresh timestamp and
        every freshness check built on it passes. This is the honest
        number: the wall-clock moment the frame came off the wire, with
        the decode queue provably empty behind it.
        """
        with self.lock:
            self._frame_capture_ts = float(captured_ts)
        lag = self.capture_lag_s()
        if lag is not None and lag > _LAG_RECONNECT_S:
            self._request_lag_reconnect(lag)

    def _request_lag_reconnect(self, lag_s: float) -> None:
        """Ask the main loop to reopen a stream that fell behind live."""
        now = time.time()
        if now - getattr(self, "_lag_reconnect_ts", 0.0) < _LAG_RECONNECT_COOLDOWN_S:
            return
        self._lag_reconnect_ts = now
        log_cam.warning(
            "[cam:%s] decoder %.1fs behind live — forcing reconnect",
            self.camera_id,
            lag_s,
        )
        self._force_reconnect = True

    def capture_lag_s(self) -> float | None:
        """Seconds the decoder output trails real time, or None when the
        backend reports no usable presentation timestamps."""
        cap = self.capture
        return cap.lag_s if isinstance(cap, DrainedCapture) else None

    def latest_main_frame(self):
        """``(frame, arrival_ts)`` for the newest main-stream frame.

        Served straight from the reader slot, so a caller that only wants
        to LOOK at the scene is not held to the main loop's
        frame_interval cadence. Snapshot (HTTP) cameras have no reader
        and fall back to the last stored frame.
        """
        cap = self.capture
        if isinstance(cap, DrainedCapture):
            frame, ts = cap.peek()
            if frame is not None:
                return frame, ts
        with self.lock:
            ts = float(getattr(self, "_frame_capture_ts", 0.0) or 0.0)
            return self.frame, (ts or float(self.frame_ts or 0.0))

    def _grab_frame(self):
        if self.cfg.get("rtsp_url"):
            if self.capture is None or not self.capture.isOpened():
                self._open_capture()
            # newer_than pins this to a frame we have not served before.
            # Without it a stream that went quiet would keep handing the
            # same frame back, every grab would look successful, and the
            # main loop's 20 s silence watchdog would never fire.
            ok, frame, ts = self.capture.read_latest(
                newer_than=getattr(self, "_frame_capture_ts", 0.0)
            )
            if not ok or frame is None:
                raise RuntimeError(f"Kamera {self.camera_id}: Frame lesen fehlgeschlagen")
            # Reject H.265 pink/magenta corruption frames (hardware decode artifact)
            r = float(frame[:, :, 2].mean())
            b = float(frame[:, :, 0].mean())
            if r > b * 2.5 and r > 150:
                log.debug("[%s] Pink frame discarded (R=%.0f B=%.0f)", self.camera_id, r, b)
                for _ in range(3):
                    # newer_than pins each retry to a frame the reader has
                    # not served yet — without it the slot would hand back
                    # the same pink frame three times.
                    ok2, frame2, ts2 = self.capture.read_latest(
                        newer_than=ts, timeout=_PINK_RETRY_TIMEOUT_S
                    )
                    if ok2 and frame2 is not None:
                        ts = ts2
                        r2 = float(frame2[:, :, 2].mean())
                        b2 = float(frame2[:, :, 0].mean())
                        if not (r2 > b2 * 2.5 and r2 > 150):
                            self._note_capture_age(ts2)
                            return frame2
                raise RuntimeError(
                    f"Kamera {self.camera_id}: Frame nach Pink-Discard fehlgeschlagen"
                )
            self._note_capture_age(ts)
            return frame
        url = self.cfg.get("snapshot_url")
        auth = None
        if self.cfg.get("username") and self.cfg.get("password"):
            auth = (self.cfg.get("username"), self.cfg.get("password"))
        resp = requests.get(url, auth=auth, timeout=8)
        resp.raise_for_status()
        frame = cv2.imdecode(np.frombuffer(resp.content, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"Kamera {self.camera_id}: Snapshot lesen fehlgeschlagen")
        self._note_capture_age(time.time())
        return frame

    def _is_frame_valid(self, frame) -> bool:
        """Reject corrupt, uniform-gray, white, pink-artifact, or near-black frames.
        Also rejects frames with large solid-color quadrants (RTSP corruption pattern)
        and frames with JPEG block artifacts (abnormally uniform 8×8 blocks).
        False-positive analysis: cam-Werkstatt.rechts.oben fires heavily during cloud/sun
        transitions and whenever H.265 decode produces solid magenta quadrants — both
        pass the simple channel-mean test but fail quadrant-HSV and block-variance checks."""
        if frame is None or frame.size == 0:
            return False
        h, w = frame.shape[:2]
        if w < 64 or h < 48:
            return False
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean_val = float(np.mean(gray))
        if mean_val < 8 or mean_val > 250:
            return False
        b_ch, g_ch, r_ch = cv2.split(frame)
        mean_r = float(r_ch.mean())
        mean_g = float(g_ch.mean())
        # Reject H.265 pink/magenta corruption: dominant red channel + low green/blue
        if mean_r > 180 and mean_r > mean_g * 2:
            return False
        # Reject frames where >40% of pixels are R≈G≈B (uniform gray/white)
        uniform = np.sum(
            (np.abs(r_ch.astype(np.int16) - g_ch.astype(np.int16)) < 10)
            & (np.abs(r_ch.astype(np.int16) - b_ch.astype(np.int16)) < 10)
        )
        if uniform > 0.4 * h * w:
            return False
        # Quadrant solid-color check: reject if any quadrant is >60% high-saturation
        # pink/magenta (H=135–165 in OpenCV's 0–179 scale, which maps 270–330°)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hh, hw = h // 2, w // 2
        for qy, qx in [(0, 0), (0, hw), (hh, 0), (hh, hw)]:
            q = hsv[qy : qy + hh, qx : qx + hw]
            q_h, q_s, q_v = q[:, :, 0], q[:, :, 1], q[:, :, 2]
            vivid = (q_s > 178) & (q_v > 127)
            pink = vivid & (q_h >= 135) & (q_h <= 165)
            qpix = hh * hw
            if qpix > 0 and float(np.sum(pink)) / qpix > 0.60:
                log.debug(
                    "[%s] Corrupt quadrant (pink/magenta >60%%), frame rejected", self.camera_id
                )
                return False
        # JPEG block-artifact check: if >50% of sampled 8×8 blocks have near-zero
        # variance the image is a solid-fill decode artifact, not a real scene.
        bs = 8
        low_var = 0
        total_blocks = 0
        for by in range(0, h - bs, bs * 3):
            for bx in range(0, w - bs, bs * 3):
                blk = gray[by : by + bs, bx : bx + bs]
                if float(np.var(blk)) < 2.0:
                    low_var += 1
                total_blocks += 1
        if total_blocks > 0 and low_var > total_blocks * 0.50:
            log.debug(
                "[%s] Block-artifact frame rejected (%d/%d uniform blocks)",
                self.camera_id,
                low_var,
                total_blocks,
            )
            return False
        return True

    def _is_frame_too_different(self, frame, prev_frame) -> bool:
        """Return True if mean absolute difference vs previous frame exceeds 60 (glitch/corrupt)."""
        if prev_frame is None or frame.shape != prev_frame.shape:
            return False
        mad = float(np.mean(np.abs(frame.astype(np.int16) - prev_frame.astype(np.int16))))
        return mad > 60

    @staticmethod
    def _has_corrupt_strip(frame, strip_height: int = 60) -> bool:
        """Thin forwarder to :func:`frame_helpers.has_corrupt_strip`. Kept
        as a class member so the existing mixin call sites (and tests
        that reach in via ``CaptureMixin._has_corrupt_strip``) stay
        bit-identical; the implementation lives in frame_helpers so the
        test-detection route can call the same heuristic without
        instantiating the runtime class."""
        from ..frame_helpers import has_corrupt_strip as _has

        return _has(frame, strip_height=strip_height)
