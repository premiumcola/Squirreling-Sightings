""" "Debug kopieren" produces a document for a machine, not a reader.

The operator's own account of what happens to it: "ich schau mir den ja
nie manuell an, ich paste den immer nur zum Debuggen ins Codefenster."
A paste with exactly one destination should be shaped for that
destination — stable keys, units in the key name, raw typed values, and
no German sentence with a number buried inside it.

Two properties are load-bearing and both are pinned below:

  · the SCREEN is unchanged. The Debug tab renders `findings`, which is
    a separate field of the same response — the operator still reads
    "tote Zone 0.45–0.85" on the phone.
  · the Markdown rendering survives (``GET …/debug-snapshot`` without
    ``format=json``) and may not drift away from the JSON one. Both are
    built from one extraction in ``build_snapshot``; ``SECTION_KEYS`` is
    the map between them and the drift guard below reads it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.routes._debug_snapshot import SCHEMA, SECTION_KEYS, build_snapshot

_COPY = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "web"
    / "static"
    / "js"
    / "mediaview"
    / "live-detect-debug"
    / "_copy-bar.js"
)

CAM_ID = "reolink_cx810_hof_42"

PUSH_CFG = {
    "telegram": {"push": {"labels": {"person": {"push": True, "threshold": 0.85}}}},
    "processing": {"wildlife": {"min_score": 0.35}},
}


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
        "detections": [
            {"label": "person", "score": 0.65, "verdict": "pass", "track_num": 1},
            {"label": "cat", "score": 0.21, "verdict": "tentative"},
        ],
        "trace": ["[capture] frame 640x360"],
        "frame_size": {"w": 640, "h": 360},
        "frame_age_ms": 120,
        "diag": {"frame_src": "sub", "inference_ms": 42, "frame_interval_avg_ms": 369},
        "cluster_evidence": {"cluster4": {"tick_cycle_ema_ms": 369}},
    }
    tick.update(over)
    return {"last_tick": tick}


def _snap(cam=None, tt=None, runtime=None, eff=None):
    return build_snapshot(
        cam=cam or _cam(),
        cam_id=CAM_ID,
        tt=tt if tt is not None else _tt(),
        runtime=runtime,
        eff_cfg=eff if eff is not None else PUSH_CFG,
    )


# ── the shape ────────────────────────────────────────────────────────


def test_the_document_names_its_own_schema():
    """A consumer that meets a version it does not know should be able to
    say so rather than read a renamed field as null."""
    doc = _snap()["doc"]
    assert doc["schema"] == SCHEMA
    assert re.match(r"^[a-z.\-]+/\d+$", SCHEMA), f"unversioned schema id: {SCHEMA!r}"


def test_the_whole_document_round_trips_through_json():
    """It is written to a file and pasted into a code window; anything
    that is not JSON-serialisable (a dataclass, a datetime, a set) breaks
    both destinations at once."""
    doc = _snap()["doc"]
    assert json.loads(json.dumps(doc, ensure_ascii=False)) == doc


def test_numbers_are_numbers_and_not_sentences():
    """The Markdown says "0.00 (0 → global processing.wildlife.min_score
    = 0.35)". Useful to read, impossible to compare."""
    doc = _snap()["doc"]
    motion = doc["motion"]
    assert isinstance(motion["wildlife_min_score"], float)
    assert motion["wildlife_min_score"] == 0.0
    # …and the fallback the prose explained is resolved into its own key.
    assert motion["wildlife_min_score_effective"] == 0.35
    assert motion["wildlife_min_score_source"] == "global"
    assert isinstance(doc["tick"]["inference_ms"], int)
    assert isinstance(doc["performance"]["tick_cycle_ema_ms"], int)


def test_a_schedule_is_three_facts_rather_than_one_german_sentence():
    doc = _snap(_cam(schedule_notify={"enabled": True, "from": "22:00", "to": "06:00"}))["doc"]
    notify = doc["gates"]["schedule_notify"]
    assert notify["gates"] is True
    assert (notify["from"], notify["to"]) == ("22:00", "06:00")
    assert notify["active_now"] in (True, False)
    # An absent schedule gates nothing — and says so as a boolean, not as
    # the string "24/7 (nicht konfiguriert)".
    assert doc["gates"]["schedule_record"] == {
        "gates": False,
        "from": None,
        "to": None,
        "active_now": True,
    }


def test_the_dead_zone_survives_the_dataclass_dump():
    """``dead_zone`` is a property on EffectiveThresholds, so asdict()
    drops it — and it is the single most diagnostic bit in the document
    (the shipped person config, spawn 0.45 / push 0.85, IS one)."""
    rows = _snap()["doc"]["ladder"]
    person = next(r for r in rows if r["label"] == "person")
    assert person["dead_zone"] is True
    assert person["spawn"] == 0.45 and person["push"] == 0.85
    assert person["source"]["push"], "the ladder must say where each bar came from"


def test_detections_are_grouped_by_the_verdict_that_decided_them():
    dets = _snap()["doc"]["detections"]
    assert [d["label"] for d in dets["pass"]] == ["person"]
    assert [d["label"] for d in dets["tentative"]] == ["cat"]
    assert dets["pass"][0]["score"] == 0.65


# ── the honesty conventions carry over from the Markdown ─────────────


def test_frontend_only_values_are_null_and_not_zero():
    """The scheduler that owns them runs in the browser. 0 would read as
    "no delay", which is a different claim from "not knowable here"."""
    tick = _snap()["doc"]["tick"]
    assert tick["next_ms"] is None
    assert tick["hold_ms"] is None
    assert _snap()["doc"]["frontend"] == {}


def test_an_unmeasured_counter_is_null_with_a_reason_not_a_fabricated_zero():
    """``sub_stream_fps: 0.0`` reads as "the stream is dead" and sends the
    operator hunting a camera fault that does not exist. There is no
    ``_sub_fps`` counter anywhere in camera_runtime."""

    class _Runtime:
        _main_fps = 7.4

    perf = _snap(runtime=_Runtime())["doc"]["performance"]
    assert perf["main_stream_fps"] == 7.4
    assert perf["main_stream_fps_state"] == "ok"
    assert perf["sub_stream_fps"] is None
    assert perf["sub_stream_fps_state"] == "not_measured"
    # No runtime at all is a third state, and not the same as either.
    assert _snap()["doc"]["performance"]["main_stream_fps_state"] == "no_runtime"


def test_an_unset_tracker_override_is_null_not_a_zero_threshold():
    """0.0 is the schema's "keep the tracker_core default" marker; a bare
    0.00 would claim the tracker accepts anything."""
    tracker = _snap()["doc"]["tracker"]
    assert tracker["track_spawn_min_score"] is None
    assert _snap(_cam(track_spawn_min_score=0.3))["doc"]["tracker"]["track_spawn_min_score"] == 0.3


def test_the_log_block_never_carries_a_password(monkeypatch):
    """The document is pasted into a chat window AND written to disk."""

    class _Buf:
        def get(self, _level):
            return [
                {
                    "ts": "12:00:01",
                    "level": "ERROR",
                    "msg": f"[cam:{CAM_ID}] open rtsp://admin:hunter2@cam.lan/h264",
                }
            ]

    monkeypatch.setattr("app.routes._debug_snapshot._helpers.log_buffer", _Buf())
    doc = _snap()["doc"]
    blob = json.dumps(doc)
    assert "hunter2" not in blob
    assert "admin:•••@cam.lan" in doc["log"][0]["msg"]


# ── the two renderings may not drift apart ───────────────────────────


def test_every_markdown_section_has_a_key_in_the_document():
    """One dataset, two renderings, different code. This is the guard
    that turns "someone added a section to only one of them" into a test
    failure instead of a discovery six months later."""
    snap = _snap()
    headings = re.findall(r"^## (.+)$", snap["markdown"], re.MULTILINE)
    assert headings, "the Markdown rendering lost its sections"
    missing = [h for h in headings if h not in SECTION_KEYS]
    assert not missing, f"Markdown sections with no JSON counterpart: {missing}"
    absent = [key for key in SECTION_KEYS.values() if key not in snap["doc"]]
    assert not absent, f"SECTION_KEYS names keys the document does not build: {absent}"


def test_screen_paste_and_markdown_share_one_findings_list():
    """Three surfaces, one server-computed diagnosis. A second
    client-side implementation would drift the moment a rule changed."""
    snap = _snap(_cam(armed=False))
    assert snap["doc"]["findings"] is not snap["findings"]  # copied, not aliased
    assert snap["doc"]["findings"] == snap["findings"]
    assert snap["findings"][0]["text"] in snap["markdown"]


# ── the browser copies the JSON, and only the JSON ───────────────────


def test_the_clipboard_gets_the_document_not_the_prose():
    src = _COPY.read_text(encoding="utf-8")
    assert "data.doc" in src, "the copy path must cache the machine document"
    assert "JSON.stringify(payload, null, 2)" in src, "indented so two runs diff cleanly"
    assert "data.markdown" not in src, "the German report is no longer the copy payload"


def test_a_failed_archive_is_not_swallowed():
    """The archive exists so the operator can STOP pasting runs into a
    chat. Failing silently would leave them believing a run is on the box
    when it is not — the one outcome worse than not having the feature."""
    src = _COPY.read_text(encoding="utf-8")
    body = src[src.index("function _archiveRun") : src.index("export function _wireCopyBar")]
    assert "NICHT gesichert" in body, "a failed archive has to reach the screen"
    assert "j.ok !== true" in body, "a 200 carrying ok:false is still a failure"
    assert ".catch(" in body, "…and so is a dead network"


def test_the_copy_is_still_written_inside_the_gesture():
    """iOS Safari revokes clipboard access across an await boundary — the
    JSON switch must not have introduced one, and the archive POST must
    sit AFTER the write."""
    src = _COPY.read_text(encoding="utf-8")
    click = src[src.index("btn.addEventListener('click'") :]
    click = click[: click.index("\n}")]
    code = "\n".join(ln for ln in click.splitlines() if not ln.strip().startswith("//"))
    assert "await" not in code
    assert code.index("writeText") < code.index("_archiveRun"), (
        "the clipboard is the primary path — the archive write must never "
        "be able to delay or break it"
    )
