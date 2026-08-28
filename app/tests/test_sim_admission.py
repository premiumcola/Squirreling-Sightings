"""The Simulieren view must fail HONESTLY.

Picking 3×3 used to take the camera off the air: the tick never finished,
the client watchdog aborted and re-issued it into a handler Flask cannot
cancel (so each retry ADDED ten inferences), the detector lock backed up,
and the operator was shown "Verbindung zur Kamera unterbrochen" for a
request nobody could afford. A wrong error message has already cost this
project four months once; these guards pin the pieces that make the
failure say what it is.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.routes import _sim_guard as G

_JS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js" / "mediaview"


def _read(name: str) -> str:
    p = _JS / name
    assert p.exists(), f"missing: {p}"
    return p.read_text(encoding="utf-8")


# ── backend: one slot per camera, never a queue ──────────────────────


def test_a_second_concurrent_request_is_refused_not_queued():
    """Queueing is what lets a wedged client pile up inference threads."""
    first = G.sim_slot("cam-a")
    assert first.acquired
    second = G.sim_slot("cam-a")
    assert not second.acquired, "a second in-flight sim request must be refused"
    # A different camera is unaffected — the guard is per-camera.
    other = G.sim_slot("cam-b")
    assert other.acquired
    other.__exit__()
    first.__exit__()
    assert G.sim_slot("cam-a").acquired


def test_the_slot_is_released_by_the_context_manager():
    with G.sim_slot("cam-c") as slot:
        assert slot.acquired
    assert G.sim_slot("cam-c").acquired


def test_busy_payload_names_the_real_cause_not_the_camera():
    body = G.busy_payload("cam-a")
    assert body["code"] == "busy"
    assert "Simulation" in body["error"]
    assert "Verbindung" not in body["error"], "busy is not a connection fault"


# ── backend: refuse a mode the hardware cannot afford ────────────────


def test_an_unmeasured_camera_is_allowed_to_try():
    """The first attempt is what produces the measurement."""
    verdict = G.affordability("cam-fresh", "3x3")
    assert verdict["ok"]
    assert verdict["estimated_ms"] is None


def test_a_measured_slow_camera_is_refused_before_it_hangs():
    # 1.2 s for a single-inference tick → ten inferences project to ~12 s.
    G.record_cost("cam-slow", "off", 1200.0)
    verdict = G.affordability("cam-slow", "3x3")
    assert not verdict["ok"]
    assert verdict["invokes"] == 10
    assert verdict["estimated_ms"] > G.TICK_CEILING_MS
    # …and the cheap mode stays available.
    assert G.affordability("cam-slow", "off")["ok"]


def test_a_fast_camera_keeps_every_mode():
    G.record_cost("cam-fast", "off", 120.0)
    assert G.affordability("cam-fast", "3x3")["ok"]


def test_the_refusal_says_it_is_the_mode_and_not_the_camera():
    G.record_cost("cam-slow2", "off", 1500.0)
    verdict = G.affordability("cam-slow2", "3x3")
    body = G.refusal_payload("cam-slow2", "3x3", verdict)
    assert body["code"] == "mode_too_expensive"
    msg = body["error"]
    assert "Kamera ist in Ordnung" in msg, "the camera must be exonerated explicitly"
    assert "Inferenzen" in msg and "3×3" in msg, "the arithmetic has to be in the message"


def test_a_measurement_in_one_mode_converts_to_another():
    """Cost per INVOKE is the transferable unit — measuring 2x2 has to
    inform the 3x3 verdict, or the gate only ever learns after the hang."""
    G.record_cost("cam-conv", "2x2", 5 * 900.0)  # 5 invokes at 900 ms
    verdict = G.affordability("cam-conv", "3x3")
    assert verdict["per_invoke_ms"] == 900
    assert not verdict["ok"]


# ── frontend: the pacing contract ────────────────────────────────────


def test_contact_and_success_are_tracked_separately():
    """`lastRespAt` counted only ok=true responses, so a backend answering
    503 (or now 429) promptly was indistinguishable from a dead camera and
    the reconnect banner was guaranteed."""
    poll = _read("live-detect-poll.js")
    assert "S.tickState.lastContactAt = Date.now();" in poll
    head = poll[: poll.index("if (data?.ok)")]
    assert "lastContactAt" in head, "contact must be stamped before the ok/else split"
    stall = _read("live-detect-stall.js")
    assert "t.lastContactAt" in stall, "the disconnect watchdog must key on contact"


def test_the_watchdog_will_not_abort_a_young_request():
    """Flask has no request cancellation: the handler runs every inference
    to completion regardless, so an abort-and-retry doubles the load."""
    stall = _read("live-detect-stall.js")
    body = stall[stall.index("export function _retryTickNow") :]
    body = body[: body.index("\n}")]
    assert "_INFLIGHT_ABORT_CEILING_MS" in body
    assert "return;" in body.split("_INFLIGHT_ABORT_CEILING_MS")[1][:80]


def test_the_pace_budget_scales_with_the_modes_inference_count():
    """A 5 s budget measured in 'Aus' describes a different request than a
    3×3 tick. Not scaling it is what aborted ticks that were about to
    succeed, so the EMA never learned the new cost — a bootstrap deadlock."""
    stall = _read("live-detect-stall.js")
    body = stall[stall.index("function _paceBudgetMs") :]
    body = body[: body.index("\n}")]
    assert "mvModeInvokes" in body
    assert "_STALL_FLOOR_MS * invokes" in body


def test_the_mode_switch_drops_the_stale_cadence_average():
    chrome = _read("live-detect-chrome.js")
    body = chrome[chrome.index("onModeChange:") :]
    body = body[: body.index("onOverlayChange")]
    assert "S.cycleEmaMs = NaN" in body


def test_the_slow_notice_is_not_a_connection_error():
    """The whole point: 'expensive' and 'disconnected' must not share a
    message."""
    stall = _read("live-detect-stall.js")
    warn = stall[stall.index("export function _showStallBanner") :]
    warn = warn[: warn.index("\n}")]
    assert "Keine Antwort vom Server" in warn
    pace = stall[stall.index("function _showPaceNotice") :]
    pace = pace[: pace.index("\n}")]
    assert "Verbindung" not in pace and "unterbrochen" not in pace
    assert "Inferenzen je Bild" in pace, "the notice must name the cost"


def test_the_inference_count_mirrors_the_python_table():
    """MV_MODE_INVOKES is the hi half of sim_invokes(). If they drift the
    frontend paces against a cost the backend is not paying."""
    from app.detectors._projection import sim_invokes

    js = _read("mode-indicator.js")
    block = js[js.index("MV_MODE_INVOKES = {") :]
    block = block[: block.index("}")]
    pairs = dict(re.findall(r"'?([a-z0-9x]+)'?:\s*(\d+)", block))
    for mode, count in pairs.items():
        assert int(count) == sim_invokes(mode)[1], f"{mode} drifted from the Python table"
    assert set(pairs) == {"off", "roi", "2x2", "3x3"}
