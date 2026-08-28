"""Formatters + the log-ring-buffer reader for the debug snapshot.

Two conventions live here, and both exist because the previous snapshot
lied by omission:

* :data:`_UNKNOWN` — printed wherever a value is genuinely not knowable
  server-side. ``sub_fps: 0.0`` used to read as "the sub-stream is
  dead"; it meant "no counter exists".
* ``<<placeholder>>`` tokens — values only the browser holds (the next
  tick delay, the bbox hold time). The frontend substitutes them
  immediately before the clipboard write.
"""

from __future__ import annotations

import logging
import re

from ...event_logic import is_schedule_window_active
from ...logging_setup import log_buffer
from .._camera_helpers import _mask_password_in_url

_UNKNOWN = "n/v"

# How many server-log lines ride along. 40 is roughly one phone screen
# of scrollback and comfortably covers a single trigger→push sequence
# (capture → det → trigger → recording → tg), while keeping the paste
# small enough to send in a chat message.
_LOG_LINES = 40

# A log line is relevant to this snapshot when it names the camera or
# carries one of the tags that answer "why was there no alert".
_LOG_TAGS = (
    "[trigger]",
    "[tg]",
    "[det]",
    "[push",
    "Recording started",
    "Recording stopped",
    "NOT recording",
    "alert routing",
)

# Credential scrubber for log lines — a paste of this document ends up
# in a chat window. Matches the embedded-credential URL form only; the
# actual masking is delegated to the existing helper so there is one
# implementation of "hide the password".
_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s]*@[^\s]*")


def _scrub(text: str) -> str:
    """Mask passwords in any embedded-credential URL inside a log line."""
    return _URL_RE.sub(lambda m: _mask_password_in_url(m.group(0)), text or "")


def _fmt_float(val, digits: int = 2) -> str:
    try:
        return f"{float(val):.{digits}f}"
    except (TypeError, ValueError):
        return _UNKNOWN


def _fmt_fps(runtime, attr: str) -> str:
    """FPS counters are honest about their own absence.

    ``_main_fps`` is maintained by the camera runtime's main loop;
    there is no sub-stream counter at all. A missing attribute prints
    :data:`_UNKNOWN` with the reason rather than ``0.0``.
    """
    if runtime is None:
        return _UNKNOWN + " (kein Runtime-Thread für diese Kamera)"
    if not hasattr(runtime, attr):
        return _UNKNOWN + " (wird nicht gemessen)"
    val = getattr(runtime, attr, None)
    try:
        num = float(val or 0.0)
    except (TypeError, ValueError):
        return _UNKNOWN
    if num <= 0.0:
        return "0.0 (noch kein volles Messfenster)"
    return f"{num:.1f}"


def _fmt_schedule(sched: dict) -> str:
    """One line per schedule: window, whether it gates at all, active now."""
    if not sched:
        return "24/7 (nicht konfiguriert) · aktiv_jetzt=ja"
    if not sched.get("enabled"):
        return "24/7 (deaktiviert → gilt immer) · aktiv_jetzt=ja"
    try:
        active = "ja" if is_schedule_window_active(sched) else "NEIN"
    except Exception as exc:  # pragma: no cover - defensive
        active = f"{_UNKNOWN} ({exc})"
    return f"{sched.get('from', '?')}→{sched.get('to', '?')} · aktiv_jetzt={active}"


def _schedule_blocks(sched: dict) -> bool:
    if not sched or not sched.get("enabled"):
        return False
    try:
        return not is_schedule_window_active(sched)
    except Exception:  # pragma: no cover - defensive
        return False


def collect_log_lines(cam_id: str, limit: int = _LOG_LINES) -> list:
    """Ring-buffer lines relevant to this camera, oldest → newest.

    ``logging_setup.log_buffer`` already holds the last 400 records for
    ``/api/logs``; this is the same data narrowed to what answers "why
    was there no alert" so the operator never has to open a root shell.
    """
    try:
        records = log_buffer.get(logging.DEBUG)
    except Exception:  # pragma: no cover - defensive
        return []
    keep = []
    for rec in records:
        msg = rec.get("msg") or ""
        level = (rec.get("level") or "").upper()
        relevant = (
            (cam_id and cam_id in msg)
            or any(tag in msg for tag in _LOG_TAGS)
            or level in ("WARNING", "ERROR", "CRITICAL")
        )
        if relevant:
            keep.append(rec)
    return keep[-limit:]


def _log_block(cam_id: str, records) -> str:
    if not records:
        return (
            "(keine passenden Zeilen im Ring-Puffer — der Puffer hält die "
            "letzten 400 Server-Logs)"
        )
    lines = [
        f"{r.get('ts', '')} {(r.get('level') or '')[:4]:<4} {_scrub(r.get('msg') or '')}"
        for r in records
    ]
    return _fenced(lines)


def _fenced(lines) -> str:
    return "```\n" + "\n".join(lines) + "\n```"


def _section(title: str, body: str) -> str:
    return "\n## {}\n{}\n".format(title, body.rstrip())
