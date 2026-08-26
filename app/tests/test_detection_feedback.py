"""The alert/verdict ledger — the corpus everything downstream needs.

Before this existed, a user judgement led nowhere: `event["confirmed"]`
had no reader in the Python code, and the Telegram verdict stored only
`{verdict, by, ts}` in settings.json — no camera, no label, and crucially
not the score that produced the alert. So no amount of tapping could
calibrate anything, and settings.json grew without bound.

These tests pin the properties the downstream work depends on: records
survive concurrent writers, a truncated line cannot poison the file, the
ledger stays bounded, and an unanswered alert contributes nothing.
"""

from __future__ import annotations

import json
import threading

import pytest

from app.detection_feedback import (
    iter_records,
    judged_alerts,
    ledger_path,
    record_alert,
    record_verdict,
    score_summary,
)


class _Det:
    def __init__(self, label, score):
        self.label = label
        self.score = score


def _alert(root, eid, cam="cam1", label="person", score=0.62, ts=1000.0):
    return record_alert(
        root,
        cam_id=cam,
        event_id=eid,
        label=label,
        score=score,
        threshold=0.85,
        ts=ts,
        detections=[_Det(label, score)],
    )


# ── writing ───────────────────────────────────────────────────────────


def test_alert_is_recorded_with_the_numbers_behind_it(tmp_path):
    assert _alert(tmp_path, "e1")

    recs = list(iter_records(tmp_path))
    assert len(recs) == 1
    assert recs[0]["kind"] == "alert"
    assert recs[0]["cam"] == "cam1"
    assert recs[0]["label"] == "person"
    assert recs[0]["score"] == 0.62
    assert recs[0]["threshold"] == 0.85, "the bar it had to clear must be recorded too"


def test_detections_in_frame_are_kept(tmp_path):
    record_alert(
        tmp_path,
        cam_id="cam1",
        event_id="e1",
        label="person",
        score=0.7,
        threshold=0.45,
        ts=1.0,
        detections=[_Det("person", 0.7), _Det("dog", 0.4)],
    )
    dets = list(iter_records(tmp_path))[0]["detections"]
    assert {d["label"] for d in dets} == {"person", "dog"}


def test_verdict_is_recorded(tmp_path):
    record_verdict(tmp_path, event_id="e1", correct=False, ts=2.0, source="telegram")
    rec = list(iter_records(tmp_path))[0]
    assert rec["kind"] == "verdict"
    assert rec["correct"] is False
    assert rec["source"] == "telegram"


def test_corrected_label_survives(tmp_path):
    """'It was actually a dog' is what a per-camera label veto is built on."""
    record_verdict(
        tmp_path, event_id="e1", correct=False, ts=2.0, corrected_label="dog", source="web"
    )
    assert list(iter_records(tmp_path))[0]["corrected_label"] == "dog"


def test_ledger_lives_outside_the_event_folders(tmp_path):
    """cleanup_old deletes events by age; the corpus must not live there."""
    _alert(tmp_path, "e1")
    assert "_diag" in ledger_path(tmp_path).parts
    assert "motion_detection" not in ledger_path(tmp_path).parts


# ── robustness ────────────────────────────────────────────────────────


def test_a_truncated_line_does_not_poison_the_file(tmp_path):
    """Power loss mid-append must not make the whole ledger unreadable."""
    _alert(tmp_path, "e1")
    with open(ledger_path(tmp_path), "a", encoding="utf-8") as fh:
        fh.write('{"kind": "alert", "event_i')  # torn write, no newline
    _alert(tmp_path, "e2")

    ids = {r.get("event_id") for r in iter_records(tmp_path)}
    assert "e1" in ids and "e2" in ids


def test_missing_ledger_reads_as_empty(tmp_path):
    assert list(iter_records(tmp_path)) == []


def test_write_failure_is_reported_not_raised(tmp_path, monkeypatch):
    """A diagnostic write must never break a capture loop."""
    monkeypatch.setattr(
        "app.detection_feedback.ledger_path",
        lambda _root: (_ for _ in ()).throw(OSError("disk gone")),
    )
    assert _alert(tmp_path, "e1") is False


def test_concurrent_writers_lose_nothing(tmp_path):
    """Camera threads, the Telegram callback thread and HTTP handlers all
    write here; a torn interleave would silently drop judgements."""
    errors = []

    def writer(n):
        for i in range(25):
            if not _alert(tmp_path, f"e{n}-{i}"):
                errors.append(n)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    recs = list(iter_records(tmp_path))
    assert len(recs) == 150, f"expected 150 records, got {len(recs)}"
    # And every line must still be valid JSON.
    for line in ledger_path(tmp_path).read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_ledger_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("app.detection_feedback._MAX_BYTES", 2000)
    for i in range(200):
        _alert(tmp_path, f"e{i}")

    assert ledger_path(tmp_path).stat().st_size <= 2000 * 3
    # Rotation keeps one previous generation, and both are still read.
    assert len(list(iter_records(tmp_path))) > 0


# ── joining ───────────────────────────────────────────────────────────


def test_only_judged_alerts_are_returned(tmp_path):
    """An unanswered alert says nothing and must not skew calibration."""
    _alert(tmp_path, "answered")
    _alert(tmp_path, "ignored")
    record_verdict(tmp_path, event_id="answered", correct=True, ts=5.0)

    pairs = judged_alerts(tmp_path)
    assert len(pairs) == 1
    assert pairs[0][0]["event_id"] == "answered"
    assert pairs[0][1] is True


def test_a_later_verdict_supersedes_an_earlier_one(tmp_path):
    _alert(tmp_path, "e1")
    record_verdict(tmp_path, event_id="e1", correct=True, ts=5.0)
    record_verdict(tmp_path, event_id="e1", correct=False, ts=6.0)

    assert judged_alerts(tmp_path)[0][1] is False


def test_filtering_by_camera_and_label(tmp_path):
    _alert(tmp_path, "a", cam="cam1", label="person")
    _alert(tmp_path, "b", cam="cam2", label="person")
    _alert(tmp_path, "c", cam="cam1", label="squirrel")
    for eid in ("a", "b", "c"):
        record_verdict(tmp_path, event_id=eid, correct=True, ts=9.0)

    assert len(judged_alerts(tmp_path, cam_id="cam1")) == 2
    assert len(judged_alerts(tmp_path, cam_id="cam1", label="person")) == 1


def test_verdict_without_its_alert_is_ignored(tmp_path):
    record_verdict(tmp_path, event_id="ghost", correct=True, ts=1.0)
    assert judged_alerts(tmp_path) == []


# ── summary ───────────────────────────────────────────────────────────


def test_summary_reports_counts_alongside_the_numbers(tmp_path):
    """A separation computed from three samples is noise — any caller
    moving a threshold has to be able to see the sample size."""
    for i, (score, ok) in enumerate([(0.9, True), (0.7, True), (0.3, False)]):
        _alert(tmp_path, f"e{i}", score=score)
        record_verdict(tmp_path, event_id=f"e{i}", correct=ok, ts=10.0 + i)

    s = score_summary(tmp_path, "cam1", "person")
    assert s["n_total"] == 3
    assert s["n_true"] == 2
    assert s["n_false"] == 1
    assert s["true_min"] == 0.7
    assert s["false_max"] == 0.3


def test_summary_on_no_data_is_safe(tmp_path):
    s = score_summary(tmp_path, "cam1", "person")
    assert s["n_total"] == 0
    assert s["true_min"] is None and s["false_max"] is None


@pytest.mark.parametrize("bad", [None, "", 0])
def test_missing_event_id_is_skipped_in_joins(tmp_path, bad):
    record_alert(
        tmp_path,
        cam_id="cam1",
        event_id=bad,
        label="person",
        score=0.5,
        threshold=0.4,
        ts=1.0,
    )
    assert judged_alerts(tmp_path) == []
