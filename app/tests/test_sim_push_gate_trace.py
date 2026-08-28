"""The simulator must show the gate that actually silences the alert.

The decision trace listed severity matrix, armed, telegram_enabled,
schedule_notify and cooldown — then concluded "would route through the
push pipeline (subject to gates above)". The per-label PUSH threshold
was not among "the gates above", and it is the one that drops most
alerts: shipped defaults are person 0.85 and squirrel 0.80 against a
detection floor of 0.45, with cat and bird at push:false entirely.

Observed on the real system: a person detected at 65 %, trace said
"would route", nothing arrived. A diagnostic that cannot see the gate
killing the thing it diagnoses sends the operator hunting in the wrong
place — which is exactly what happened.

The trace moved out of the endpoint into ``routes/_sim_routing`` when
the panel was put on production's configuration; the properties below
follow it rather than the file it used to live in.
"""

from __future__ import annotations

from pathlib import Path

ROUTES = Path(__file__).resolve().parent.parent / "app" / "routes"
ROUTING = ROUTES / "_sim_routing.py"
PIPELINE = ROUTES / "_sim_pipeline.py"


def _src(path: Path = ROUTING) -> str:
    return path.read_text(encoding="utf-8")


def test_the_push_threshold_is_evaluated():
    src = _src()
    assert "[push_threshold]" in src, (
        "the trace must evaluate the per-label push threshold — it is the gate "
        "that actually silences most alerts"
    )


def test_the_push_flag_is_evaluated():
    """cat and bird ship with push:false — no score can ever clear that,
    and the trace must say so rather than implying a threshold problem."""
    assert "[push_flag]" in _src()


def test_the_verdict_changes_when_the_push_gate_blocks():
    """Reporting 'would route' while the push gate blocks is the exact
    false confidence being removed."""
    src = _src()
    assert "push_blocked" in src
    assert "KEIN Alarm" in src


def test_the_final_verdict_does_not_overclaim():
    """The motion gate and the N-of-M confirmation window are NOT
    simulated. An unqualified "würde die Push-Pipeline erreichen" is a
    claim this endpoint cannot make, and making it is how a single-frame
    hit read as a confirmed event."""
    src = _src()
    assert "Bestätigungsfenster" in src and "nicht prüft" in src


def test_the_gate_is_read_only():
    """The simulator inspects; it must never send or mutate config."""
    src = _src()
    for forbidden in ("send_event_alert", "update_section", "upsert_camera", "settings.save"):
        assert forbidden not in src, f"the routing trace must not call {forbidden}"


def test_a_lookup_failure_cannot_break_the_endpoint():
    """The simulator is a diagnostic; a config read that throws must not
    take down the view the operator is using to diagnose."""
    src = _src()
    block = src[src.index("def _push_lines") :]
    assert "except Exception" in block


def test_the_simulator_passes_the_frame_size_to_the_tracker():
    """Without frame_w/frame_h the motion model's prediction clamp and the
    edge-grace rule both short-circuit on `0 == unknown`.

    That matters more here than anywhere else: the simulator is what the
    operator LOOKS AT to judge tracking quality. Running it with the
    clamp disabled shows a worse tracker than production actually has,
    and sends the diagnosis chasing a problem that is partly the
    diagnostic tool's own.
    """
    src = _src(PIPELINE)
    call = src[src.index("tracker.step_matches(") :][:600]
    assert "frame_w=" in call and "frame_h=" in call


def test_the_simulator_does_not_hand_roll_the_tracker_step():
    """It used to bump ``_frame_idx`` itself and build its own
    ``compute_miss_grace_samples`` call against the camera's CONFIGURED
    frame rate — 53 s of grace at a 1 Hz tick. One shared entry point
    with the live loop is what keeps the two from drifting again."""
    src = _src(PIPELINE)
    assert "_frame_idx +=" not in src
    assert "associate_detections" not in src
