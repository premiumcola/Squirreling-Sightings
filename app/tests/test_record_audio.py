"""Recording the camera's microphone onto the motion clip.

The pipeline threw audio away in three places, all of them an explicit
``-an``: the raw→H.264 re-encode, and both halves of the pre-roll concat
(the stream copy tried first and the re-encode fallback). The RTSP
stream-copy that produces the raw file never dropped it — ``-c copy``
carries whatever the camera offers — so the sound was captured and then
discarded one step later, every time.

``cameras[].record_audio`` turns that around per camera. Default OFF and
it stays off for every existing camera: a microphone pointed at a garden
records the neighbours too, so this is an opt-in, never a migration.

What this file pins
───────────────────
* OFF is byte-for-byte the command line each of those three steps has
  always run — an audio feature must not change a single clip for the
  cameras nobody switched it on for.
* ON keeps the audio and lands it as AAC, the only codec every browser
  plays out of an mp4.
* The pre-roll splice, which is the case a naive concat gets wrong: a
  silent segment in front of an audio-bearing one. The pre-roll gets a
  silent AAC track with the SAME pinned parameters as the main clip, so
  the concat demuxer's stream copy has two matching inputs — and that
  silent track is added only when the main clip really has audio to
  match, because a camera with no microphone would otherwise turn the
  mismatch around and lose its lead-in.
* The setting's default, at both ends that can drop it (the schema and
  the ``default_camera`` skeleton), plus the ``/api/cameras`` projection
  the cam-edit form hydrates from.

ffmpeg is not installed in this sandbox (nor in CI) — see
``test_motion_preroll.py``'s module docstring. Nothing here invokes it:
the command lines are built by pure functions precisely so they can be
asserted on, and the one path that would spawn a process is stubbed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import flask
import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

# The transcode moved to _finalize.py when _ffmpeg_clip.py crossed the
# 500-line ceiling; the mixin below still exposes the whole chain, but
# the module-level `cv2`/`_subprocess` these tests patch live where the
# code that uses them does.
import app.camera_runtime._recording._finalize as clip_mod  # noqa: E402
import app.camera_runtime._recording._preroll as preroll_mod  # noqa: E402
from app import app_state  # noqa: E402
from app.camera_runtime._recording._ffmpeg_clip import FfmpegClipMixin  # noqa: E402
from app.camera_runtime._recording._preroll import (  # noqa: E402
    build_concat_tail,
    preroll_audio_wanted,
)
from app.media_encode import (  # noqa: E402
    AAC_OUTPUT_ARGS,
    AUDIO_SAMPLE_RATE,
    SILENT_AUDIO_INPUT,
    build_jpeg_frames_cmd,
    build_reencode_cmd,
)
from app.routes import cameras as camera_routes  # noqa: E402
from app.schema import CAMERA_SCHEMA  # noqa: E402
from app.settings.defaults import default_camera  # noqa: E402

CAM = "reolink_rlc810a_garten_23"


# ── The re-encode: where the clip's own audio was dropped ────────────────


def test_reencode_drops_audio_when_the_camera_did_not_opt_in():
    cmd = build_reencode_cmd(Path("/s/e.raw.mp4"), Path("/s/e.mp4"), record_audio=False)

    assert "-an" in cmd
    assert "-c:a" not in cmd
    assert "aac" not in cmd


def test_reencode_off_is_byte_for_byte_the_historical_command():
    """The whole promise of a default-off privacy toggle: a camera that
    never touched it records exactly what it recorded yesterday."""
    assert build_reencode_cmd(Path("/s/e.raw.mp4"), Path("/s/e.mp4"), record_audio=False) == [
        "ffmpeg",
        "-y",
        "-i",
        "/s/e.raw.mp4",
        "-vcodec",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        "/s/e.mp4",
    ]


def test_reencode_keeps_audio_as_aac_when_the_camera_opted_in():
    cmd = build_reencode_cmd(Path("/s/e.raw.mp4"), Path("/s/e.mp4"), record_audio=True)

    assert "-an" not in cmd, "the opt-in is meaningless if the encode still strips audio"
    assert cmd[cmd.index("-c:a") + 1] == "aac", "mp4 audio a browser will not play is no audio"
    assert cmd[-1] == "/s/e.mp4", "the output path must stay last"


def test_the_reencode_pins_the_audio_layout_the_preroll_also_uses():
    """The concat demuxer stream-copies first, and a stream copy cannot
    resample — the two segments have to agree on codec, rate and channels
    or the joined file plays wrong. Both sides read the same constant."""
    cmd = build_reencode_cmd(Path("/s/e.raw.mp4"), Path("/s/e.mp4"), record_audio=True)

    assert AAC_OUTPUT_ARGS[0] == "-c:a"
    for arg in AAC_OUTPUT_ARGS:
        assert arg in cmd
    assert cmd[cmd.index("-ar") + 1] == AUDIO_SAMPLE_RATE


# ── The transcode step actually reads the per-camera setting ─────────────


class _Clipper(FfmpegClipMixin):
    """Just enough of a CameraRuntime for ``_transcode_raw_to_mp4``."""

    def __init__(self, cfg: dict):
        self.camera_id = "cam1"
        self.cfg = cfg

    def _set_clip_stage(self, event_id, stage):
        pass


class _FakeCap:
    """cv2.VideoCapture stand-in — a readable clip without a real file."""

    def get(self, prop):
        return 30 if prop == cv2.CAP_PROP_FRAME_COUNT else 15.0

    def release(self):
        pass


@pytest.fixture
def transcode_argv(tmp_path, monkeypatch):
    """Run ``_transcode_raw_to_mp4`` against a stubbed ffmpeg and hand
    back the argv it would have executed."""

    def _run(cfg: dict) -> list[str]:
        raw = tmp_path / "evt.raw.mp4"
        raw.write_bytes(b"R" * 4096)
        vid = tmp_path / "evt.mp4"
        seen: list[list[str]] = []

        def _fake_run(cmd, **kw):
            seen.append(list(cmd))
            vid.write_bytes(b"V" * 4096)
            return SimpleNamespace(returncode=0, stderr=b"")

        monkeypatch.setattr(clip_mod._subprocess, "run", _fake_run)
        monkeypatch.setattr(clip_mod.cv2, "VideoCapture", lambda _p: _FakeCap())
        video_url, _rel, _dur, _size, err = _Clipper(cfg)._transcode_raw_to_mp4(
            raw, vid, "evt", tmp_path, ""
        )
        assert err is None and video_url, "the stubbed encode should have succeeded"
        assert len(seen) == 1
        return seen[0]

    return _run


def test_a_camera_without_the_flag_still_transcodes_without_audio(transcode_argv):
    assert "-an" in transcode_argv({})


def test_the_flag_reaches_the_ffmpeg_call(transcode_argv):
    argv = transcode_argv({"record_audio": True})

    assert "-an" not in argv
    assert "aac" in argv


# ── The pre-roll segment: the silent side of the splice ──────────────────


def test_the_jpeg_encoder_stays_video_only_by_default():
    cmd = build_jpeg_frames_cmd(Path("/s/pre.mp4"), 3)

    assert "lavfi" not in cmd
    assert "-c:a" not in cmd
    assert "-shortest" not in cmd


def test_the_jpeg_encoder_can_fabricate_a_matching_silent_track():
    cmd = build_jpeg_frames_cmd(Path("/s/pre.mp4"), 3, silent_audio=True)

    assert SILENT_AUDIO_INPUT in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    # anullsrc is infinite; without -shortest the pre-roll would run for
    # ever and the splice would never finish.
    assert "-shortest" in cmd
    assert cmd[-1] == "/s/pre.mp4"


# ── The concat tails ─────────────────────────────────────────────────────


def test_both_concat_tails_are_unchanged_when_audio_is_off():
    copy_tail = build_concat_tail(Path("/s/out.mp4"), reencode=False, want_audio=False)
    encode_tail = build_concat_tail(Path("/s/out.mp4"), reencode=True, want_audio=False)

    assert copy_tail == ["-c", "copy", "-movflags", "+faststart", "-an", "/s/out.mp4"]
    assert encode_tail == [
        "-vcodec",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        "/s/out.mp4",
    ]


def test_the_copy_tail_carries_audio_through_untouched_when_it_is_wanted():
    """`-c copy` already copies every stream — adding audio flags on the
    copy branch would be an encode the copy path exists to avoid."""
    tail = build_concat_tail(Path("/s/out.mp4"), reencode=False, want_audio=True)

    assert tail == ["-c", "copy", "-movflags", "+faststart", "/s/out.mp4"]


def test_the_reencode_tail_re_states_the_pinned_aac_layout():
    tail = build_concat_tail(Path("/s/out.mp4"), reencode=True, want_audio=True)

    assert "-an" not in tail
    for arg in AAC_OUTPUT_ARGS:
        assert arg in tail
    assert tail[-1] == "/s/out.mp4"


# ── The splice decision itself ───────────────────────────────────────────


def test_a_camera_that_never_opted_in_is_never_probed(tmp_path, monkeypatch):
    """The ffprobe is a subprocess per spliced clip — an operator who left
    audio off must not pay for it."""
    probed = []
    monkeypatch.setattr(preroll_mod, "clip_has_audio_stream", lambda p: probed.append(p) or True)

    assert preroll_audio_wanted({}, tmp_path / "clip.mp4") is False
    assert preroll_audio_wanted({"record_audio": False}, tmp_path / "clip.mp4") is False
    assert probed == []


def test_the_opt_in_splices_audio_when_the_clip_actually_has_some(tmp_path, monkeypatch):
    monkeypatch.setattr(preroll_mod, "clip_has_audio_stream", lambda _p: True)

    assert preroll_audio_wanted({"record_audio": True}, tmp_path / "clip.mp4") is True


def test_a_camera_with_no_microphone_falls_back_to_the_silent_splice(tmp_path, monkeypatch):
    """record_audio on but the camera ships no audio stream: the main clip
    has no track, so a silent pre-roll in front of it is the SAME layout
    mismatch in reverse. Answering 'no audio' keeps the lead-in the
    operator would otherwise silently lose."""
    monkeypatch.setattr(preroll_mod, "clip_has_audio_stream", lambda _p: False)

    assert preroll_audio_wanted({"record_audio": True}, tmp_path / "clip.mp4") is False


def test_an_unprobeable_clip_is_treated_as_silent(tmp_path, monkeypatch):
    """No ffprobe on PATH is the sandbox's own situation. The conservative
    branch is the historical `-an` splice, never a promised audio track
    that isn't there."""
    monkeypatch.setattr(preroll_mod.shutil, "which", lambda _n: None)

    assert preroll_mod.clip_has_audio_stream(tmp_path / "clip.mp4") is False


def test_the_splice_asks_for_a_silent_track_only_when_audio_is_wanted(tmp_path, monkeypatch):
    """End-to-end through the splice: the flag the camera carries has to
    arrive at BOTH the pre-roll encode and the concat, or the two segments
    disagree about their stream layout."""
    calls: dict = {}

    def _fake_encode(frames, out_path, fps, **kw):
        calls["silent_audio"] = kw.get("silent_audio")
        Path(out_path).write_bytes(b"P" * 2000)
        return True

    def _fake_concat(pre, main, out, want_audio=False):
        calls["want_audio"] = want_audio
        Path(out).write_bytes(b"S" * 2000)
        return True

    monkeypatch.setattr(preroll_mod, "encode_jpeg_frames_to_mp4", _fake_encode)
    monkeypatch.setattr(
        preroll_mod.MotionPrerollMixin, "_concat_preroll_and_clip", staticmethod(_fake_concat)
    )
    monkeypatch.setattr(preroll_mod, "clip_has_audio_stream", lambda _p: True)
    monkeypatch.setattr(
        preroll_mod.cv2,
        "VideoCapture",
        lambda _p: _FakeCap(),
    )

    class _Splicer(preroll_mod.MotionPrerollMixin):
        def __init__(self, cfg):
            self.camera_id = "cam1"
            self.cfg = cfg

    vid = tmp_path / "evt.mp4"
    vid.write_bytes(b"O" * 2000)
    frames = [(1000.0, b"x"), (1002.0, b"x")]

    assert _Splicer({"record_audio": True})._splice_preroll_onto_clip(
        vid, frames, "evt", tmp_path
    ) == pytest.approx(2.0)
    assert calls == {"silent_audio": True, "want_audio": True}

    calls.clear()
    vid.write_bytes(b"O" * 2000)
    _Splicer({})._splice_preroll_onto_clip(vid, frames, "evt", tmp_path)
    assert calls == {"silent_audio": False, "want_audio": False}


# ── The setting: default OFF at every end that can drop it ───────────────


def test_the_schema_declares_the_field_defaulting_to_off():
    assert CAMERA_SCHEMA["record_audio"] == (bool, False)


def test_a_new_camera_is_seeded_with_audio_off():
    assert default_camera({})["record_audio"] is False


def test_an_existing_camera_without_the_key_reads_as_off():
    """Every camera in a shipped settings.json predates this field. None
    of them may start recording sound because the code arrived."""
    assert default_camera({"id": CAM, "name": "Garten"})["record_audio"] is False


def test_a_camera_that_opted_in_keeps_the_flag_through_the_skeleton():
    assert default_camera({"id": CAM, "record_audio": True})["record_audio"] is True


@pytest.fixture
def client(monkeypatch):
    def _wire(cam_extra: dict):
        cam = {"id": CAM, "name": "Garten", **cam_extra}
        monkeypatch.setattr(
            app_state, "get_effective_config", lambda: {"cameras": [cam]}, raising=False
        )
        monkeypatch.setattr(app_state, "runtimes", {}, raising=False)
        monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), raising=False)
        app = flask.Flask(__name__)
        app.register_blueprint(camera_routes.bp)
        return app.test_client()

    return _wire


def _row(c) -> dict:
    r = c.get("/api/cameras")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["cameras"][0]


def test_the_projection_carries_the_opt_in(client):
    """Same lesson as `color`: a key the key-by-key projection forgets is
    a key the frontend never sees, however well it is stored."""
    assert _row(client({"record_audio": True}))["record_audio"] is True


def test_the_projection_reports_off_rather_than_omitting_the_key(client):
    row = _row(client({}))
    assert "record_audio" in row
    assert row["record_audio"] is False
