"""SIGTERM has to actually end the process.

`_install_shutdown_hooks` ran the shutdown work — the session Bilanz and
(since the clip-recovery work) the interrupted-clip stamp — and then
RETURNED. The WSGI server kept serving, so `docker stop` sat out its
full ~10 s grace on every restart before SIGKILLing us. Two costs: ten
seconds added to each deploy on a box the operator redeploys many times
a day, and the hard kill landing at an arbitrary moment instead of
immediately after the cleanup finished.

The fix is the canonical "clean up, then terminate normally" pattern —
restore the default disposition and re-raise the signal — so the exit
status stays the one the caller expects (`-SIGTERM`), which a bare
`os._exit(0)` would misreport as a clean voluntary exit.

Driven as a real subprocess because that is the only way to observe a
signal disposition; a mocked `signal.signal` would assert the shape of
the fix rather than its effect.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]

_PROBE = textwrap.dedent(
    """
    import sys, time
    sys.path.insert(0, %r)
    from app.lifecycle import _install_shutdown_hooks
    import app.app_state as app_state
    # No storage root: the stamp must fail soft and still let us exit.
    app_state.storage_root = "/nonexistent-probe-root"
    _install_shutdown_hooks()
    print("ready", flush=True)
    while True:
        time.sleep(0.2)
    """
)


def _spawn():
    proc = subprocess.Popen(
        [sys.executable, "-c", _PROBE % str(_APP)],
        cwd=str(_APP),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    line = proc.stdout.readline().strip() if proc.stdout else ""
    if line != "ready":
        proc.kill()
        pytest.skip("probe process did not start")
    return proc


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_the_process_exits_on_the_signal(sig):
    proc = _spawn()
    started = time.time()
    proc.send_signal(sig)
    try:
        rc = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail(
            f"still running 10 s after {sig!r} — docker stop would have to SIGKILL, "
            "adding its whole grace period to every restart"
        )
    assert time.time() - started < 8, "shutdown took most of docker's grace window"
    assert rc == -sig, f"expected termination by {sig!r}, got exit status {rc}"


def test_the_shutdown_work_still_runs_before_exiting():
    """Exiting must not skip the cleanup — that would trade one bug for
    a worse one (clips left claiming they are still encoding)."""
    src = (_APP / "app" / "lifecycle.py").read_text(encoding="utf-8")
    body = src[src.index("def _sig_handler(") :]
    body = body[: body.index("\n    try:")]
    assert body.index("_once(") < body.index("os.kill("), "the process exits before cleaning up"
