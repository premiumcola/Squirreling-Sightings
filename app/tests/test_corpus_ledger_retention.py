"""The corpus stays bounded WITHOUT losing what a human produced.

The ledger used to bound itself by renaming the live file over the
previous generation: two rotations and everything older was gone,
judgements included. The first attempt at fixing that replaced the
rename with a stratified compaction and introduced three new ways to
destroy data:

* a verdict whose event has **no alert record** was deleted outright.
  Not a corner case — ``record_alert`` sits below the mute and push-flag
  gates in the Telegram chain, so a muted camera or a label with
  ``push: false`` produces no alert record at all, while the web
  surfaces (FB-1) write a verdict for every confirm, label correction
  and delete. The cleanup would have destroyed exactly the corpus it
  existed to preserve.
* a record of any **unrecognised kind** was silently dropped, so the
  next record type anyone adds dies at the first compaction.
* eviction was **uncounted**, so the answer rate was computed over
  what survived retention — and retention keeps judged records while
  dropping unjudged ones. The rate therefore rose with every
  compaction and the "have we got enough data?" gate could never
  honestly say no.

These tests pin the invariant that removes all three:

    **An automatic sweep may delete only an unjudged alert, it evicts
    per (camera, label), and every eviction is counted.**
"""

from __future__ import annotations

import json

from app.detection_feedback import (
    archive_path,
    compact_ledger,
    corpus_stats,
    iter_records,
    judged_alerts,
    ledger_health,
    ledger_path,
    record_alert,
    record_verdict,
    select_retained,
)


def _alert_rec(eid, cam="cam1", label="person", ts=1.0, score=0.7):
    return {
        "kind": "alert",
        "ts": ts,
        "cam": cam,
        "event_id": eid,
        "label": label,
        "score": score,
        "threshold": 0.5,
        "passed_threshold": True,
        "detections": [],
    }


def _verdict_rec(eid, correct=True, ts=2.0, corrected_label=None, cam=None):
    return {
        "kind": "verdict",
        "ts": ts,
        "event_id": eid,
        "cam": cam,
        "correct": correct,
        "corrected_label": corrected_label,
        "source": "telegram",
    }


def _census(kept):
    return {(r["cam"], r["label"]): r["evicted_alerts"] for r in kept if r["kind"] == "census"}


# ── blocker 1 · a human judgement is never deleted ────────────────────


def test_a_verdict_whose_alert_is_missing_survives():
    """The rejected implementation deleted every one of these.

    `record_alert` is written below the mute and push-flag gates, so a
    muted camera or a `push: false` label produces no alert record —
    yet the web UI still books confirm / label-correction / delete
    verdicts against those events. Their `corrected_label` is the whole
    signal a per-camera label veto is built from.
    """
    orphan = _verdict_rec("ghost", correct=False, corrected_label="dog", cam="garden")
    kept = select_retained([orphan])
    assert kept == [orphan]


def test_a_flood_of_unjudged_alerts_cannot_evict_an_orphan_verdict():
    records = [_verdict_rec("ghost", corrected_label="dog", ts=1.0)]
    records += [_alert_rec(f"n{i}", ts=100.0 + i) for i in range(500)]
    kept = select_retained(records, max_records=10, max_unjudged_per_stratum=500)
    assert any(r.get("event_id") == "ghost" for r in kept)


def test_a_judged_alert_is_never_evicted_by_the_record_budget():
    """The budget governs the evictable pool only, and judged records are
    not in it. A corpus with more judgements than the budget overflows it
    rather than losing them."""
    records = [_alert_rec(f"a{i}", ts=i) for i in range(500)]
    records += [_verdict_rec(f"a{i}", ts=1000 + i) for i in range(500)]

    kept = select_retained(records, max_records=40, max_unjudged_per_stratum=1000)
    assert len(kept) == 1000, "500 alerts + 500 verdicts, all human-judged"
    assert not _census(kept), "nothing was evicted, so nothing to count"


# ── blocker 2 · the answer rate stays honest ──────────────────────────


def test_every_evicted_alert_is_counted_into_a_census():
    records = [_alert_rec(f"a{i}", ts=i) for i in range(500)]
    kept = select_retained(records, max_records=10, max_unjudged_per_stratum=1000)
    assert _census(kept) == {("cam1", "person"): 490}
    assert sum(1 for r in kept if r["kind"] == "alert") == 10


def test_the_census_is_per_stratum():
    records = [_alert_rec(f"a{i}", cam="drive", ts=i) for i in range(100)]
    records += [_alert_rec(f"b{i}", cam="garden", label="squirrel", ts=i) for i in range(4)]
    kept = select_retained(records, max_records=1000, max_unjudged_per_stratum=10)
    assert _census(kept) == {("drive", "person"): 90}


def test_recompacting_the_same_content_does_not_double_count():
    """Compaction must be idempotent, or the denominator drifts every
    time the sweep runs."""
    records = [_alert_rec(f"a{i}", ts=i) for i in range(50)]
    once = select_retained(records, max_records=10, max_unjudged_per_stratum=100)
    twice = select_retained(once, max_records=10, max_unjudged_per_stratum=100)
    assert _census(once) == _census(twice) == {("cam1", "person"): 40}


def test_the_answer_rate_counts_alerts_that_were_evicted(tmp_path):
    """The regression the min-data gate depended on.

    One judged alert and a hundred unjudged ones, of which ninety were
    already swept away. Counting only what is on disk reports a 9%
    answer rate; the truth is under 1%.
    """
    lines = [_alert_rec("judged", ts=1.0), _verdict_rec("judged", ts=2.0)]
    lines += [_alert_rec(f"u{i}", ts=10.0 + i) for i in range(10)]
    lines.append(
        {"kind": "census", "ts": 99.0, "cam": "cam1", "label": "person", "evicted_alerts": 90}
    )
    path = ledger_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(rec) + "\n" for rec in lines),
        encoding="utf-8",
    )

    stats = corpus_stats(tmp_path)
    assert stats["n_alerts"] == 101, "11 on disk + 90 evicted"
    assert stats["n_judged"] == 1
    assert stats["answer_rate"] == round(1 / 101, 3)
    st = stats["strata"][0]
    assert st["n_alerts_evicted"] == 90
    assert st["ready"] is False
    assert any("answer rate" in b for b in st["blockers"])


# ── blocker 3 · an unknown kind is carried, not destroyed ─────────────


def test_a_record_of_an_unknown_kind_survives_compaction():
    """Dropping data because a newer writer produced it is how a corpus
    quietly loses the thing that mattered."""
    future = {"kind": "gate_trace", "ts": 5.0, "cam": "cam1", "blocked_by": "cooldown"}
    kept = select_retained([_alert_rec("e1", ts=1.0), future])
    assert future in kept


def test_unknown_kinds_are_not_evictable_either():
    records = [{"kind": "gate_trace", "ts": float(i)} for i in range(50)]
    kept = select_retained(records, max_records=5, max_unjudged_per_stratum=5)
    assert len(kept) == 50


# ── representativeness ────────────────────────────────────────────────


def test_a_rare_stratum_is_not_evicted_by_a_common_one():
    """Round-robin, not newest-first: three records must survive 5000."""
    records = [_alert_rec(f"rare{i}", cam="garden", label="squirrel", ts=i) for i in range(3)]
    records += [
        _alert_rec(f"common{i}", cam="drive", label="person", ts=1000 + i) for i in range(5000)
    ]
    kept = select_retained(records, max_records=100, max_unjudged_per_stratum=100)
    survivors = {r.get("event_id") for r in kept}
    assert {"rare0", "rare1", "rare2"} <= survivors
    assert sum(1 for r in kept if r["kind"] == "alert") <= 100


def test_the_unjudged_quota_is_per_stratum():
    records = [_alert_rec(f"a{i}", cam="drive", ts=i) for i in range(500)]
    records += [_alert_rec(f"b{i}", cam="garden", label="squirrel", ts=i) for i in range(2)]
    kept = select_retained(records, max_records=10000, max_unjudged_per_stratum=30)
    per_cam = {}
    for r in kept:
        if r["kind"] == "alert":
            per_cam[r["cam"]] = per_cam.get(r["cam"], 0) + 1
    assert per_cam["drive"] == 30, "the loud stratum is capped"
    assert per_cam["garden"] == 2, "the quiet one keeps everything it has"


def test_a_superseded_verdict_is_dropped():
    records = [
        _alert_rec("e1"),
        _verdict_rec("e1", correct=True, ts=5),
        _verdict_rec("e1", correct=False, ts=6),
    ]
    verdicts = [r for r in select_retained(records) if r["kind"] == "verdict"]
    assert len(verdicts) == 1
    assert verdicts[0]["correct"] is False


def test_retention_output_is_chronological():
    records = [_alert_rec("b", ts=20), _alert_rec("a", ts=10), _verdict_rec("a", ts=15)]
    kept = select_retained(records)
    assert [r.get("ts") for r in kept] == [10, 15, 20]


# ── end to end, through the writer ────────────────────────────────────


def test_a_judged_record_survives_a_flood_of_unjudged_ones(tmp_path, monkeypatch):
    """One judged `squirrel` on the garden camera, then hundreds of
    unjudged `person` alerts from the driveway — enough to roll the
    ledger over many times. The judgement must still be there."""
    monkeypatch.setattr("app.detection_feedback._MAX_BYTES", 4000)
    record_alert(
        tmp_path,
        cam_id="garden",
        event_id="rare",
        label="squirrel",
        score=0.71,
        threshold=0.5,
        ts=1.0,
    )
    record_verdict(tmp_path, event_id="rare", correct=True, ts=2.0, cam_id="garden")
    for i in range(400):
        record_alert(
            tmp_path,
            cam_id="drive",
            event_id=f"noise{i}",
            label="person",
            score=0.9,
            threshold=0.5,
            ts=100.0 + i,
        )

    pairs = judged_alerts(tmp_path, cam_id="garden", label="squirrel")
    assert [a["event_id"] for a, _ in pairs] == ["rare"]
    assert pairs[0][1] is True


def test_the_flood_itself_stays_bounded_and_is_counted(tmp_path, monkeypatch):
    """Keeping the rare records must not mean keeping everything — and
    what is dropped must show up in the answer-rate denominator."""
    monkeypatch.setattr("app.detection_feedback._MAX_BYTES", 4000)
    monkeypatch.setattr("app.detection_feedback.MAX_UNJUDGED_PER_STRATUM", 20)
    for i in range(400):
        record_alert(
            tmp_path,
            cam_id="drive",
            event_id=f"noise{i}",
            label="person",
            score=0.9,
            threshold=0.5,
            ts=100.0 + i,
        )

    assert ledger_health(tmp_path)["live_bytes"] <= 4000 * 2
    kinds = [r.get("kind") for r in iter_records(tmp_path)]
    assert kinds.count("alert") < 400
    stats = corpus_stats(tmp_path)
    assert stats["n_alerts_evicted"] > 0
    assert stats["n_alerts"] == 400, "every alert ever written is still counted"


def test_compaction_leaves_every_line_parseable(tmp_path, monkeypatch):
    monkeypatch.setattr("app.detection_feedback._MAX_BYTES", 2000)
    for i in range(200):
        record_alert(
            tmp_path,
            cam_id="cam1",
            event_id=f"e{i}",
            label="person",
            score=0.5,
            threshold=0.4,
            ts=float(i),
        )
    archive = archive_path(ledger_path(tmp_path))
    assert archive.exists(), "a compaction should have produced an archive"
    for line in archive.read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_compaction_uses_the_shared_atomic_writer(tmp_path, monkeypatch):
    """`storage._atomic_write_text` already does temp-file + fsync +
    os.replace with a per-writer temp name. A second hand-rolled copy is
    a divergence waiting to happen."""
    import app.storage as storage

    calls = []
    real = storage._atomic_write_text

    def _spy(path, text):
        calls.append(path)
        return real(path, text)

    monkeypatch.setattr(storage, "_atomic_write_text", _spy)
    record_alert(
        tmp_path,
        cam_id="cam1",
        event_id="e1",
        label="person",
        score=0.5,
        threshold=0.4,
        ts=1.0,
    )
    compact_ledger(tmp_path)

    assert calls == [archive_path(ledger_path(tmp_path))]
    assert not list(ledger_path(tmp_path).parent.glob("*.tmp")), "no temp file left behind"


def test_compaction_on_an_empty_ledger_is_safe(tmp_path):
    assert compact_ledger(tmp_path) == {"read": 0, "retained": 0}


# ── health ────────────────────────────────────────────────────────────


def test_health_reports_fill_and_quotas_on_an_empty_ledger(tmp_path):
    health = ledger_health(tmp_path)
    assert health["live_bytes"] == 0
    assert health["compacted"] is False
    assert health["max_unjudged_per_stratum"] > 0
    assert health["rotate_at_bytes"] > 0


def test_health_tracks_the_live_file(tmp_path):
    record_alert(
        tmp_path,
        cam_id="cam1",
        event_id="e1",
        label="person",
        score=0.5,
        threshold=0.4,
        ts=1.0,
    )
    health = ledger_health(tmp_path)
    assert health["live_bytes"] > 0
    assert health["total_bytes"] == health["live_bytes"] + health["archive_bytes"]
    assert 0 < health["live_fill"] < 1
