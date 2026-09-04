"""Telegram must be told a video's shape, not left to guess it.

„Format vom gesendetem timelapse strange 😬" — the daily timelapse
arrived on the phone in a box nothing like the camera's own aspect.

Measured on the host: the stored frames are 2560x1440, exactly 16:9, and
``timelapse.py`` scales with ``force_original_aspect_ratio=decrease``,
pads to the same box and writes ``setsar=1``. Nothing in this project
distorts the file. What was missing is that ``sendVideo`` was called with
no ``width`` / ``height`` / ``duration``, so the client fell back to its
own guess about the container.

ffprobe is not installed in the dev container, so these drive the parser
against captured ffprobe output rather than against ffmpeg. That is the
part that can be wrong in a way a person would not notice.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.video_meta import _apply_sar, video_dimensions


class _Result:
    def __init__(self, payload: dict, rc: int = 0):
        self.returncode = rc
        self.stdout = json.dumps(payload).encode()
        self.stderr = b""


@pytest.fixture
def probe(monkeypatch, tmp_path):
    """Stand in for ffprobe. Returns a setter for the payload it reports."""
    monkeypatch.setattr("app.video_meta.shutil.which", lambda _n: "/usr/bin/ffprobe")
    holder: dict = {}

    def _run(cmd, **kw):
        if "boom" in holder:
            raise holder["boom"]
        return _Result(holder.get("payload", {}), holder.get("rc", 0))

    monkeypatch.setattr(subprocess, "run", _run)

    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\0")

    def _set(payload=None, rc=0, boom=None):
        holder.clear()
        if payload is not None:
            holder["payload"] = payload
        holder["rc"] = rc
        if boom is not None:
            holder["boom"] = boom
        return f

    return _set


def _payload(w, h, sar="1:1", duration="60.04"):
    return {
        "streams": [{"width": w, "height": h, "sample_aspect_ratio": sar}],
        "format": {"duration": duration},
    }


# ── the real case ────────────────────────────────────────────────────


def test_a_16_9_timelapse_reports_16_9(probe):
    f = probe(_payload(1920, 1080))
    assert video_dimensions(f) == (1920, 1080, 60)


def test_the_duration_is_whole_seconds(probe):
    """Telegram's API takes an integer, and a float would be dropped."""
    f = probe(_payload(1920, 1080, duration="59.6"))
    assert video_dimensions(f)[2] == 60


# ── a stream whose pixels are not square ─────────────────────────────


def test_a_stretched_stream_reports_its_DISPLAY_width(probe):
    """A 2:1 sample aspect is stored 720 wide and meant to be shown 1440
    wide. Handing a player the coded number is its own wrong-shaped box —
    which is the whole defect this module exists to avoid."""
    f = probe(_payload(720, 576, sar="2:1"))
    assert video_dimensions(f)[0] == 1440


@pytest.mark.parametrize("sar", ["1:1", "0:1", "", None, "garbage", "3:0"])
def test_square_or_unusable_sar_leaves_the_width_alone(sar):
    assert _apply_sar(1920, sar) == 1920


# ── every failure is silent and sends the video anyway ───────────────


def test_no_ffprobe_installed_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr("app.video_meta.shutil.which", lambda _n: None)
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\0")
    assert video_dimensions(f) is None


def test_a_missing_file_is_not_an_error():
    assert video_dimensions("/nope/does-not-exist.mp4") is None


def test_a_failed_probe_is_not_an_error(probe):
    assert video_dimensions(probe(_payload(1920, 1080), rc=1)) is None


def test_a_crashing_probe_is_not_an_error(probe):
    assert video_dimensions(probe(boom=OSError("no"))) is None


def test_a_timeout_is_not_an_error(probe):
    assert video_dimensions(probe(boom=subprocess.TimeoutExpired("ffprobe", 10))) is None


def test_a_file_with_no_video_stream_is_not_an_error(probe):
    assert video_dimensions(probe({"streams": [], "format": {}})) is None


@pytest.mark.parametrize("w,h", [(0, 1080), (1920, 0), (-1, -1)])
def test_a_nonsense_size_is_refused(probe, w, h):
    """Better no hint than a hint of 0x1080 — Telegram would honour it."""
    assert video_dimensions(probe(_payload(w, h))) is None


def test_an_unreadable_duration_still_yields_the_size(probe):
    """The shape is the point; the length is a bonus."""
    f = probe(_payload(1920, 1080, duration="n/a"))
    assert video_dimensions(f) == (1920, 1080, 0)


# ── the send path actually uses it ───────────────────────────────────


def test_send_video_is_given_the_shape():
    src = (
        Path(__file__).resolve().parents[1] / "app" / "telegram_bot" / "_outbound" / "_payload.py"
    ).read_text(encoding="utf-8")
    call = src[src.index("return await bot.send_video") :]
    call = call[: call.index(")") + 1]
    assert "_video_hints(video)" in call, "sendVideo is still left to guess the aspect"


def test_the_hints_are_skipped_for_in_memory_video():
    """A clip held as bytes has no file for ffprobe to read; probing it
    would spawn a subprocess per send for a guaranteed miss."""
    from app.telegram_bot._outbound._payload import _video_hints

    assert _video_hints(b"\0\0") == {}
    assert _video_hints(None) == {}


def test_streaming_is_declared():
    """A timelapse is watched where it lands, not downloaded first."""
    from app.telegram_bot._outbound import _payload

    src = Path(_payload.__file__).read_text(encoding="utf-8")
    assert "supports_streaming" in src
