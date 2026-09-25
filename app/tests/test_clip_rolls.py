"""Der Nachlauf, den ein Clip tatsächlich hat.

„Vorlauf und Nachlauf ist auch nicht schön markiert in der Timeline."

Auf der Nut Bar stand bei jedem Clip „Nachlauf 0" (fünf von fünf,
2026-09-25): notiert wurde der EIGENE Wert der Kamera, und die hat
keinen — sie erbt die globalen 3 s und hat auch genau damit gestoppt.
Der Zeitstrahl zeichnete daher nie ein Nachlauf-Band.
"""

from __future__ import annotations

from pathlib import Path

from app.camera_runtime._recording._rolls import record_post_roll, resolve_post_motion_seconds

_REPO = Path(__file__).resolve().parents[2]


def test_a_camera_without_its_own_tail_inherits_the_global_one():
    assert resolve_post_motion_seconds({}, {"processing": {"post_motion_tail_s": 3.0}}) == 3.0
    assert resolve_post_motion_seconds({"post_motion_tail_s": 0}, {}) == 3.0


def test_the_cameras_own_tail_wins():
    assert resolve_post_motion_seconds({"post_motion_tail_s": 5}, {}) == 5.0


def test_fractions_survive():
    """`int()` machte aus 2,5 s zwei."""
    assert resolve_post_motion_seconds({"post_motion_tail_s": 2.5}, {}) == 2.5


def test_the_measured_post_roll_is_recorded_on_the_running_clip():
    meta = {}
    record_post_roll(meta, 6.4321)
    assert meta["post_roll_s"] == 6.43


def test_recording_nothing_is_harmless():
    record_post_roll(None, 3.0)
    meta = {}
    record_post_roll(meta, "kaputt")
    assert "post_roll_s" not in meta


def test_there_is_one_resolution_not_three():
    """Dieselbe Regel stand an drei Stellen von Hand — und war an einer
    falsch. Keine davon darf sie wieder selbst hinschreiben."""
    for rel in (
        "app/app/camera_runtime/_recording_step.py",
        "app/app/camera_runtime/_recording/_provenance.py",
        "app/app/camera_runtime/_recording/__init__.py",
    ):
        src = (_REPO / rel).read_text(encoding="utf-8")
        assert "resolve_post_motion_seconds(" in src, rel
        assert 'get("post_motion_tail_s") or 0' not in src, rel


def test_the_finished_clip_carries_the_measurement():
    src = (_REPO / "app/app/camera_runtime/_recording/_finalize.py").read_text(encoding="utf-8")
    assert 'rs["post_motion_seconds"] = meta["post_roll_s"]' in src
    step = (_REPO / "app/app/camera_runtime/_recording_step.py").read_text(encoding="utf-8")
    stop = step[step.index("record_post_roll(self._rec_event_meta") :]
    assert stop.index("record_post_roll") < stop.index(
        "_stop_ffmpeg_and_queue_reencode()"
    ), "gemessen werden muss VOR dem Stopp — der gibt die Metadaten weiter"
