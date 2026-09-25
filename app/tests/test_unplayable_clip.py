"""Ein Clip ohne ein einziges dekodierbares Bild wird nicht ausgeliefert.

„ffmpeg re-encode rc=1 … Cannot determine format of input stream 0:0
after EOF … Conversion failed! … solche Videos … löscht die einfach."

Am 2026-09-25 standen 32 solche Kacheln in der Mediathek (18 Garten,
14 Nut Bar), jede 1332 Byte groß: ein MP4 mit Kopf und ohne Keyframe.
Die alte Rückfallschiene prüfte nur „größer als 1024 Byte" — und genau
das ist ein Kopf ohne Bild auch.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import app.camera_runtime._recording._unplayable as unplayable
from app.camera_runtime._consts import MIN_LIVE_SEGMENT_S
from app.camera_runtime._recording._unplayable import discard_unplayable, has_decodable_frame

_REPO = Path(__file__).resolve().parents[2]


def test_a_header_without_frames_is_not_playable(tmp_path):
    """So groß wie die echten Ausfälle — und größer als die alte Hürde."""
    raw = tmp_path / "x.raw.mp4"
    raw.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1320)
    assert raw.stat().st_size > 1024
    assert has_decodable_frame(raw) is False


def test_a_missing_file_is_not_playable(tmp_path):
    assert has_decodable_frame(tmp_path / "nope.mp4") is False
    assert has_decodable_frame(None) is False


def test_a_real_clip_is_playable(tmp_path):
    import cv2

    path = tmp_path / "ok.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (64, 48))
    for i in range(5):
        writer.write(np.full((48, 64, 3), i * 40, dtype=np.uint8))
    writer.release()
    assert has_decodable_frame(path) is True


def test_an_unplayable_clip_goes_to_the_trash_not_away(monkeypatch):
    """Papierkorb, nicht Löschen — wer es doch sehen will, holt es zurück."""
    calls = []

    def fake_trash(cam, eid):
        calls.append((cam, eid))
        return {"json_deleted": True, "trashed": True}

    import app.trash as trash

    monkeypatch.setattr(trash, "move_to_trash", fake_trash)
    assert discard_unplayable("cam1", "e1", "ffmpeg re-encode rc=1:\nConversion failed!") is True
    assert calls == [("cam1", "e1")]


def test_a_trash_failure_is_reported_not_raised(monkeypatch):
    import app.trash as trash

    def boom(cam, eid):
        raise OSError("disk full")

    monkeypatch.setattr(trash, "move_to_trash", boom)
    assert discard_unplayable("cam1", "e1", None) is False


def test_the_finalize_chain_discards_instead_of_publishing():
    """Kein Telegram-Link auf ein Video, das nicht abspielt: der Verwurf
    steht VOR dem Vorschaubild, dem Filmstreifen und der Ankündigung."""
    src = (_REPO / "app/app/camera_runtime/_recording/_finalize.py").read_text(encoding="utf-8")
    orchestrator = src[
        src.index("def _reencode_motion_clip") : src.index("def _produce_playable_clip")
    ]
    discard = orchestrator.index("discard_unplayable(")
    assert discard < orchestrator.index("extract_motion_thumbnail(")
    assert discard < orchestrator.index("_announce_finished_clip(")
    assert (
        "if has_decodable_frame(raw_path):" in src
    ), "die Rückfallschiene prüft wieder nur die Größe"
    assert unplayable.has_decodable_frame is has_decodable_frame


def test_a_live_recording_runs_long_enough_to_catch_a_keyframe():
    """Die Ursache: gestoppt nach Bewegung plus Nachlauf, also ~3 s, von
    denen ~1 s der RTSP-Aufbau frisst."""
    assert MIN_LIVE_SEGMENT_S >= 6.0
    src = (_REPO / "app/app/camera_runtime/_recording_step.py").read_text(encoding="utf-8")
    assert "since_start >= min_live" in src
