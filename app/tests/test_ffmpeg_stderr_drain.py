"""A recorder's stderr is drained, or the recording stops mid-clip.

THE MEASUREMENT THAT FOUND IT. On the live archive, 361 clips on one
camera and not one longer than 32.1 s — against a `clip_max_duration_s`
of 120 s, and against the clips' own frame tallies, which ran the full
window (`whole_clip.detections[].last_s` up to 127 s). A third camera,
quieter on stderr, reached 234 s. The operator saw the two halves
disagree: „Wieso wird unten ein objekt bis 2:xx mins erkannt wenn der
clip nur knapp 30s hat???"

THE CAUSE. `_start_ffmpeg_recording` spawns ffmpeg with `stderr=PIPE`
and nothing ever read it. A pipe holds ~64 KB; ffmpeg's progress line
plus a Reolink feed's steady warnings fill that in well under a minute,
and a process blocked writing stderr stops muxing. The file freezes,
the analysis loop keeps going on its own thread, and the clip ends up a
fraction of its own recording window. Python's subprocess docs warn
about this exact deadlock.

Two things are pinned here: the drain works and is bounded, and NEITHER
long-running spawn is left with an unread pipe — the continuous ring
buffer has the same shape and, running for ever, would hit it with
certainty rather than merely with probability.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

from app.camera_runtime._recording._ffmpeg_clip import (
    drain_ffmpeg_stderr,
    ffmpeg_stderr_tail,
)

_REC = Path(__file__).resolve().parent.parent / "app" / "camera_runtime" / "_recording"


class _FakeProc:
    def __init__(self, payload: bytes):
        self.stderr = io.BytesIO(payload)
        self.returncode = 0


def _settle(proc, want_lines: int, timeout_s: float = 2.0) -> None:
    """Wait for the drain thread to finish reading a finite stream."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if getattr(proc, "sq_stderr_tail", None) is not None and proc.stderr.closed:
            return
        time.sleep(0.01)


def test_the_pipe_is_read_to_the_end():
    """The whole point: nothing is left in the pipe to block on."""
    proc = _FakeProc(b"line one\nline two\nline three\n")

    drain_ffmpeg_stderr(proc, "cam1")
    _settle(proc, 3)

    assert proc.stderr.closed, "the drain must consume the stream, not sample it"
    assert "line three" in ffmpeg_stderr_tail(proc)


def test_a_flood_is_bounded_rather_than_accumulated():
    """The failure mode is a chatty stream, so the fix must not answer it
    by growing without limit — the recorder runs for minutes and the ring
    buffer for ever."""
    proc = _FakeProc(b"".join(b"Non-monotonous DTS in output stream\n" for _ in range(5000)))

    drain_ffmpeg_stderr(proc, "cam1", keep=10)
    _settle(proc, 10)

    assert len(proc.sq_stderr_tail) == 10
    assert proc.stderr.closed


def test_the_kept_lines_are_the_LAST_ones():
    """A failure explains itself in what a process said just before it
    died, not in its startup banner."""
    proc = _FakeProc(b"banner\n" + b"".join(f"line {i}\n".encode() for i in range(50)))

    drain_ffmpeg_stderr(proc, "cam1", keep=3)
    _settle(proc, 3)

    assert ffmpeg_stderr_tail(proc).splitlines() == ["line 47", "line 48", "line 49"]


def test_a_process_without_a_pipe_is_a_safe_no_op():
    class _NoPipe:
        stderr = None

    proc = _NoPipe()
    drain_ffmpeg_stderr(proc, "cam1")  # must not raise

    assert ffmpeg_stderr_tail(proc) == ""


def test_an_unreadable_stream_never_escapes_into_the_recording():
    class _Angry:
        closed = False

        def readline(self):
            raise OSError("stream went away")

        def close(self):
            self.closed = True

    proc = _FakeProc(b"")
    proc.stderr = _Angry()

    drain_ffmpeg_stderr(proc, "cam1")  # must not raise
    time.sleep(0.05)

    assert ffmpeg_stderr_tail(proc) == ""


def test_the_tail_of_a_process_that_was_never_drained_is_empty():
    class _Bare:
        pass

    assert ffmpeg_stderr_tail(_Bare()) == ""


# ── the regression guard ────────────────────────────────────────────────


def _src(name: str) -> str:
    return (_REC / name).read_text(encoding="utf-8")


def test_every_long_running_spawn_drains_its_stderr():
    """Source-text, because the alternative is a test that must actually
    run ffmpeg for a minute to fail. Both of these processes outlive the
    call that starts them; a PIPE either of them does not read is the
    same deadlock again."""
    for filename in ("_ffmpeg_clip.py", "_ring_buffer.py"):
        src = _src(filename)
        if "stderr=_subprocess.PIPE" not in src:
            continue
        assert "drain_ffmpeg_stderr(" in src, (
            f"{filename} pipes stderr on a long-running process without draining it — "
            "that is what truncated every clip on two cameras"
        )


def test_the_recorder_does_not_ask_ffmpeg_for_a_progress_line():
    """`-nostats` removes the bulk of what filled the pipe. The drain
    makes it safe; this keeps it cheap."""
    assert "'-nostats'" in _src("_ffmpeg_clip.py")
