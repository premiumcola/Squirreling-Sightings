"""The read side, and its willingness to say "not yet".

`judged_alerts` and `score_summary` had zero non-test callers: the corpus
was written and never read, the same dead end that made
`event["confirmed"]` useless. `corpus_stats` plus `scripts/corpus_report`
close that loop.

The property worth testing is not that the report prints numbers — it is
that it REFUSES to endorse them, and that the refusal is per downstream
use, because a threshold move, a label veto and a nearest-centroid
classifier are three different statistical questions with three
different sample requirements.
"""

from __future__ import annotations

from app.detection_feedback import (
    MIN_AGREEING_CORRECTIONS,
    MIN_CLASSES_FOR_CENTROID,
    MIN_EXAMPLES_PER_CLASS,
    MIN_JUDGED_FOR_VETO,
    MIN_JUDGED_PER_CLASS,
    MIN_JUDGED_PER_STRATUM,
    centroid_readiness,
    corpus_stats,
    record_alert,
    record_verdict,
)
from scripts import corpus_report


def _judged(
    root,
    eid,
    *,
    cam="cam1",
    label="person",
    score=0.9,
    correct=True,
    threshold=0.5,
    ts=1.0,
    corrected_label=None,
):
    record_alert(
        root, cam_id=cam, event_id=eid, label=label, score=score, threshold=threshold, ts=ts
    )
    record_verdict(
        root,
        event_id=eid,
        correct=correct,
        ts=ts + 0.5,
        cam_id=cam,
        corrected_label=corrected_label,
    )


def _fill(root, n_true=30, n_false=30, cam="cam1", label="person"):
    """A stratum thick enough to clear every calibration bar."""
    for i in range(n_true):
        _judged(root, f"t{i}", cam=cam, label=label, score=0.9, correct=True, ts=float(i))
    for i in range(n_false):
        _judged(
            root,
            f"f{i}",
            cam=cam,
            label=label,
            score=0.6,
            correct=False,
            ts=float(100 + i),
        )


# ── the rollup ────────────────────────────────────────────────────────


def test_stats_group_by_camera_and_label(tmp_path):
    _judged(tmp_path, "a", cam="garden", label="squirrel")
    _judged(tmp_path, "b", cam="garden", label="person")
    _judged(tmp_path, "c", cam="drive", label="person")
    keys = {(s["cam"], s["label"]) for s in corpus_stats(tmp_path)["strata"]}
    assert keys == {("garden", "squirrel"), ("garden", "person"), ("drive", "person")}


def test_stats_count_unanswered_alerts_in_the_answer_rate(tmp_path):
    _judged(tmp_path, "answered")
    record_alert(
        tmp_path,
        cam_id="cam1",
        event_id="ignored",
        label="person",
        score=0.8,
        threshold=0.5,
        ts=9.0,
    )
    s = corpus_stats(tmp_path)["strata"][0]
    assert s["n_alerts"] == 2
    assert s["n_total"] == 1, "only the judged one is a corpus sample"
    assert s["answer_rate"] == 0.5


def test_stats_carry_the_label_corrections(tmp_path):
    """ "It was actually a dog" is the signal a label veto is built from."""
    _judged(tmp_path, "e1", correct=False, corrected_label="dog")
    assert corpus_stats(tmp_path)["strata"][0]["corrections"] == [("dog", 1)]


def test_stats_report_orphan_verdicts_separately(tmp_path):
    """A muted camera produces no alert record, but the web UI still
    judges the event. That verdict is real and must be visible, without
    being counted as a scored sample."""
    record_verdict(
        tmp_path,
        event_id="ghost",
        correct=False,
        ts=1.0,
        cam_id="garden",
        corrected_label="cat",
        source="web_labels",
    )
    stats = corpus_stats(tmp_path)
    assert stats["orphan_verdicts"] == 1
    assert stats["n_judged"] == 0, "no alert record means no scored pair"


def test_stats_on_an_empty_ledger_are_safe(tmp_path):
    stats = corpus_stats(tmp_path)
    assert stats["strata"] == []
    assert stats["n_alerts"] == 0
    assert stats["answer_rate"] == 0.0
    assert stats["centroid"]["ready"] is False


# ── refusal · threshold calibration ───────────────────────────────────


def test_a_thin_stratum_is_not_ready(tmp_path):
    for i in range(3):
        _judged(tmp_path, f"e{i}", correct=i == 0, ts=float(i))
    s = corpus_stats(tmp_path)["strata"][0]
    assert s["ready"] is False
    assert any(f"judged 3/{MIN_JUDGED_PER_STRATUM}" in b for b in s["blockers"])


def test_a_thick_stratum_is_ready(tmp_path):
    _fill(tmp_path)
    s = corpus_stats(tmp_path)["strata"][0]
    assert s["n_total"] >= MIN_JUDGED_PER_STRATUM
    assert s["ready"] is True
    assert s["blockers"] == []


def test_one_sided_evidence_is_never_ready(tmp_path):
    """Sixty confirmations and not one rejection cannot place a threshold."""
    _fill(tmp_path, n_true=60, n_false=0)
    s = corpus_stats(tmp_path)["strata"][0]
    assert s["ready"] is False
    assert any(f"confirmed-false 0/{MIN_JUDGED_PER_CLASS}" in b for b in s["blockers"])


def test_lowering_a_threshold_needs_judged_sub_threshold_candidates(tmp_path):
    _fill(tmp_path)
    assert corpus_stats(tmp_path)["strata"][0]["can_lower"] is False
    for i in range(MIN_JUDGED_PER_CLASS):
        record_alert(
            tmp_path,
            cam_id="cam1",
            event_id=f"low{i}",
            label="person",
            score=0.3,
            threshold=0.5,
            ts=float(500 + i),
        )
        record_verdict(tmp_path, event_id=f"low{i}", correct=True, ts=float(600 + i))
    assert corpus_stats(tmp_path)["strata"][0]["can_lower"] is True


# ── refusal · per-camera label veto ───────────────────────────────────


def test_a_veto_needs_more_than_a_high_wrong_rate(tmp_path):
    """Ten out of ten wrong is 100% — and a 95% lower bound that is not
    a basis for silencing a camera."""
    for i in range(10):
        _judged(tmp_path, f"e{i}", correct=False, ts=float(i))
    veto = corpus_stats(tmp_path)["strata"][0]["veto"]
    assert veto["wrong_rate"] == 1.0
    assert veto["ready"] is False
    assert any(f"judged 10/{MIN_JUDGED_FOR_VETO}" in b for b in veto["blockers"])


def test_a_veto_clears_once_the_sample_is_thick_enough(tmp_path):
    for i in range(28):
        _judged(tmp_path, f"f{i}", correct=False, ts=float(i))
    for i in range(2):
        _judged(tmp_path, f"t{i}", correct=True, ts=float(100 + i))
    veto = corpus_stats(tmp_path)["strata"][0]["veto"]
    assert veto["ready"] is True
    assert veto["wrong_rate_lower"] > 0.6


def test_a_mostly_right_stratum_is_never_vetoed(tmp_path):
    _fill(tmp_path, n_true=50, n_false=10)
    veto = corpus_stats(tmp_path)["strata"][0]["veto"]
    assert veto["ready"] is False


def test_a_redirect_needs_the_corrections_to_agree(tmp_path):
    """A stratum can be wrong often enough to veto and still have no
    replacement label: half "dog", half "cat" is not a redirect."""
    split = (MIN_AGREEING_CORRECTIONS - 1) * 2
    for i in range(MIN_JUDGED_FOR_VETO):
        _judged(
            tmp_path,
            f"e{i}",
            correct=False,
            ts=float(i),
            corrected_label=("dog", "cat")[i % 2] if i < split else None,
        )
    veto = corpus_stats(tmp_path)["strata"][0]["veto"]
    assert veto["ready"] is True, "the veto itself is justified"
    assert veto["redirect_to"] is None
    assert "agreeing corrections" in veto["redirect_blocker"]


# ── refusal · nearest-centroid classifier ─────────────────────────────


def test_one_class_is_never_enough_for_a_centroid():
    out = centroid_readiness({"person": 500})
    assert out["ready"] is False
    assert out["classes"] == ["person"]
    assert out["blockers"]


def test_a_centroid_needs_two_well_populated_classes():
    counts = {"person": MIN_EXAMPLES_PER_CLASS, "squirrel": MIN_EXAMPLES_PER_CLASS}
    out = centroid_readiness(counts)
    assert out["ready"] is True
    assert len(out["classes"]) >= MIN_CLASSES_FOR_CENTROID
    assert out["needs_crops_from"] == "CORP-2"


def test_a_correction_counts_as_an_example_of_the_corrected_class(tmp_path):
    _judged(tmp_path, "a", correct=True, ts=1.0)
    _judged(tmp_path, "b", correct=False, corrected_label="dog", ts=2.0)
    examples = corpus_stats(tmp_path)["centroid"]["examples"]
    assert examples == {"person": 1, "dog": 1}


# ── the rendered report ───────────────────────────────────────────────


def _report(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_report, "storage_root", lambda: tmp_path)
    return corpus_report.main().read_text(encoding="utf-8")


def test_the_report_refuses_on_a_thin_corpus(tmp_path, monkeypatch):
    _judged(tmp_path, "e1", correct=True)
    _judged(tmp_path, "e2", correct=False, ts=2.0)
    text = _report(tmp_path, monkeypatch)
    assert "NOT ENOUGH DATA" in text
    assert f"judged 2/{MIN_JUDGED_PER_STRATUM}" in text


def test_the_report_states_all_three_bars(tmp_path, monkeypatch):
    """An operator must be able to read the thresholds off the page
    rather than trust the word READY."""
    _judged(tmp_path, "e1")
    text = _report(tmp_path, monkeypatch)
    assert "Threshold calibration" in text
    assert "Per-camera label veto" in text
    assert "Nearest-centroid classifier" in text
    for n in (MIN_JUDGED_PER_STRATUM, MIN_JUDGED_FOR_VETO, MIN_EXAMPLES_PER_CLASS):
        assert str(n) in text


def test_the_report_endorses_a_thick_corpus(tmp_path, monkeypatch):
    _fill(tmp_path)
    text = _report(tmp_path, monkeypatch)
    assert "NOT ENOUGH DATA" not in text
    assert "enough data to calibrate a threshold" in text


def test_the_report_survives_an_empty_ledger(tmp_path, monkeypatch):
    text = _report(tmp_path, monkeypatch)
    assert "EMPTY CORPUS" in text


def test_the_report_names_the_retention_invariant(tmp_path, monkeypatch):
    """The report is where an operator learns what the sweep may delete."""
    _judged(tmp_path, "e1")
    text = _report(tmp_path, monkeypatch)
    assert "only an *unjudged alert*" in text


def test_the_report_does_not_touch_the_ledger(tmp_path, monkeypatch):
    from app.detection_feedback import ledger_path

    _fill(tmp_path, n_true=3, n_false=3)
    before = ledger_path(tmp_path).read_bytes()
    _report(tmp_path, monkeypatch)
    assert ledger_path(tmp_path).read_bytes() == before
