"""The debug snapshot must answer "why was there no alert" on its own.

The operator diagnoses this system from an iPhone over SSH to an Unraid
box. Every field missing from the snapshot is a field they have to go
fetch with ``docker logs … | grep …`` on a phone keyboard, so the bar
here is: whatever the diagnosis needs is IN the copied text.

A real snapshot the user sent had five holes, and each of them is a
regression test below:

    TICK     ok · 0 ms · next ? ms          <- frontend-only, printed "?"
    CADENCE  avg_cycle 369 · hold ?         <- frontend-only, printed "?"
    Motion-Gate: trigger_mode: ?            <- WRONG KEY (detection_trigger)
                 motion_threshold: ?        <- WRONG KEY (motion_sensitivity)
    sub_stream_fps: 0.0                     <- never measured, printed 0.0

The last one is the worst kind of bug in a diagnostic: ``0.0`` reads as
"the stream is dead" and sends the operator hunting a camera fault that
does not exist. An unmeasured value must say so.
"""

from __future__ import annotations

import logging

import pytest

from app.logging_setup import log_buffer
from app.routes._debug_snapshot import build_findings, build_snapshot, collect_log_lines
from app.routes._debug_snapshot._findings import ladder_rows

CAM_ID = "reolink_cx810_hof_42"


def _cam(**over):
    cam = {
        "id": CAM_ID,
        "name": "Hof",
        "object_filter": ["person"],
        "label_thresholds": {"person": 0.45},
    }
    cam.update(over)
    return cam


def _tt(**over):
    tick = {
        "detections": [{"label": "person", "score": 0.65, "verdict": "pass", "track_num": 1}],
        "trace": ["[capture] frame 640x360"],
        "frame_size": {"w": 640, "h": 360},
        "frame_age_ms": 120,
        "diag": {"frame_src": "sub", "inference_ms": 42, "frame_interval_avg_ms": 369},
        "cluster_evidence": {
            "cluster4": {"tick_cycle_ema_ms": 369, "dropped_ticks_session": 0},
        },
    }
    tick.update(over)
    return {"last_tick": tick}


PUSH_CFG = {
    "telegram": {
        "push": {
            "labels": {
                "person": {"push": True, "threshold": 0.85},
                "cat": {"push": False, "threshold": 0.60},
            }
        }
    },
    "processing": {"wildlife": {"min_score": 0.35}},
}


def _md(cam=None, tt=None, runtime=None, eff=None):
    return build_snapshot(
        cam=cam or _cam(),
        cam_id=CAM_ID,
        tt=tt if tt is not None else _tt(),
        runtime=runtime,
        eff_cfg=eff if eff is not None else PUSH_CFG,
    )["markdown"]


# ── the five holes ────────────────────────────────────────────────────


def test_frontend_only_values_are_placeholders_not_question_marks():
    """``next`` and ``hold`` live in the browser's scheduler. The server
    cannot know them — so it leaves a token the frontend fills in, rather
    than printing "?" and leaving the reader to wonder which it is."""
    md = _md()
    assert "next <<tick_next_ms>>" in md
    assert "hold <<hold_ms>>" in md
    assert "next ? ms" not in md
    assert "hold ?" not in md


def test_the_motion_gate_reads_the_keys_that_actually_exist():
    """``trigger_mode`` / ``motion_threshold`` are not camera fields —
    the schema calls them ``detection_trigger`` / ``motion_sensitivity``,
    which is why both rendered as "?" forever."""
    md = _md(_cam(detection_trigger="objects_only", motion_sensitivity=0.7))
    assert "detection_trigger:  objects_only" in md
    assert "motion_sensitivity: 0.70" in md
    assert "trigger_mode" not in md
    assert "motion_threshold" not in md


def test_an_unmeasured_fps_says_so_instead_of_printing_zero():
    """There is no ``_sub_fps`` counter anywhere in camera_runtime, so
    the old ``sub_stream_fps: 0.0`` was a fabricated zero."""
    md = _md()
    assert "sub_stream_fps:        n/v" in md
    assert "sub_stream_fps: 0.0" not in md


def test_a_measured_fps_is_reported_as_a_number():
    class _Runtime:
        _main_fps = 7.4

    md = _md(runtime=_Runtime())
    assert "main_stream_fps:       7.4" in md
    # …and the counter that genuinely does not exist stays honest.
    assert "sub_stream_fps:        n/v (wird nicht gemessen)" in md


def test_a_zero_wildlife_score_names_the_global_it_falls_back_to():
    """0.0 is the schema's "use the global" marker, not a real floor."""
    md = _md()
    assert "wildlife_min_score: 0.00 (0 → global processing.wildlife.min_score = 0.35)" in md


def test_unset_tracker_overrides_are_not_reported_as_a_zero_threshold():
    md = _md()
    assert "track_spawn_min_score:     0.00 (nicht gesetzt → tracker_core-Default)" in md


# ── what was missing entirely ─────────────────────────────────────────


def test_the_snapshot_carries_the_server_log(monkeypatch):
    """The root console is what this replaces; the log lines have to be
    in the paste or the operator still opens a shell."""
    monkeypatch.setattr(
        "app.routes._debug_snapshot._helpers.log_buffer",
        _FakeBuffer(
            [
                {
                    "ts": "12:00:01",
                    "level": "INFO",
                    "msg": f"[trigger][cam:{CAM_ID}] alert routing",
                },
                {"ts": "12:00:02", "level": "INFO", "msg": "[weather] irrelevant chatter"},
            ]
        ),
    )
    md = _md()
    assert "## Server-Log" in md
    assert "alert routing" in md
    assert "irrelevant chatter" not in md


def test_log_lines_never_leak_a_password(monkeypatch):
    """A snapshot gets pasted into a chat window."""
    monkeypatch.setattr(
        "app.routes._debug_snapshot._helpers.log_buffer",
        _FakeBuffer(
            [{"ts": "12:00:01", "level": "ERROR", "msg": "open rtsp://admin:hunter2@cam.lan/h264"}]
        ),
    )
    md = _md()
    assert "hunter2" not in md
    assert "admin:•••@cam.lan" in md


def test_the_alarm_path_gates_are_all_reported():
    cam = _cam(
        armed=False,
        recording_enabled=False,
        telegram_enabled=False,
        class_severity={"person": "alarm"},
        schedule_notify={"enabled": True, "from": "22:00", "to": "06:00"},
    )
    md = _md(cam)
    for field in ("armed:", "telegram_enabled:", "recording_enabled:", "class_severity:"):
        assert field in md
    assert "schedule_notify:   22:00→06:00 · aktiv_jetzt=" in md
    assert "schedule_record:   24/7" in md


def test_the_push_bar_stands_next_to_the_detection_bar():
    """The 65 %-person-never-arrived case: the trace now names the push
    gate, and the snapshot must show the configured bar beside it."""
    md = _md()
    assert "Schwellen-Leiter" in md
    assert "0.85" in md, "the configured push threshold must be visible"
    assert "TOTE ZONE" in md


def test_a_class_that_can_never_push_says_so():
    md = _md(_cam(object_filter=["cat"], label_thresholds={}))
    assert "push=false → wird NIE gemeldet" in md


# ── findings (the on-screen half) ─────────────────────────────────────


def test_findings_put_the_blocking_gate_first():
    """Only the first two or three lines survive on a phone screen."""
    cam = _cam(armed=False)
    findings = build_snapshot(cam=cam, cam_id=CAM_ID, tt=_tt(), runtime=None, eff_cfg=PUSH_CFG)[
        "findings"
    ]
    assert findings[0]["tone"] == "red"
    assert "armed" in findings[0]["text"]


def test_a_healthy_camera_gets_one_ok_finding():
    cam = _cam(object_filter=[], label_thresholds={})
    findings = build_findings(cam, _tt()["last_tick"], {}, [])
    assert len(findings) == 1
    assert findings[0]["tone"] == "ok"


def test_the_dead_zone_is_named_as_its_own_pattern():
    """spawn 0.45 / push 0.85 = recorded forever, never sent. Nothing in
    the UI used to say that out loud."""
    ladder = ladder_rows(_cam(), PUSH_CFG["telegram"]["push"], ["person"])
    findings = build_findings(_cam(), _tt()["last_tick"], {}, ladder)
    assert any("tote Zone" in f["text"] for f in findings)


def test_findings_appear_in_the_copied_text_too():
    """One diagnosis, two renderings — the screen shows it short, the
    paste carries the same verdict so a reader gets the conclusion."""
    md = _md(_cam(armed=False))
    assert "## Befund" in md
    assert "armed=false" in md


# ── plumbing ──────────────────────────────────────────────────────────


class _FakeBuffer:
    def __init__(self, records):
        self._records = records

    def get(self, min_level=logging.DEBUG):
        return list(self._records)


def test_collect_log_lines_is_bounded():
    """400 buffered records must never all end up in one paste."""
    many = [{"ts": "12:00:00", "level": "INFO", "msg": f"[det] line {i}"} for i in range(400)]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routes._debug_snapshot._helpers.log_buffer", _FakeBuffer(many))
        lines = collect_log_lines(CAM_ID)
    assert len(lines) == 40
    assert lines[-1]["msg"] == "[det] line 399", "newest lines are the ones kept"


def test_this_cameras_own_lines_are_never_crowded_out():
    """``[det]`` / ``[tg]`` are system-wide tags. On a multi-camera box a
    chatty detector would fill a 40-line window with other cameras' noise
    and the snapshot would look full while saying nothing about this one."""
    noise = [{"ts": "12:00:00", "level": "INFO", "msg": f"[det] other cam {i}"} for i in range(60)]
    ours = [
        {"ts": "12:00:01", "level": "INFO", "msg": f"[trigger][cam:{CAM_ID}] ours {i}"}
        for i in range(5)
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routes._debug_snapshot._helpers.log_buffer", _FakeBuffer(noise + ours))
        lines = collect_log_lines(CAM_ID)
    kept = [line["msg"] for line in lines]
    for i in range(5):
        assert f"ours {i}" in "\n".join(kept), "every line naming this camera must survive"
    assert len(lines) == 40, "the rest of the budget is still filled with context"


def test_the_log_block_reads_chronologically():
    """Camera lines and context lines are re-interleaved by buffer order —
    a block that jumped back in time would misread as a causal sequence."""
    records = [
        {"ts": "12:00:00", "level": "INFO", "msg": "[det] before"},
        {"ts": "12:00:01", "level": "INFO", "msg": f"[trigger][cam:{CAM_ID}] middle"},
        {"ts": "12:00:02", "level": "INFO", "msg": "[tg] after"},
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routes._debug_snapshot._helpers.log_buffer", _FakeBuffer(records))
        lines = collect_log_lines(CAM_ID)
    assert [line["msg"] for line in lines] == [r["msg"] for r in records]


def test_the_real_log_buffer_is_readable():
    """Guards against the filter drifting away from the buffer's shape."""
    log_buffer.emit(
        logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=f"[trigger][cam:{CAM_ID}] probe",
            args=(),
            exc_info=None,
        )
    )
    assert any("probe" in r["msg"] for r in collect_log_lines(CAM_ID))


def test_a_missing_tick_does_not_break_the_document():
    """The snapshot is what you reach for when nothing works."""
    md = _md(tt={})
    assert "noch kein Tick" in md
    assert "## Befund" in md


# ── SIMU · foreign COCO classes must not become findings ──────────────────
#
# A workshop camera pointed at a bench makes the detector report book,
# chair, suitcase, backpack and laptop every tick. None of them has an
# entry in TELEGRAM_PUSH_DEFAULTS, so `resolve_effective` returns
# push_enabled=False for each and the findings builder emitted a warn-tone
# "<class>: push=false — wird erkannt, aber nie gemeldet." per class.
# Warn sorts above info, so five non-findings pushed the REAL diagnostics
# off a phone screen that shows three lines.


def test_foreign_coco_classes_do_not_become_ladder_rows():
    from app.routes._debug_snapshot import _relevant_labels

    cam = {"object_filter": ["person", "cat", "dog"]}
    last = {
        "detections": [
            {"label": "person"},
            {"label": "book"},
            {"label": "chair"},
            {"label": "suitcase"},
            {"label": "laptop"},
        ]
    }
    assert _relevant_labels(cam, last) == ["cat", "dog", "person"]


def test_a_project_label_the_camera_does_not_filter_for_is_still_shown():
    """The vocabulary in labels.py — not the camera's filter — decides what
    counts as a real class. Seeing a squirrel on a camera that does not
    filter for squirrels is a genuine finding worth a ladder row."""
    from app.routes._debug_snapshot import _relevant_labels

    cam = {"object_filter": ["person"]}
    last = {"detections": [{"label": "squirrel"}, {"label": "book"}]}
    assert _relevant_labels(cam, last) == ["person", "squirrel"]


def test_a_filtered_for_class_survives_even_if_it_left_the_vocabulary():
    """An explicit object_filter entry is something the operator asked
    about by name; it must never be silently dropped."""
    from app.routes._debug_snapshot import _relevant_labels

    cam = {"object_filter": ["person", "weird_custom_class"]}
    last = {"detections": [{"label": "weird_custom_class"}, {"label": "book"}]}
    assert _relevant_labels(cam, last) == ["person", "weird_custom_class"]


def test_an_empty_filter_still_reports_real_classes():
    from app.routes._debug_snapshot import _relevant_labels

    cam = {"object_filter": []}
    last = {"detections": [{"label": "person"}, {"label": "book"}]}
    assert _relevant_labels(cam, last) == ["person"]


# ── the wildlife threshold the panel could not name ───────────────────
#
# `processing.wildlife.min_score` IS live — `WildlifeClassifier.__init__`
# reads it with a hardcoded fallback, so the classifier really runs at
# that fallback on the deployed box, whose config.yaml predates the
# `processing.wildlife` block. The snapshot printed the config lookup
# raw, so a missing key rendered as:
#
#     wildlife_min_score: 0.00 (0 → global processing.wildlife.min_score = n/v)
#
# "n/v" reads as "no threshold is in effect", which is the opposite of
# the truth and sends the operator looking for a disabled classifier.
# The detector's behaviour is deliberately unchanged here — only the
# panel learns to name the value that is actually running, and where it
# came from.


def test_a_missing_global_wildlife_score_names_the_classifier_default():
    from app.detectors.wildlife import WILDLIFE_MIN_SCORE_DEFAULT
    from app.routes._debug_snapshot._blocks import _motion_block

    out = _motion_block(_cam(), {"processing": {}})
    assert "n/v" not in out
    assert f"{WILDLIFE_MIN_SCORE_DEFAULT:.2f}" in out
    assert "Klassifizierer-Default" in out


def test_a_configured_global_wildlife_score_is_shown_as_configured():
    from app.routes._debug_snapshot._blocks import _motion_block

    out = _motion_block(_cam(), {"processing": {"wildlife": {"min_score": 0.5}}})
    assert "0.50" in out
    assert "Klassifizierer-Default" not in out


def test_a_per_camera_override_still_wins_the_line():
    from app.routes._debug_snapshot._blocks import _motion_block

    out = _motion_block(_cam(wildlife_min_score=0.6), {"processing": {}})
    assert "wildlife_min_score: 0.60" in out
    assert "Klassifizierer-Default" not in out


def test_the_panel_default_is_the_one_the_detector_actually_uses():
    """The number on screen and the number in the classifier come from
    one constant — a second literal is how they drift apart."""
    import inspect

    from app.detectors import wildlife

    src = inspect.getsource(wildlife.WildlifeClassifier.__init__)
    assert 'self.cfg.get("min_score", WILDLIFE_MIN_SCORE_DEFAULT)' in src
