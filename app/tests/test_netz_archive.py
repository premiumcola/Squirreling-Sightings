"""The archive: what it captures, when, and what it outlives.

Three properties carry the whole design:

* the record is written AT ASK TIME with the threshold state of that
  instant — capturing it when the answer arrives would record the wrong
  numbers and nobody would ever notice;
* it outlives the event it describes, image included;
* an answer that changed nothing is recorded as "bestätigt, keine
  Änderung" rather than omitted.
"""

from __future__ import annotations

import json
import time

import pytest

from app import net_archive
from app.net_archive import _io, _retention

CAM = "cam_werkstatt"


def _capture(root, eid, *, push=0.85, verdict=None, ts=None, kind=None):
    net_archive.capture(
        root,
        event_id=eid,
        cam_id=CAM,
        cam_name="Werkstatt",
        kind=kind or net_archive.KIND_FRAGE,
        detection={"label": "person", "score": 0.62, "all": []},
        net_state={
            "person": {
                "E": 50,
                "spawn": 0.45,
                "push": push,
                "source": {"push": "camera"},
                "provenance": "werk",
                "evidence": {"judged": 3, "ready": False},
            }
        },
        rails={"push": [0.45, 0.98]},
        asked=True,
    )
    if ts is not None:
        rec = _io.load_record(root, eid)
        rec["ts"] = ts
        _io.save_record(root, eid, rec)
    if verdict:
        net_archive.append_verdict(root, eid, value=verdict, source="telegram_q")


# ── capture ───────────────────────────────────────────────────────────


def test_the_record_carries_the_threshold_state_of_the_ask_moment(tmp_storage_root):
    _capture(tmp_storage_root, "e1", push=0.85)
    # The learner moves on — but the record must not.
    _capture(tmp_storage_root, "e2", push=0.77)
    assert net_archive.get_record(tmp_storage_root, "e1")["net_state"]["person"]["push"] == 0.85
    assert net_archive.get_record(tmp_storage_root, "e2")["net_state"]["person"]["push"] == 0.77


def test_the_record_names_the_ladder_layer_that_won(tmp_storage_root):
    """Not a second reading of the config — the layer the pipeline used."""
    _capture(tmp_storage_root, "e1")
    rec = net_archive.get_record(tmp_storage_root, "e1")
    assert rec["net_state"]["person"]["source"]["push"] == "camera"


def test_a_card_is_never_blank_before_the_night_job_runs(tmp_storage_root):
    _capture(tmp_storage_root, "e1")
    cons = net_archive.get_record(tmp_storage_root, "e1")["consequence"]
    assert cons["state"] == net_archive.STATE_PENDING
    assert cons["reason_de"]


def test_the_record_lives_outside_the_event_tree(tmp_storage_root):
    """`cleanup_old` deletes by age INSIDE motion_detection/. An archive
    living there would dissolve at 14 days — exactly when it becomes
    historically interesting."""
    _capture(tmp_storage_root, "20260828-141233-874512")
    path = _io.record_path(tmp_storage_root, "20260828-141233-874512")
    assert "motion_detection" not in path.parts
    assert path.parent.name == "2026-08"


def test_an_archive_entry_survives_a_retention_sweep_of_its_event(tmp_storage_root):
    """The moment the operator judged must still have a record and a
    picture when the clip, the snapshot and the event JSON are gone."""
    eid = "20260828-141233-874512"
    day = tmp_storage_root / "motion_detection" / CAM / "2026-08-28"
    day.mkdir(parents=True)
    (day / f"{eid}.json").write_text("{}", encoding="utf-8")
    (day / f"{eid}.jpg").write_bytes(b"jpegish")
    _capture(tmp_storage_root, eid, verdict=net_archive.VERDICT_WRONG)
    # A retention sweep takes the whole day folder.
    for p in sorted(day.iterdir()):
        p.unlink()
    day.rmdir()
    rec = net_archive.get_record(tmp_storage_root, eid)
    assert rec is not None
    assert rec["verdict"]["value"] == net_archive.VERDICT_WRONG
    assert rec["net_state"]["person"]["push"] == 0.85


# ── the durable event-context fallback ────────────────────────────────


def test_a_late_answer_still_finds_its_camera_and_class(tmp_storage_root):
    """`runtime.alert_index` is an LRU of 200. Past that, the archive is
    where cam and label come from — and it outlives the LRU by design."""
    _capture(tmp_storage_root, "late-1")
    ctx = net_archive.find_event_context(tmp_storage_root, "late-1")
    assert ctx["cam"] == CAM
    assert ctx["label"] == "person"


def test_an_orphaned_verdict_reads_its_score_from_the_archive(tmp_storage_root):
    """MANDATORY #5. Compaction may drop an unjudged alert row at
    MAX_UNJUDGED_PER_STRATUM. A later tap then makes a verdict with no
    alert to join to — recorded, but score-less and therefore silent for
    calibration. The archive record carries the score."""
    _capture(tmp_storage_root, "orphan-1")
    ctx = net_archive.find_event_context(tmp_storage_root, "orphan-1")
    assert ctx["score"] == 0.62


def test_a_missing_record_is_none_not_an_exception(tmp_storage_root):
    assert net_archive.find_event_context(tmp_storage_root, "nope") is None
    assert net_archive.get_record(tmp_storage_root, "nope") is None


# ── retention ─────────────────────────────────────────────────────────


def test_unjudged_records_are_evicted_before_judged_ones(tmp_storage_root):
    """A judged record is a picture a person looked at and a button they
    tapped. An unjudged one is reproducible by waiting."""
    records = []
    for i in range(net_archive.MAX_RECORDS + 10):
        eid = f"20260828-1412{i:02d}-000000"
        judged = i < 20
        records.append((eid, {"ts": f"2026-08-28T10:{i % 60:02d}:00", "verdict": {} if judged else None}))
    evict = _retention.select_evictable(records)
    assert len(evict) == 10
    judged_ids = {eid for eid, rec in records if rec.get("verdict")}
    assert not (set(evict) & judged_ids)


def test_anything_past_the_age_cap_goes_judged_or_not(tmp_storage_root):
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 800 * 86400))
    records = [("ancient", {"ts": old, "verdict": {"value": "richtig"}})]
    assert _retention.select_evictable(records) == ["ancient"]


def test_an_unparsable_timestamp_never_triggers_a_deletion(tmp_storage_root):
    """A broken field is not evidence of age."""
    assert _retention.select_evictable([("weird", {"ts": "not-a-date"})]) == []


def test_enforce_removes_the_record_and_its_frame(tmp_storage_root):
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 800 * 86400))
    _capture(tmp_storage_root, "20240101-120000-000000", ts=old)
    frame = _io.frame_path(tmp_storage_root, "20240101-120000-000000")
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"x")
    assert _retention.enforce(tmp_storage_root) == 1
    assert not frame.exists()


# ── the browse page ───────────────────────────────────────────────────


def test_the_header_stat_counts_answers_and_movements(tmp_storage_root):
    """"Von 84 Antworten haben 11 einen Wert bewegt" is the audit
    sentence the whole feature exists to be able to print."""
    _capture(tmp_storage_root, "a1", verdict=net_archive.VERDICT_RIGHT)
    _capture(tmp_storage_root, "a2", verdict=net_archive.VERDICT_WRONG)
    _capture(tmp_storage_root, "a3")
    net_archive.append_consequence(
        tmp_storage_root,
        "a2",
        {"state": net_archive.STATE_CHANGED, "reason_de": "bewegt"},
    )
    page = net_archive.list_records(tmp_storage_root)
    assert page["total"] == 3
    assert page["answered"] == 2
    assert page["moved"] == 1
    assert page["unjudged"] == 1


def test_the_open_filter_shows_exactly_the_unjudged(tmp_storage_root):
    _capture(tmp_storage_root, "b1", verdict=net_archive.VERDICT_RIGHT)
    _capture(tmp_storage_root, "b2")
    page = net_archive.list_records(tmp_storage_root, only_open=True)
    assert [r["event_id"] for r in page["items"]] == ["b2"]


def test_every_row_carries_a_badge_never_silence(tmp_storage_root):
    _capture(tmp_storage_root, "c1")
    row = net_archive.list_records(tmp_storage_root)["items"][0]
    assert row["badge"] == net_archive.STATE_BADGE[net_archive.STATE_PENDING]


def test_a_manual_drag_gets_its_own_record_with_no_image(tmp_storage_root):
    net_archive.record_net_change(
        tmp_storage_root,
        event_id="netz-1",
        cam_id=CAM,
        cam_name="Werkstatt",
        label="person",
        e_before=50,
        e_after=62,
        push_before=0.85,
        push_after=0.78,
        net_state={},
        rails={},
    )
    rec = net_archive.get_record(tmp_storage_root, "netz-1")
    assert rec["kind"] == net_archive.KIND_NETZ
    assert "von 50 auf 62" in rec["consequence"]["reason_de"]
    assert "85 %" in rec["consequence"]["reason_de"]
    assert not _io.frame_path(tmp_storage_root, "netz-1").exists()


# ── the German sentences ──────────────────────────────────────────────


def test_pooled_evidence_says_so_in_words(tmp_storage_root):
    """P3 · a recommendation from the pooled stratum must not present
    itself as a per-camera one."""
    text = net_archive.sentence_confirmed(push=0.74, scope=net_archive.SCOPE_POOLED)
    assert "aus allen Kameras zusammengerechnet" in text


def test_a_held_person_floor_is_stated_not_hidden(tmp_storage_root):
    text = net_archive.sentence_changed(
        label="person",
        cam_name="Werkstatt",
        n_verdicts=52,
        push_before=0.85,
        push_after=0.82,
        blocked_false=9,
        n_false=12,
        kept_true=31,
        n_true=31,
        floor_held={"wanted": 28, "floor": 35},
    )
    assert "Sicherheitsgrenze für Person liegt bei 35" in text
    assert "nicht angewandt" in text


def test_the_pending_sentence_names_the_bar_it_is_counting_towards(tmp_storage_root):
    text = net_archive.sentence_pending(
        label="person", cam_name="Werkstatt", judged=24, needed=50
    )
    assert "24 von 50" in text


@pytest.mark.parametrize(
    "state",
    [
        net_archive.STATE_CHANGED,
        net_archive.STATE_CONFIRMED,
        net_archive.STATE_PENDING,
        net_archive.STATE_OUTVOTED,
        net_archive.STATE_PINNED,
    ],
)
def test_every_state_has_a_badge(state):
    assert net_archive.STATE_BADGE[state]


def test_the_record_is_json_round_trippable(tmp_storage_root):
    _capture(tmp_storage_root, "j1", verdict=net_archive.VERDICT_OTHER)
    raw = _io.record_path(tmp_storage_root, "j1").read_text(encoding="utf-8")
    assert json.loads(raw)["verdict"]["value"] == net_archive.VERDICT_OTHER
