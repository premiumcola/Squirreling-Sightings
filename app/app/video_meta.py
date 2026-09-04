"""What a video file actually is: pixel size and length.

One place, because two callers need the same answer and a second
implementation of "ask ffprobe how wide this is" is exactly the parallel
implementation CLAUDE.md forbids.

WHY IT EXISTS AT ALL. Telegram's ``sendVideo`` accepts ``width``,
``height`` and ``duration``, and when they are omitted it falls back to
its own guess about the file. That guess is not reliable: the daily
timelapse arrived on the phone in a box that was nothing like the
camera's own aspect — „Format vom gesendetem timelapse strange 😬" — and
the encoder had already done its part correctly (``timelapse.py`` scales
with ``force_original_aspect_ratio=decrease`` and pads, so the stored mp4
is exactly right). Telling Telegram the numbers removes the guess.

Best-effort throughout: every failure returns ``None`` and the caller
sends the video without the hints, exactly as before. A probe must never
be the reason a notification does not go out.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

#: ffprobe is fast on a local file, but it is still a subprocess on the
#: box that runs the capture loops. A file it cannot answer for in this
#: long is a file we send without hints.
_PROBE_TIMEOUT_S = 10


def video_dimensions(path: str | Path) -> tuple[int, int, int] | None:
    """``(width, height, duration_s)`` for a video file, or ``None``.

    ``duration`` is rounded to whole seconds because that is the only
    resolution Telegram's API accepts for it.

    The DISPLAY size is what is returned, not the coded size: a stream
    with a non-square sample aspect ratio is stored at one size and meant
    to be shown at another, and handing a player the coded numbers is its
    own way of producing a wrong-shaped box.
    """
    if not shutil.which("ffprobe"):
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,sample_aspect_ratio:format=duration",
                "-print_format",
                "json",
                str(p),
            ],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_S,
        )
        if r.returncode != 0:
            return None
        info = json.loads(r.stdout.decode(errors="replace") or "{}")
    except Exception as e:
        log.debug("[video] probe of %s failed: %s", p.name, e)
        return None

    streams = info.get("streams") or []
    if not streams:
        return None
    st = streams[0]
    try:
        w = int(st.get("width") or 0)
        h = int(st.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    w = _apply_sar(w, st.get("sample_aspect_ratio"))
    try:
        duration = int(round(float((info.get("format") or {}).get("duration") or 0.0)))
    except (TypeError, ValueError):
        duration = 0
    return (w, h, max(0, duration))


def _apply_sar(width: int, sar: str | None) -> int:
    """Widen ``width`` by a non-square sample aspect ratio.

    ffprobe reports SAR as ``"num:den"``; ``"1:1"``, ``"0:1"`` and a
    missing value all mean square pixels and leave the width alone. The
    timelapse encoder writes ``setsar=1`` so this is a no-op there — it
    is here for every other file that reaches the same send path.
    """
    if not sar or ":" not in str(sar):
        return width
    try:
        num, den = (int(x) for x in str(sar).split(":", 1))
    except (TypeError, ValueError):
        return width
    if num <= 0 or den <= 0 or num == den:
        return width
    return max(1, int(round(width * num / den)))
