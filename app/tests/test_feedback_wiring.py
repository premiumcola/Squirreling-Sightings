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


def test_send_path_records_the_alert():
    src = _read("telegram_bot/_outbound/__init__.py")
    assert "from ...detection_feedback import record_alert" in src
    assert "record_alert(" in src


def test_alert_record_carries_score_and_threshold():
    """Without these two the record cannot calibrate anything — which is
    precisely why the pre-existing runtime alert-index was useless."""
    src = _read("telegram_bot/_outbound/__init__.py")
    call = src[src.index("record_alert(") : src.index("record_alert(") + 600]
    assert "score=top_score" in call
    assert "threshold=threshold" in call
    assert "cam_id=camera_id" in call
    assert "detections=detections" in call


def test_verdict_path_records_the_judgement():
    src = _read("telegram_bot/_inbound.py")
    assert "from ..detection_feedback import record_verdict" in src
    assert "record_verdict(" in src


def test_verdict_record_carries_the_camera():
    """Joined from the alert index, so a per-camera calibration is possible."""
    src = _read("telegram_bot/_inbound.py")
    call = src[src.index("record_verdict(") : src.index("record_verdict(") + 400]
    assert "cam_id=" in call
    assert 'source="telegram"' in call


def test_both_writes_are_best_effort():
    """Bookkeeping must never drop a real alert or break a callback."""
    out = _read("telegram_bot/_outbound/__init__.py")
    inb = _read("telegram_bot/_inbound.py")
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
    src = _read("telegram_bot/_inbound.py")
    assert 'runtime_set_subkey(\n                "event_feedback"' in src
