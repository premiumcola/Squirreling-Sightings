"""S3 · the operator must SEE which half of the verdict was checked.

Two bugs with the same shape, both inside the alarm diagnostics:

  1. ``diag.parity.not_simulated`` — the endpoint's machine-readable
     declaration of the gates it does not run — was assembled on every
     tick and read by nothing. ``grep -rn "not_simulated\\|parity"
     app/web/static/js/`` found no consumer at all.
  2. the German skip notices DO reach the Trace tab, but ``live-trace``
     had no prefix class for ``motion`` / ``confirmation`` / ``wildlife``
     / ``event_cooldown`` / ``recording``, so every "wird in der Simu
     NICHT geprüft" line rendered in the muted ``info`` tint — quieter
     than the ``[final]`` line it exists to qualify.

Node runs the real renderer; the source assertions cover the wiring
(poll → S.session.lastParity → the Trace tab) that a DOM-free harness
cannot reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

JS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js"
CSS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "css"
ROUTES = Path(__file__).resolve().parents[1] / "app" / "routes"


# ── the declaration reaches the screen ──────────────────────────────────


def test_the_backend_still_declares_the_gates_it_does_not_run():
    # The diag payload moved to _sim_debug when the orchestrator hit
    # its file ceiling; the declaration is what this pins, not the file.
    src = (ROUTES / "_sim_debug.py").read_text(encoding="utf-8")
    block = src[src.index('"not_simulated"') :][:600]

    for gate in ("motion_gate", "confirmation_window", "wildlife_cascade", "frame_validator"):
        assert gate in block


def test_the_parity_block_has_a_consumer():
    """The bug this file exists for: a value written every tick and read
    by nobody, inside the diagnostics the operator trusts."""
    # The "what one response turns into" half of the poll loop lives in
    # _live-detect-frame.js since the 60-line-function split; the poll file
    # keeps the loop. Read both, so this pins the DATA PATH and not which
    # file currently holds it.
    frame = (JS / "mediaview" / "_live-detect-frame.js").read_text(encoding="utf-8")
    poll = (JS / "mediaview" / "live-detect-poll.js").read_text(encoding="utf-8") + frame
    panels = (JS / "mediaview" / "live-detect-panels.js").read_text(encoding="utf-8")
    trace = (JS / "mediaview" / "live-trace.js").read_text(encoding="utf-8")

    assert "lastParity" in poll, "the poll loop must keep diag.parity"
    assert "_diag.parity" in poll
    assert "lastParity" in panels, "the Trace tab must hand it to the renderer"
    assert "not_simulated" in trace, "the renderer must read the declared list"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_unchecked_gates_are_named_in_german_on_screen():
    out = _js(
        """
        const t = await import(JS + '/mediaview/live-trace.js');
        const html = t.renderParityBanner({
          not_simulated: ['motion_gate', 'confirmation_window', 'wildlife_cascade'],
        });
        console.log(JSON.stringify({ html }));
        """
    )
    html = out["html"]

    assert "NICHT GEPRÜFT" in html
    for word in ("Bewegung", "Bestätigung", "Wildtier-Kaskade"):
        assert word in html, html
    assert "motion_gate" not in html, "raw gate ids are not German"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_an_older_backend_without_parity_renders_nothing_extra():
    out = _js(
        """
        const t = await import(JS + '/mediaview/live-trace.js');
        console.log(JSON.stringify({
          none: t.renderParityBanner(null),
          empty: t.renderParityBanner({ not_simulated: [] }),
        }));
        """
    )

    assert out["none"] == "" and out["empty"] == ""


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_banner_is_rendered_even_before_the_first_tick():
    """The empty state is exactly when the operator is reading the panel
    to find out what it will and will not tell them."""
    out = _js(
        """
        const t = await import(JS + '/mediaview/live-trace.js');
        const host = { innerHTML: '' };
        t.renderLiveTrace(host, [], { not_simulated: ['identity'] });
        console.log(JSON.stringify({ html: host.innerHTML }));
        """
    )

    assert "Identität" in out["html"]
    assert "Warte auf ersten Tick" in out["html"]


# ── unchecked is visually distinct from ordinary info ───────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_a_stated_but_unrun_gate_does_not_render_as_ordinary_info():
    """Every one of these five lines says "läuft in der Simu NICHT" and
    every one of them used to fall through to the muted info tint."""
    out = _js(
        """
        const t = await import(JS + '/mediaview/live-trace.js');
        const host = { innerHTML: '' };
        t.renderLiveTrace(host, [{ ts: 0, lines: [
          '[motion] das Bewegungs-Gate läuft in der Simu NICHT',
          '[confirmation] die Simu prüft das Fenster NICHT',
          '[wildlife] Wildtier-Kaskade läuft in der Simu NICHT',
          '[event_cooldown] in der Simu nicht geprüft',
          '[recording] in der Simu nicht geprüft',
          '[push_threshold] person: 91 % < 95 %',
          '[final] KEIN Alarm',
        ] }], null);
        const found = [...host.innerHTML.matchAll(/data-prefix="([a-z]+)"/g)].map((m) => m[1]);
        console.log(JSON.stringify({ found }));
        """
    )

    assert out["found"] == [
        "unchecked",
        "unchecked",
        "unchecked",
        "unchecked",
        "unchecked",
        "gate",
        "final",
    ]


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_new_routing_gates_are_tinted_as_gates_not_as_noise():
    """mute / suppress / rate_limit are real evaluated gates and must not
    share the tint of a gate nobody checked."""
    out = _js(
        """
        const t = await import(JS + '/mediaview/live-trace.js');
        const host = { innerHTML: '' };
        t.renderLiveTrace(host, [{ ts: 0, lines: [
          '[mute] System stumm bis 21:14',
          '[suppress] person@cam: nicht unterdrückt',
          '[rate_limit] cam: Fenster 30 s frei',
        ] }], null);
        const found = [...host.innerHTML.matchAll(/data-prefix="([a-z]+)"/g)].map((m) => m[1]);
        console.log(JSON.stringify({ found }));
        """
    )

    assert set(out["found"]) == {"gate"}


def test_both_tints_actually_exist_in_the_stylesheet():
    """A data-prefix with no rule behind it renders as the default text
    colour — the same invisible-difference bug, one layer down."""
    css = (CSS / "30f-live-detect-skeleton.css").read_text(encoding="utf-8")

    for selector in (
        ".mv-ld-trace-line[data-prefix='unchecked']",
        ".mv-ld-trace-line[data-prefix='gate']",
        ".mv-ld-trace-parity-chip",
    ):
        assert selector in css, selector
    # iOS: the panel scrolls, so no viewport units and no hover-only state.
    block = css[css.index(".mv-ld-trace-parity") :]
    assert "vh" not in block.split("}")[0]


def test_the_renderer_stays_inside_the_js_file_budget():
    src = (JS / "mediaview" / "live-trace.js").read_text(encoding="utf-8")

    assert len(src.splitlines()) <= 400
