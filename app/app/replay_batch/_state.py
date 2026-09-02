"""In-flight state for the one batch replay run.

A module-level singleton guarded by one lock, deliberately NOT hung off
a service instance — saving settings rebuilds those (`rebuild_services`),
and a poll that arrived after a rebuild would find a fresh, empty job
and report a running batch as finished. Same reasoning, and the same
shape, as weather_service/_sun_tl's `_active_test_session`.

Cancellation is the two-flag protocol from that module: HTTP sets
`cancel_requested` under the lock, the worker reads it at each event
boundary and sets `cancelled` when it stops. One flag would not
distinguish "asked to stop" from "has stopped", which is exactly what a
progress line needs to say.
"""

from __future__ import annotations

import threading
from datetime import datetime

_lock = threading.Lock()

#: Phases, in the order a run passes through them. German because the
#: dashboard renders them verbatim, like every other status string here.
PHASE_IDLE = ""
PHASE_COUNTING = "zaehlen"
PHASE_RUNNING = "laeuft"
PHASE_DONE = "fertig"
PHASE_CANCELLED = "abgebrochen"
PHASE_ERROR = "fehler"


def _blank() -> dict:
    return {
        "running": False,
        "phase": PHASE_IDLE,
        "done": 0,
        "total": 0,
        "errors": 0,
        "cancel_requested": False,
        "cancelled": False,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "current": None,
        "report": None,
    }


_task: dict = _blank()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def snapshot() -> dict:
    """A copy of the state, taken under the lock so a poll never reads a
    half-updated dict."""
    with _lock:
        return dict(_task)


def begin(scope: dict) -> bool:
    """Claim the single run slot. False when one is already in flight —
    the single-flight guard `routes/media.py` uses, so a double click
    cannot start two archive walks."""
    with _lock:
        if _task["running"]:
            return False
        _task.update(_blank())
        _task.update(running=True, phase=PHASE_COUNTING, started_at=_now(), scope=scope)
        return True


def set_total(total: int) -> None:
    with _lock:
        _task["total"] = int(total)
        _task["phase"] = PHASE_RUNNING


def advance(event_id: str | None, *, failed: bool = False) -> None:
    with _lock:
        _task["done"] += 1
        _task["current"] = event_id
        if failed:
            _task["errors"] += 1


def request_cancel() -> bool:
    """True when a running job was asked to stop."""
    with _lock:
        if not _task["running"]:
            return False
        _task["cancel_requested"] = True
        return True


def cancel_requested() -> bool:
    with _lock:
        return bool(_task["cancel_requested"])


def finish(report: dict | None, *, cancelled: bool = False, error: str | None = None) -> None:
    """Single terminal write, mirroring media.py's `_integrity_task`
    update: one lock acquisition sets every field a poll can read."""
    with _lock:
        _task.update(
            running=False,
            cancelled=bool(cancelled),
            current=None,
            finished_at=_now(),
            error=error,
            report=report,
            phase=(PHASE_ERROR if error else (PHASE_CANCELLED if cancelled else PHASE_DONE)),
        )


def reset_for_tests() -> None:
    """Drop all state. Exists for the test suite, which would otherwise
    see one test's finished run as another's in-flight one."""
    with _lock:
        _task.clear()
        _task.update(_blank())
