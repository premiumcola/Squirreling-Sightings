"""Single source of truth for RTSP capture tuning.

Two knobs decide whether a wedged camera recovers in seconds or in half
a minute, and both are easy to set in a way that silently does nothing:

* ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` — FFmpeg 7 dropped the RTSP
  ``stimeout`` option; it is spelled ``timeout`` now (still
  microseconds). An unknown key is discarded without a word, so a
  handle that looks configured ends up with no socket timeout at all.
* ``CAP_PROP_{OPEN,READ}_TIMEOUT_MSEC`` — OpenCV's FFmpeg backend reads
  these only from the ``VideoCapture`` constructor's params vector.
  ``cap.set()`` after construction returns ``False`` and changes
  nothing, leaving the backend's 30 s interrupt default in charge.

Both together were why a stalled camera froze the dashboard tile for
~30 s while the 20 s watchdog fired into a read that could not be
interrupted. Every RTSP handle in the process goes through the two
helpers below so the pair can't drift apart again.
"""

from __future__ import annotations

import cv2

# FFmpeg socket-I/O timeout, microseconds. Deliberately just under the
# OpenCV read timeout so FFmpeg gives up first and surfaces a clean
# read failure instead of tripping the interrupt callback.
RTSP_TIMEOUT_US = 5_000_000
OPEN_TIMEOUT_MS = 8_000
READ_TIMEOUT_MS = 6_000


def capture_options(timeout_us: int = RTSP_TIMEOUT_US, extra: str = "") -> str:
    """Build the ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` value for an RTSP handle.

    ``extra`` appends further ``key;value`` pairs (e.g. ``hwaccel;none``)
    without losing the transport or timeout settings.
    """
    opts = f"rtsp_transport;tcp|timeout;{int(timeout_us)}"
    return f"{opts}|{extra}" if extra else opts


def timeout_params(open_ms: int = OPEN_TIMEOUT_MS, read_ms: int = READ_TIMEOUT_MS) -> list[int]:
    """Params vector carrying open/read timeouts into ``cv2.VideoCapture``.

    Must be passed as the third constructor argument — the equivalent
    ``cap.set()`` calls are no-ops on the FFmpeg backend.
    """
    return [
        int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC),
        int(open_ms),
        int(cv2.CAP_PROP_READ_TIMEOUT_MSEC),
        int(read_ms),
    ]
