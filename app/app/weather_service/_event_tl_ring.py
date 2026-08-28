"""Pre-roll ring buffer for the weather event timelapse.

Why this exists
───────────────
The three event-tl triggers are forecast-based, but a storm only
*reveals* itself once it is already overhead. ``_run_event_tl_capture``
starts writing frames at trigger time and runs forward, so the minutes
of build-up — the part the operator actually wants to see — were gone
before the first frame was written. This module keeps a rolling window
of those minutes so the finished clip is ``pre-roll + event``.

Frame source
────────────
The ring pulls from ``rt.snapshot_jpeg_hires(quality=92)`` through
``grab_valid_frame`` — the *same* source, the same validator profile and
the same cadence the forward capture uses. Two consequences, both
deliberate:

* No seam. Splicing sub-stream preview frames (1280×720) onto main-stream
  frames (2560×1440) would change resolution mid-clip and force the
  encoder to rescale half the timeline.
* No second capture loop. Exactly one hires grab per ``interval_s`` per
  camera exists at any moment: the ring loop suspends itself for the
  duration of a capture (``_event_tl_inflight``) and the forward capture
  takes over the cadence.

``camera_runtime.WeatherPrebuffer`` was evaluated for reuse and rejected:
it is sized ``pre_roll_s × fps`` against the *preview* loop (15 fps), so
a 15-minute window would hold 13 500 frames ≈ 1.1 GB per camera, and it
carries sub-stream frames. It stays what it is — the 5-second splice for
``_clip.py``.

Disk, not RAM
─────────────
At the shipped ``interval_s = 8`` a 15-minute window is 113 frames. A
2560×1440 JPEG at quality 92 runs 0.6–1.5 MB, so the window is roughly
90 MB per camera, 180 MB across the two weather cameras, worst case
~340 MB. Holding that resident 24/7 on a box that already software-
decodes three H.265 streams is the more dangerous of the two costs: an
OOM kill takes every camera down, whereas SSD writes only wear. The
bytes have to reach disk anyway — the encoder reads files, so a RAM ring
would merely delay and then concentrate the same write. So: disk, under
``weather/<cam>/event_timelapse/.prebuffer/``, with BOTH a frame cap and
a byte cap (``prebuffer_max_mb``, default 256) so an unusually detailed
scene cannot outgrow the budget.

Cleanup obligations, all of them met here: on boot
(``_event_tl_boot_cleanup``), on teardown (``_stop_event_tl_prebuffers``
from shutdown/reload), and when a camera is disabled or loses its opt-in
(``_sync_event_tl_rings``).
"""

from __future__ import annotations

import contextlib
import shutil
import threading
from pathlib import Path

from ._consts import log

# Directory / file markers. Every one of them starts with a dot, which is
# what keeps them invisible to the sighting listers: _manifests.py skips
# `.scratch_*` event dirs and only reads `*.json` directly inside an event
# dir, and routes/weather.py's rescan skips any entry whose name starts
# with a dot. Renaming these prefixes means revisiting both.
PREBUFFER_DIR_NAME = ".prebuffer"
SCRATCH_DIR_PREFIX = ".scratch_"
PART_MP4_PREFIX = ".part_"

# Per-camera defaults. `armed` is the shipped mode: the ring only spins
# while the forecast shows elevated risk. Because the triggers are
# themselves forecast-based and look 60–90 min ahead, the watch predicate
# normally arms hours before a trigger fires — a risk-armed ring gets the
# same pre-roll as an always-on one at a fraction of the duty cycle.
DEFAULT_PREBUFFER_MIN = 15
DEFAULT_PREBUFFER_MODE = "armed"
PREBUFFER_MODES = ("off", "armed", "always")

# Global (weather.event_timelapse.*) cost caps.
DEFAULT_PREBUFFER_MAX_MB = 256
DEFAULT_WATCH_GRACE_MIN = 30

# How often the ring loop re-picks its DAY/TWILIGHT/NIGHT validator
# profile. Unlike the forward capture this costs nothing extra — the
# re-pick runs against the most recent frame the loop already grabbed.
_RING_REPICK_S = 300.0


class EventTLRing:
    """Bounded on-disk ring of JPEG frames, oldest evicted first.

    Two independent bounds, whichever binds first:
      * ``capacity`` frames — the configured pre-roll window.
      * ``max_bytes``       — defence against an unusually large JPEG.

    ``arm()`` is the hinge the user described: the ring stops discarding
    and hands its frames to the capture, which then keeps writing
    forward. An armed ring accepts no further pushes — the forward
    capture owns the cadence from that moment on.
    """

    def __init__(self, scratch_dir: Path, capacity: int, max_bytes: int):
        self.dir = Path(scratch_dir)
        self.capacity = max(1, int(capacity))
        self.max_bytes = max(1, int(max_bytes))
        self._lock = threading.Lock()
        self._paths: list = []  # list[tuple[Path, int]] — chronological
        self._bytes = 0
        self._seq = 0
        self._armed = False
        self.dir.mkdir(parents=True, exist_ok=True)

    # ── State ───────────────────────────────────────────────────────────
    @property
    def armed(self) -> bool:
        with self._lock:
            return self._armed

    @property
    def bytes_held(self) -> int:
        with self._lock:
            return self._bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._paths)

    # ── Writing ─────────────────────────────────────────────────────────
    def push(self, jpg: bytes):
        """Append one frame, evicting from the head until both bounds
        hold. Returns the written path, or None when the ring is armed
        (capture owns the cadence) or the write failed."""
        if not jpg:
            return None
        with self._lock:
            if self._armed:
                return None
            path = self.dir / ("%08d.jpg" % self._seq)
            self._seq += 1
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(jpg)
            except Exception as e:
                log.warning("[weather] prebuffer write failed %s: %s", path.name, e)
                return None
            self._paths.append((path, len(jpg)))
            self._bytes += len(jpg)
            self._evict_locked()
            return path

    def _evict_locked(self) -> None:
        while self._paths and (len(self._paths) > self.capacity or self._bytes > self.max_bytes):
            old_path, old_size = self._paths.pop(0)
            self._bytes -= old_size
            with contextlib.suppress(Exception):
                old_path.unlink()

    # ── Handover ────────────────────────────────────────────────────────
    def arm(self) -> int:
        """Freeze the ring. Returns the number of retained frames.
        Idempotent — a second trigger on an already-armed ring is a
        no-op rather than a second handover."""
        with self._lock:
            self._armed = True
            return len(self._paths)

    def frames(self) -> list:
        """Retained frames, oldest first. The list order IS the capture
        order — never re-derive it from the filesystem, because a purge
        racing a push can leave a gap in the numbering."""
        with self._lock:
            return [p for p, _ in self._paths]

    # ── Teardown ────────────────────────────────────────────────────────
    def purge(self) -> None:
        """Drop every frame and the directory itself."""
        with self._lock:
            self._paths = []
            self._bytes = 0
            self._armed = False
        shutil.rmtree(self.dir, ignore_errors=True)


def purge_event_tl_scratch(weather_root: Path) -> int:
    """Remove every leftover pre-roll ring, capture scratch dir and
    part-encoded mp4 under ``weather/<cam>/event_timelapse/``.

    Called once at service start. Nothing of ours is running at that
    point, so anything matching is by definition an orphan from a
    container restart mid-ring or mid-encode. Returns the number of
    entries removed (for the boot log line).
    """
    removed = 0
    root = Path(weather_root)
    if not root.exists():
        return 0
    try:
        cam_dirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except Exception as e:
        log.warning("[weather] prebuffer boot cleanup: cannot list %s: %s", root, e)
        return 0
    for cam_dir in cam_dirs:
        evt_dir = cam_dir / "event_timelapse"
        if not evt_dir.is_dir():
            continue
        for entry in list(evt_dir.iterdir()):
            name = entry.name
            is_ring = entry.is_dir() and name == PREBUFFER_DIR_NAME
            is_scratch = entry.is_dir() and name.startswith(SCRATCH_DIR_PREFIX)
            is_part = entry.is_file() and name.startswith(PART_MP4_PREFIX)
            if not (is_ring or is_scratch or is_part):
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink()
                removed += 1
            except Exception as e:
                log.warning("[weather] prebuffer boot cleanup: %s: %s", entry, e)
    if removed:
        log.info("[weather] prebuffer boot cleanup: %d orphan entr(ies) removed", removed)
    return removed
