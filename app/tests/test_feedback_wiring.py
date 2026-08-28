"""The ledger must actually be called from the send and verdict paths.

The module can be perfect and still useless if nothing writes to it.
This is exactly how the existing surfaces ended up dead: `confirmed` has
no reader, `/review` has no caller, and the Telegram verdict stores
`{verdict, by, ts}` with no camera, label or score — each one a correct
piece of code wired to nothing.

These tests pin the wiring, and pin the two properties that make the
record useful: the score and the threshold have to travel with it.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "app"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


#: The ``ev:*`` callbacks moved out of `_inbound.py` when the question's
#: three new branches would have pushed that file 350 lines past the
#: ceiling. The wiring is the same; only its address changed.
_VERDICT_MODULE = "telegram_bot/_inbound_event.py"


def _read_outbound() -> str:
    """The push path is a package (HYG-2 split it along its concerns), so
    the wiring is pinned against the package as a whole rather than one
    file inside it. The ordering assertion below still means what it
    says: both of its needles live in the same module."""
    pkg = SRC / "telegram_bot" / "_outbound"
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(pkg.glob("*.py")))


def test_send_path_records_the_alert():
    src = _read_outbound()
    assert "from ...detection_feedback import record_alert" in src
    assert "record_alert(" in src


def test_alert_record_carries_score_and_threshold():
    """Without these two the record cannot calibrate anything — which is
    precisely why the pre-existing runtime alert-index was useless."""
    src = _read_outbound()
    call = src[src.index("record_alert(") : src.index("record_alert(") + 600]
    assert "score=top_score" in call
    assert "threshold=threshold" in call
    assert "cam_id=camera_id" in call
    assert "detections=detections" in call


def test_verdict_path_records_the_judgement():
    src = _read(_VERDICT_MODULE)
    assert "from ..detection_feedback import record_verdict" in src
    assert "record_verdict(" in src


def test_verdict_record_carries_the_camera():
    """Joined from the alert index — or, once the LRU has dropped it,
    from the archive record, which outlives it by design."""
    src = _read(_VERDICT_MODULE)
    call = src[src.index("record_verdict(") : src.index("record_verdict(") + 400]
    assert "cam_id=" in call
    assert "source=source" in call


def test_both_writes_are_best_effort():
    """Bookkeeping must never drop a real alert or break a callback."""
    out = _read_outbound()
    inb = _read(_VERDICT_MODULE)
    for src, needle in ((out, "record_alert("), (inb, "record_verdict(")):
        before = src[: src.index(needle)]
        tail = before[-400:]
        assert "contextlib.suppress(Exception)" in tail, (
            f"{needle} must be guarded — a diagnostic write cannot be allowed "
            "to propagate into the alert path"
        )


def test_verdict_is_written_alongside_the_settings_entry_not_instead():
    """The settings entry drives the 'already rated' badge in the chat;
    removing it would change user-visible behaviour, so the ledger is
    additive until that badge has another source."""
    src = _read(_VERDICT_MODULE)
    assert '"event_feedback"' in src
    # LRU-bounded: it is a dedupe guard, and an unbounded one grows
    # settings.json by an entry per judged event forever.
    assert "runtime_set_subkey_lru(" in src


# ── the record must sit ABOVE the gates ───────────────────────────────


def test_alert_is_recorded_before_the_push_gate():
    """The defect this guards against is subtle and total.

    Recorded after the gates, the ledger only ever contains events that
    cleared the threshold — for `person` nothing below 0.85. Calibration
    on that data could raise a threshold and never lower one, which is
    the direction the system actually needs. The score of a REJECTED
    candidate is only observable above the gate.
    """
    # Read the ONE module that holds both, never the concatenated
    # package: across files the comparison would silently measure
    # alphabetical filename order instead of source order, and this
    # invariant is far too load-bearing to rest on that accident.
    src = _read("telegram_bot/_outbound/_event_alert.py")
    record_at = src.index("record_alert(")
    gate_at = src.index("if top_score < threshold:")
    assert record_at < gate_at, (
        "record_alert must run BEFORE the threshold gate, or rejected "
        "candidates are never captured and thresholds can only go up"
    )


def test_only_one_ledger_write_per_event():
    """Two calls would double-count every sent event and skew the
    score distribution towards the ones that passed."""
    src = _read_outbound()
    assert src.count("record_alert(") == 1


def test_the_record_says_which_side_of_the_bar_it_fell_on():
    src = _read_outbound()
    call = src[src.index("record_alert(") : src.index("record_alert(") + 600]
    assert "passed_threshold=" in call
