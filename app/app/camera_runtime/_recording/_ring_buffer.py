"""A continuous, stream-copy-only rolling buffer of each camera's raw RTSP
feed — real footage for the pre-roll splice, replacing the ~3 fps
motion-analysis stills `_preroll.py` used until now.

WHY THIS EXISTS. `_preroll.py`'s own docstring already measured and
documented the old approach's cost: the spliced pre-roll plays back at
the analysis loop's tick rate (~2.86 Hz, `frame_interval_ms: 350` by
default), not the camera's native 15-25 fps — a hard, visible frame-rate
step at the splice boundary. The rejected fix on record was "decode the
main stream continuously at full fps just to keep a smooth pre-roll ring"
— real per-frame CPU cost, permanently, per camera. That is NOT what this
module does. A stream copy touches no pixel: ffmpeg remuxes already-
compressed packets from the RTSP feed straight to disk, the same
operation `_ffmpeg_clip.py::_start_ffmpeg_recording` already performs for
every triggered clip. The cost of running one more of those continuously
is a remux, not a decode.

CONNECTION COUNT, MEASURED AGAINST WHAT ALREADY RUNS. `_capture.py`
already holds two concurrent RTSP connections per camera at all times —
the decoded main stream (`self.capture`) for motion analysis and the
decoded sub-stream (`self.preview_cap`) for the dashboard preview — and
`_start_ffmpeg_recording` opens a THIRD, fresh, on every single motion
trigger. Three concurrent sessions per camera is already normal
operation today, briefly, on every event. This module keeps a third
connection open continuously instead of opening a fourth on top — the
steady-state count goes from "2, spiking to 3" to "3, always" rather than
"2, spiking to 4".

SEGMENTS, NOT ONE GROWING FILE. ffmpeg's `-f segment` muxer with `-c
copy` cannot cut mid-GOP without decoding, so each segment boundary
snaps forward to the camera's own next keyframe — an interval this
codebase does not configure and has never measured (Reolink firmware
picks it). `_SEGMENT_TIME_S` is a REQUEST; real segments are never
shorter, sometimes longer. `_RING_SECONDS` is sized generously over any
configured pre-roll window specifically to absorb that overshoot — if a
camera's GOP is unusually long, the buffer still holds enough whole
segments to cover the requested pre-roll, just as fewer, larger files.

Segments are named by their own start time (`-strftime 1`, `%s.mp4` —
Unix epoch seconds) so `segments_covering()` can select by wall-clock
time from the directory listing alone, with no separate index to keep in
sync. A lightweight janitor thread deletes anything older than the ring
window; there is no ffmpeg-side auto-delete for strftime-named segments
to lean on.

FAILS OPEN. Every public entry point here degrades to "no ring segments
available" (empty list, or simply not starting) rather than raising —
`_preroll.py` already has a complete, working fallback (the stills-based
splice) for exactly this case, and losing the nicer pre-roll is a far
smaller cost than losing the clip itself over a buffer subprocess hiccup.
"""

from __future__ import annotations

import contextlib
import os
import subprocess as _subprocess
import threading
import time
from pathlib import Path

from .._consts import log
from ._ffmpeg_clip import drain_ffmpeg_stderr


#: Requested segment length. See module docstring — actual segments run
#: >= this. Overridable per-host like `_encode_queue.SQ_ENCODE_SLOTS`,
#: since the right number depends on hardware this runs on.
def _segment_time_s() -> float:
    try:
        return max(0.5, float(os.environ.get("SQ_RING_SEGMENT_S", "1.0")))
    except (TypeError, ValueError):
        return 1.0


#: How much history stays on disk per camera. Generous over the default
#: 3.0 s pre-roll window (`resolve_pre_motion_seconds`) to absorb GOP
#: overshoot, trigger latency and the janitor's own sweep interval.
def _ring_seconds() -> float:
    try:
        return max(5.0, float(os.environ.get("SQ_RING_SECONDS", "20.0")))
    except (TypeError, ValueError):
        return 20.0


_CLEANUP_EVERY_S = 5.0


# ── pure helpers — no filesystem, no subprocess, fully unit-testable ──────


def parse_segment_stem(path: Path) -> float | None:
    """The epoch-seconds timestamp a ring segment's filename encodes, or
    None for anything that isn't one (a stray file, a partial write with
    a temp suffix)."""
    try:
        return float(path.stem)
    except ValueError:
        return None


def segments_covering(
    stamped: list[tuple[float, Path]], start_ts: float, end_ts: float, *, segment_time_s: float
) -> list[Path]:
    """Which segments overlap [start_ts, end_ts], oldest first.

    `stamped` is (own_start_ts, path) pairs, ANY order — sorted here so
    callers can hand over a raw directory listing. A segment's own range
    is [its start, the NEXT segment's start); the last segment's end is
    estimated as start + 4*segment_time_s (generous — better to include
    one segment too many than silently drop live coverage because the
    janitor hasn't written the next file yet).
    """
    ordered = sorted(stamped, key=lambda t: t[0])
    out: list[Path] = []
    for i, (ts, path) in enumerate(ordered):
        seg_end = ordered[i + 1][0] if i + 1 < len(ordered) else ts + segment_time_s * 4
        if seg_end < start_ts or ts > end_ts:
            continue
        out.append(path)
    return out


def stale_segments(stamped: list[tuple[float, Path]], cutoff_ts: float) -> list[Path]:
    """Segments whose own start is older than `cutoff_ts` — what the
    janitor should delete this sweep."""
    return [path for ts, path in stamped if ts < cutoff_ts]


# ── the stateful half — one continuous ffmpeg process per camera ──────────


class StreamRingBufferMixin:
    """Owns one continuous stream-copy segmenter per camera.

    Mixin for CameraRuntime, alongside CaptureMixin — `_capture.py` calls
    `_start_ring_buffer()`/`_stop_ring_buffer()` from the same places it
    already opens/closes `self.capture`, and `_lifecycle.py::stop()`
    calls `_stop_ring_buffer()` on final shutdown. State lives on
    `self.*` because every other long-lived subprocess handle in this
    package does (`self._ffmpeg_proc` in `_ffmpeg_clip.py`).
    """

    def _ring_buffer_dir(self) -> Path:
        return Path(self.global_cfg["storage"]["root"]) / "_ring" / self.camera_id

    def _ring_stamped_segments(self) -> list[tuple[float, Path]]:
        try:
            files = list(self._ring_buffer_dir().glob("*.mp4"))
        except OSError:
            return []
        out = []
        for f in files:
            ts = parse_segment_stem(f)
            if ts is not None:
                out.append((ts, f))
        return out

    def _ring_segments_covering(self, start_ts: float, end_ts: float) -> list[Path]:
        """Ring segments overlapping [start_ts, end_ts], oldest first —
        [] when the buffer never started, hasn't accumulated anything
        yet, or the process has died. Never raises."""
        try:
            return segments_covering(
                self._ring_stamped_segments(), start_ts, end_ts, segment_time_s=_segment_time_s()
            )
        except Exception as e:
            log.debug("[%s] ring segment lookup failed: %s", self.camera_id, e)
            return []

    def _start_ring_buffer(self) -> None:
        """(Re)start the continuous segmenter. Safe to call repeatedly —
        stops any previous instance first, mirroring `_open_capture`'s
        own 'retire the previous handle first' rule for `self.capture`.
        A snapshot-only camera (no `rtsp_url`) has nothing to buffer."""
        self._stop_ring_buffer()
        rtsp_url = self.cfg.get("rtsp_url")
        if not rtsp_url:
            return
        ring_dir = self._ring_buffer_dir()
        try:
            ring_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("[%s] ring buffer directory failed: %s", self.camera_id, e)
            return
        cmd = [
            "ffmpeg",
            "-y",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp_url,
            "-c",
            "copy",
            "-an",
            "-f",
            "segment",
            "-segment_time",
            str(_segment_time_s()),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            str(ring_dir / "%s.mp4"),
        ]
        try:
            proc = _subprocess.Popen(
                cmd,
                stdin=_subprocess.PIPE,
                stdout=_subprocess.DEVNULL,
                stderr=_subprocess.PIPE,
            )
            # THIS ONE RUNS FOR EVER, so an undrained stderr pipe is not a
            # risk here, it is a certainty: ~64 KB of warnings and ffmpeg
            # blocks on the write and stops segmenting, leaving the ring
            # frozen at whatever it had. That is exactly what truncated
            # every recording on two cameras — see
            # `_ffmpeg_clip.drain_ffmpeg_stderr`, which this reuses rather
            # than repeating.
            drain_ffmpeg_stderr(proc, self.camera_id)
        except FileNotFoundError:
            return  # no ffmpeg on this box — _start_ffmpeg_recording already logs this loudly
        except Exception as e:
            log.warning("[%s] ring buffer spawn failed: %s", self.camera_id, e)
            return
        self._ring_proc = proc
        self._ring_stop_evt = threading.Event()
        self._ring_cleanup_thread = threading.Thread(
            target=self._ring_cleanup_loop,
            args=(self._ring_stop_evt,),
            daemon=True,
            name=f"ring-janitor-{self.camera_id}",
        )
        self._ring_cleanup_thread.start()
        log.info(
            "[%s] Vorlauf-Ringpuffer gestartet (Segmente %.1fs, Fenster %.0fs)",
            self.camera_id,
            _segment_time_s(),
            _ring_seconds(),
        )

    def _stop_ring_buffer(self) -> None:
        """Idempotent. Safe to call when nothing was ever started."""
        evt = getattr(self, "_ring_stop_evt", None)
        if evt is not None:
            evt.set()
        self._ring_stop_evt = None
        proc = getattr(self, "_ring_proc", None)
        self._ring_proc = None
        if proc is None:
            return
        with contextlib.suppress(Exception):
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except _subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

    def _ring_cleanup_loop(self, stop_evt: threading.Event) -> None:
        """Deletes segments older than the ring window. Runs until
        `stop_evt` is set — `Event.wait` doubles as the sleep, so stop is
        immediate rather than waiting out the last interval."""
        while not stop_evt.wait(_CLEANUP_EVERY_S):
            cutoff = time.time() - _ring_seconds()
            try:
                for f in stale_segments(self._ring_stamped_segments(), cutoff):
                    with contextlib.suppress(OSError):
                        f.unlink(missing_ok=True)
            except Exception as e:
                log.debug("[%s] ring cleanup sweep failed: %s", self.camera_id, e)
