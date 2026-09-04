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
#
# The first version of this gate could not fire. It capped a tick at
# 8 000 ms and projected 3×3 as ten invokes, so it needed ONE inference to
# cost 800 ms before it refused anything — on a 5950X a 300×300 SSD graph
# is tens of ms, and on the TPU 10.5 ms (coco_ssd) to 40.4 ms
# (efficientdet_lite0, both measured 2026-08-28). The refusal, its German
# text and the "Auf Aus zurückschalten" button were unreachable code, and
# the test below it asserted a 120 ms camera "keeps every mode" — which
# proved nothing, because so did every other camera.
#
# The ceiling is now `MAX_CAPTURE_LAG_S`: the endpoint's own bar for how
# far behind live a frame may be. Nothing about it is a guess about
# hardware, so it stays correct on both tiers.


def test_the_ceiling_is_the_endpoints_own_freshness_bar():
    """Not a number someone picked. A tick whose inference outlasts the
    lag the handler refuses frames for cannot deliver a live picture."""
    assert G.TICK_CEILING_MS == int(G.MAX_CAPTURE_LAG_S * 1000)


def test_an_unmeasured_camera_is_allowed_to_try():
    """The first attempt is what produces the measurement."""
    verdict = G.affordability("cam-fresh", "3x3")
    assert verdict["ok"]
    assert verdict["estimated_ms"] is None


def test_the_gate_fires_on_a_cost_that_only_the_tiled_modes_cannot_carry():
    """The band the gate exists for: an inference expensive enough that
    ten of them break the budget while five of them do not. Below
    `ceiling/10` nothing is refused; above `ceiling/5` even ROI is. In
    between — which is where a several-hundred-ms CPU invoke on a heavy
    graph lands — the verdict must differ BY MODE, or the gate is either
    unreachable or a blanket ban."""
    per = G.TICK_CEILING_MS / 10.0 + 30.0  # 230 ms at a 2 000 ms ceiling
    G.record_cost("cam-band", "off", per, 1)
    assert not G.affordability("cam-band", "3x3")["ok"], "3×3 must be refused here"
    assert G.affordability("cam-band", "roi")["ok"], "ROI must stay available"
    assert G.affordability("cam-band", "2x2")["ok"]
    assert G.affordability("cam-band", "off")["ok"], "Aus must always stay available"


def test_the_gate_stays_silent_at_the_costs_this_box_actually_measures():
    """Both hardware worlds. The TPU numbers are measured
    (CLAUDE.md, 2026-08-28); 35 ms stands in for the CPU tier on a 300×300
    SSD graph on the 5950X. In none of them is 3×3 unaffordable, and the
    gate must not pretend otherwise."""
    for cam, per_invoke in (("cam-tpu-ssd", 10.5), ("cam-tpu-eff", 40.4), ("cam-cpu-ssd", 35.0)):
        G.record_cost(cam, "off", per_invoke, 1)
        verdict = G.affordability(cam, "3x3")
        assert verdict["ok"], f"{cam}: 3×3 refused at {per_invoke} ms/invoke"
        assert verdict["estimated_ms"] <= G.TICK_CEILING_MS


def test_a_measured_slow_camera_is_refused_before_it_hangs():
    # 1.2 s for a single-inference tick → ten inferences project to 12 s.
    G.record_cost("cam-slow", "off", 1200.0, 1)
    verdict = G.affordability("cam-slow", "3x3")
    assert not verdict["ok"]
    assert verdict["invokes"] == 10
    assert verdict["estimated_ms"] > G.TICK_CEILING_MS
    # …and the cheap mode stays available.
    assert G.affordability("cam-slow", "off")["ok"]


def test_the_refusal_says_it_is_the_mode_and_not_the_camera():
    G.record_cost("cam-slow2", "off", 1500.0, 1)
    verdict = G.affordability("cam-slow2", "3x3")
    body = G.refusal_payload("cam-slow2", "3x3", verdict)
    assert body["code"] == "mode_too_expensive"
    msg = body["error"]
    assert "Kamera ist in Ordnung" in msg, "the camera must be exonerated explicitly"
    assert "Inferenzen" in msg and "3×3" in msg, "the arithmetic has to be in the message"


def test_a_measurement_in_one_mode_converts_to_another():
    """Cost per INVOKE is the transferable unit — measuring 2x2 has to
    inform the 3x3 verdict, or the gate only ever learns after the hang."""
    G.record_cost("cam-conv", "2x2", 5 * 900.0, 5)  # 5 invokes at 900 ms
    verdict = G.affordability("cam-conv", "3x3")
    assert verdict["per_invoke_ms"] == 900
    assert not verdict["ok"]


def test_the_roi_measurement_is_not_inflated_by_a_mixed_convention():
    """The arithmetic bug this pins: the estimate divided a measurement by
    the LOW invoke count of its mode and multiplied by the HIGH one of the
    target mode. `sim_invokes('roi')` is (2, 5) — a ROI tick that really
    ran five inferences for 1 750 ms costs 350 ms each, but 1750/2 = 875
    put "~875 ms je Inferenz" on screen (2.5× wrong) and projected 3×3 at
    8 750 ms. Only the handler knows how many crops ROI actually split
    into, so it reports the count and the division happens once, here."""
    G.record_cost("cam-roi", "roi", 1750.0, 5)
    verdict = G.affordability("cam-roi", "3x3")
    assert verdict["per_invoke_ms"] == 350, "the per-invoke figure must be the true one"
    assert verdict["estimated_ms"] == 3500, "10 × 350 ms — not 10 × 875 ms"
    # The same measurement, projected back onto its own mode, has to
    # reproduce itself. That is the property a mixed convention breaks.
    assert G.affordability("cam-roi", "roi")["estimated_ms"] == 1750


def test_a_two_crop_roi_tick_is_not_read_as_a_five_crop_one():
    """The other half of the same bug, with the counts the other way
    round: ROI splits into 1–4 crops depending on the motion box, so a
    tick that ran TWO inferences for 700 ms is 350 ms each. Dividing by
    the table's worst case (5) would report 140 ms and wave 3×3 through at
    an estimated 1 400 ms."""
    G.record_cost("cam-roi2", "roi", 700.0, 2)
    verdict = G.affordability("cam-roi2", "3x3")
    assert verdict["per_invoke_ms"] == 350
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


def test_no_caller_can_reach_an_unguarded_abort():
    """The claim above was FALSE for the path the operator uses most.
    `_tick` aborted at its head unconditionally, and `_forceImmediateTick`
    — mode switch, stream switch — calls straight into it, so the very
    first click on 3×3 aborted whatever was in flight and re-issued it
    into a handler that keeps running. Every `.abort()` in the live-detect
    loop must sit behind the ceiling."""
    guards = ("_INFLIGHT_ABORT_CEILING_MS", "_deferWhileInflight(session)")
    for name in ("live-detect-poll.js", "live-detect-stall.js", "live-detect-chrome.js"):
        src = _read(name)
        for hit in re.finditer(r"abort\?\.abort\(\)", src):
            head = src[: hit.start()]
            fn = max(
                head.rfind("\nfunction "),
                head.rfind("\nexport function "),
                head.rfind("\nexport async function "),
            )
            assert fn >= 0, f"{name}: abort outside any function"
            assert any(g in head[fn:] for g in guards), (
                f"{name}: an abort at offset {hit.start()} is not guarded by the "
                "in-flight ceiling"
            )


def test_a_tick_that_finds_one_in_flight_waits_instead_of_racing():
    """Not aborting is only half of it — issuing a SECOND request while
    the first runs is what the backend's single slot then answers with
    429 busy, i.e. the mode switch appears to do nothing."""
    poll = _read("live-detect-poll.js")
    body = poll[poll.index("function _deferWhileInflight") :]
    body = body[: body.index("\n}")]
    assert "_INFLIGHT_ABORT_CEILING_MS" in body
    assert "_TICK_RETRY_WHILE_INFLIGHT_MS" in body, "the waiting tick must re-arm itself"
    # The abort itself sits in _beginTick now, so the ordering is asserted
    # across the two: _tick must clear the guard before it calls _beginTick,
    # and _beginTick is where the abort lives. Pinning the ORDER, not the
    # file layout — the loop was split for the 60-line ceiling, and the
    # contract is unchanged.
    tick = poll[poll.index("export async function _tick") :]
    tick = tick[: tick.index("\n}")]
    assert tick.index("_deferWhileInflight(session)") < tick.index(
        "_beginTick(session)"
    ), "the guard has to run BEFORE the abort, or _tick is back to aborting whatever it finds"
    begin = poll[poll.index("function _beginTick") :]
    begin = begin[: begin.index("\n}")]
    assert "abort?.abort()" in begin, "the abort belongs to the step _tick guards"
    chrome = _read("live-detect-chrome.js")
    forced = chrome[chrome.index("export function _forceImmediateTick") :]
    forced = forced[: forced.index("\n}")]
    assert "abort" not in forced, "the mode-switch path must not abort a running request"


def test_the_pace_notice_can_fire_in_the_mode_it_was_written_for():
    """`_STALL_FLOOR_MS * invokes` gave 3×3 a 50 000 ms budget — the
    notice that names the mode's cost could not appear in the mode whose
    cost it names. A slow tick therefore showed a frozen picture and no
    text at all, for its whole duration."""
    stall = _read("live-detect-stall.js")
    body = stall[stall.index("function _paceBudgetMs") :]
    body = body[: body.index("\n}")]
    assert "_STALL_FLOOR_MS" not in body, "the pace budget must not scale with the mode"
    assert "_PACE_FLOOR_MS" in body and "_STALL_FACTOR" in body
    assert "invokes" not in body, "the mode's cost belongs in the message, not the threshold"
    # The tunables moved to _live-detect-consts.js (a leaf, so siblings can
    # read a threshold without importing live-detect.js). Pin the VALUE,
    # wherever the cluster declares it.
    consts = _read("_live-detect-consts.js")
    floor = int(re.search(r"_PACE_FLOOR_MS = (\d+)", consts).group(1))
    # The budget is mode-independent now, so the worst case IS the floor.
    # 10 s of frozen picture with no explanation is the failure being
    # fixed; anything under ~6 s reaches the operator while they are still
    # wondering rather than after they have given up.
    assert floor <= 6000, f"{floor} ms is too long to leave a frozen picture unexplained"
    # …and the notice itself still names the cost, which is what makes it
    # an explanation rather than another spinner. The wording moved to
    # _live-detect-outage.js when the banners were routed to a surface the
    # unified player actually renders; this file's own `_showPaceNotice`
    # now only hands over the mode and its invoke count.
    pace = stall[stall.index("function _showPaceNotice") :]
    pace = pace[: pace.index("\n}")]
    assert "mvModeInvokes" in pace and "kind: 'pace'" in pace
    verdicts = _read("_live-detect-outage.js")
    assert "Inferenzen je Bild" in verdicts[verdicts.index("  pace: {") :]


def test_a_429_clears_the_disconnect_banner_it_was_provoked_by():
    """The stuck-message path. A >30 s tick paints "Keine Antwort vom
    Server"; the retry it fires is answered 429 busy by the slot the
    aborted handler still holds; the 429 branch returned ABOVE the
    recovery block, so the disconnect banner stayed up — over a server
    answering twice a second — and nothing could take it down."""
    stall = _read("live-detect-stall.js")
    body = stall[stall.index("export function _checkStall") :]
    body = body[: body.index("\n}")]
    branch = body[body.index("t.lastStatus === 429") :]
    branch = branch[: branch.index("return;")]
    assert "_clearContactStall()" in branch, "a 429 must drop the stall state on its way out"
    clear = stall[stall.index("function _clearContactStall") :]
    clear = clear[: clear.index("\n}\n")]
    assert "clearOutage('contact'" in clear, (
        "only the disconnect verdict may be cleared here — a busy or refused "
        "notice describes the current truth, and clearOutage takes the id it "
        "is allowed to take down for exactly that reason"
    )


def test_busy_paints_its_own_message():
    """With the watchdog standing aside for a 429 and busy painting
    nothing, the operator got a frozen picture and no text."""
    poll = _read("live-detect-poll.js")
    assert "showOutage({ kind: 'http', status, data })" in poll, (
        "every ok=false response must reach the verdict band, not only the "
        "two the loop happened to special-case"
    )
    verdicts = _read("_live-detect-outage.js")
    body = verdicts[verdicts.index("  busy: {") : verdicts.index("  mode_too_expensive: {")]
    assert "tone: WAIT" in body, "busy is not a fault tone"
    assert "läuft noch" in body
    assert "Verbindung" not in body and "Keine Antwort" not in body


def test_every_failure_the_endpoint_can_send_reaches_the_operator():
    """The bug this file was extended for: the messages were CORRECT and
    invisible. `_banner` hosted itself in `#lightboxMediaWrap`, the legacy
    modal the unified player replaced and does not render, so a real
    outage showed nothing at all and the panel looked idle.

    Pin both halves: the band no longer resolves the legacy host for a
    headless (player-owned) session, and every code the Python can answer
    with has a verdict on the JS side.
    """
    verdict = _read("live-detect-verdict.js")
    assert "[data-slot=\"panel\"]" in verdict, "the band must target the player's panel"
    assert (
        "S.session?.headless" in verdict
    ), "a headless producer owns no legacy chrome and must not write into it"
    outage = _read("_live-detect-outage.js")
    for code in (
        "busy",
        "mode_too_expensive",
        "no_frame",
        "stale",
        "corrupt",
        "coral_unavailable",
        "runtime_inactive",
        "unknown_revision",
        "inference_failed",
        "camera_not_found",
    ):
        assert f"  {code}: {{" in outage, f"{code} has no verdict of its own"
    # …and the Python actually labels the bodies the JS keys on, rather
    # than leaving two 503s to be told apart by their German prose.
    src = (
        Path(__file__).resolve().parents[1] / "app" / "routes" / "coral_test_detection.py"
    ).read_text(encoding="utf-8")
    for code in ("camera_not_found", "runtime_inactive", "coral_unavailable"):
        assert f'refusal("{code}"' in src, f"the endpoint sends {code} unlabelled"


def test_the_mode_switch_drops_the_stale_cadence_average():
    chrome = _read("live-detect-chrome.js")
    body = chrome[chrome.index("onModeChange:") :]
    body = body[: body.index("onOverlayChange")]
    assert "S.cycleEmaMs = NaN" in body


def test_the_slow_notice_is_not_a_connection_error():
    """The whole point: 'expensive' and 'disconnected' must not share a
    message."""
    verdicts = _read("_live-detect-outage.js")
    contact = verdicts[verdicts.index("  contact: {") : verdicts.index("  pace: {")]
    assert "Keine Antwort vom Server" in contact
    pace = verdicts[verdicts.index("  pace: {") : verdicts.index("\n};")]
    assert "Verbindung" not in pace and "unterbrochen" not in pace
    assert "Inferenzen je Bild" in pace, "the notice must name the cost"
    assert "tone: WAIT" in pace, "slow-but-alive is not a fault tone"


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


# ── the estimate must be revisable by measurement ─────────────────────
#
# The first version of the gate resolved the per-invoke cost as a
# cross-mode min() over every measured mode. The reasoning in its
# docstring was sound for the FIRST attempt at a mode — you have to run
# something once to measure it — but it applied that optimism forever.
# One cheap `off` sample stayed in the ring and disarmed the refusal
# permanently, so a camera that had already measured 3×3 at five seconds
# a tick was still told 3×3 was affordable. The whole gate was decorative
# in exactly the path the operator walks: they use `off`, then switch up.


def _fresh(cam: str) -> None:
    with G._COST_GUARD:
        for key in [k for k in G._COSTS if k[0] == cam]:
            del G._COSTS[key]


def test_a_cheap_off_sample_cannot_disarm_the_refusal_for_3x3():
    """THE regression test. Walk the operator's actual path."""
    cam = "cam_disarm"
    _fresh(cam)
    # 1 · they watch in `off` for a while — one inference, fast.
    G.record_cost(cam, "off", 40.0, 1)
    assert (
        G.affordability(cam, "3x3")["ok"] is True
    ), "an unmeasured 3×3 must be allowed to run once — that is what measures it"
    # 2 · they switch to 3×3 and it takes five seconds per tick.
    G.record_cost(cam, "3x3", 5000.0, 10)
    aff = G.affordability(cam, "3x3")
    assert aff["per_invoke_ms"] == 500, f"3×3 must cost what 3×3 measured, got {aff}"
    assert aff["ok"] is False, "after measuring itself at 5 s a tick, 3×3 must be refused"


def test_the_cheap_stand_in_still_applies_to_a_mode_never_run():
    """The optimism is kept where it belongs — only before first contact."""
    cam = "cam_standin"
    _fresh(cam)
    G.record_cost(cam, "off", 40.0, 1)
    assert G.affordability(cam, "2x2")["per_invoke_ms"] == 40


def test_an_expensive_neighbour_does_not_condemn_an_unmeasured_mode():
    """The stand-in is the cheapest sample, so a costly 3×3 cannot veto ROI."""
    cam = "cam_neighbour"
    _fresh(cam)
    G.record_cost(cam, "off", 30.0, 1)
    G.record_cost(cam, "3x3", 5000.0, 10)
    assert G.affordability(cam, "roi")["ok"] is True
