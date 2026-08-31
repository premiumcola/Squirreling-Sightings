"""Where the Erkennungsprofil's controls sit, and what a preset costs.

Three operator complaints, one file — all three are layout/flow
decisions that a refactor can undo without anything throwing:

  1. „Bitte die anklickbaren Buttons nach rechts oben nehmen, auf jeden
     Fall aufm PC."  The camera chips moved out of the body host into the
     section header, beside the Verlauf button. The body host is swapped
     wholesale between the Netz and the Verlauf view, so a chip rendered
     into it cannot sit in the header — the slot has to be in the
     template and the renderer has to target it.
  3. „Wenn ich die einfach anklick, dann verdreht's ja alles, dann komm
     ich nicht zurück."  A preset used to PATCH four fields immediately.
     It now stages them, so the staging bar's „Verwerfen" is the way
     back.
  5. Ghost-Spuren was a full-width row of its own for a single switch.
     It is a chip in the controls row now.

There is no jsdom here: the DOM-shaped assertions run the real modules
under node via ``_node_js.run_js`` with the header slot stubbed, and the
rest are source/CSS assertions in the style of test_storms_archive.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_REPO = Path(__file__).resolve().parents[2]
_JS = _REPO / "app" / "web" / "static" / "js"
_CSS = (_REPO / "app" / "web" / "static" / "css" / "32-netz.css").read_text(encoding="utf-8")
_TPL = (_REPO / "app" / "web" / "templates" / "partials" / "netz.html").read_text(encoding="utf-8")
_CARDS = (_JS / "netz" / "_cards.js").read_text(encoding="utf-8")

_TUNING = """{
  frame_interval_ms: 500, motion_sensitivity: 0.5, post_motion_tail_s: 0,
  track_miss_grace_seconds: 0, track_iou_match_threshold: 0,
  roi_mode: 'off', wildlife_motion_sensitivity: 0, roi_min_net_disp_frac: 0,
}"""

# The header slot the chips render into, stubbed so the test can read
# back what landed in it. byId() resolves `document` on every call, so
# reassigning it here (after the imports) is enough.
_SETUP = f"""
  const cards = await import(JS + '/netz/_cards.js');
  const S = await import(JS + '/netz/_state.js');
  const slot = {{ innerHTML: '' }};
  globalThis.document.getElementById = (id) => (id === 'netzCamChips' ? slot : null);
  const host = {{ innerHTML: '' }};
  S.netzState.cameras = [
    {{ id: 'cam_a', name: 'Werkstatt' }},
    {{ id: 'cam_b', name: 'Garten' }},
  ];
  S.netzState.states = {{
    cam_a: {{ cam_id: 'cam_a', cam_name: 'Werkstatt', role: 'security',
             axes: [], frozen: [], tuning: {_TUNING} }},
    cam_b: {{ cam_id: 'cam_b', cam_name: 'Garten', role: 'garden',
             axes: [], frozen: [], tuning: {_TUNING} }},
  }};
"""


# ── 1 · the camera chips live in the header ───────────────────────────


def test_the_template_carries_the_header_chip_slot():
    """Without the slot in the template the chips have nowhere to go and
    the renderer silently paints into nothing."""
    assert 'id="netzCamChips"' in _TPL
    head = _TPL[_TPL.index('class="netz-head-row"') : _TPL.index('ws-subtitle')]
    assert 'id="netzCamChips"' in head, "the chip slot is not inside the header row"
    assert 'id="netzViewBtn"' in head, "the chips must share the header row with the toggle"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_chips_render_into_the_header_slot_and_not_into_the_body():
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        console.log(JSON.stringify({{
          slotHasChips: String(slot.innerHTML).includes('data-netz-cam="cam_a"'),
          bodyHasChips: String(host.innerHTML).includes('data-netz-cam'),
          bodyHasCards: String(host.innerHTML).includes('data-cam="cam_a"'),
        }}));
        """
    )
    assert out["slotHasChips"] is True, "the header slot never received the camera chips"
    assert out["bodyHasChips"] is False, "the chips are still rendered into the body host"
    assert out["bodyHasCards"] is True


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_verlauf_view_empties_the_header_chip_slot():
    """The archive brings camera chips of its own; two rows of the same
    control is the duplication the design rules forbid."""
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        S.netzState.view = 'verlauf';
        cards.renderCamChips();
        console.log(JSON.stringify({{ left: String(slot.innerHTML) }}));
        """
    )
    assert out["left"] == ""


def test_the_header_puts_the_chips_top_right_on_desktop():
    """„auf jeden Fall aufm PC" — a media query, not a mobile regression."""
    # `btns` (plural) since the frozen-values info button joined the
    # Verlauf button in the same right-hand slot.
    assert "grid-template-areas: 'title btns' 'cams cams'" in _CSS, "phone layout changed"
    desktop = _CSS[_CSS.index("@media (min-width: 760px)") :]
    assert "grid-template-areas: 'title cams btns'" in desktop
    assert "justify-content: flex-end" in desktop


def test_the_chips_keep_a_44px_touch_target():
    assert ".netz-cams .netz-pill {\n  min-height: 44px;\n}" in _CSS


# ── 3 · a preset is recoverable ───────────────────────────────────────


def test_a_preset_stages_instead_of_saving():
    """The undo IS the staging bar. A preset that PATCHes on click has no
    way back — four fields overwritten, no record of the previous four."""
    assert "_TRACK_PRESETS" in _CARDS
    presets = _CARDS[_CARDS.index("data-tune-preset]", _CARDS.index("qsa(")) :]
    assert "stageValue(" in presets, "the preset buttons no longer stage"
    assert "_save(" not in presets, "the preset buttons still write straight through"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_a_staged_preset_shows_the_discard_bar():
    """Four staged fields → the bar with „Verwerfen" is on the card."""
    out = _js(
        f"""
        {_SETUP}
        ['track_spawn_min_score', 'track_continue_min_score',
         'track_miss_grace_seconds', 'track_iou_match_threshold']
          .forEach((k, i) => S.stageValue('cam_a', k, 0.3 + i));
        cards.renderCards(host);
        console.log(JSON.stringify({{
          count: S.stagedCountFor('cam_a'),
          hasDiscard: String(host.innerHTML).includes('data-tune-discard'),
          other: S.stagedCountFor('cam_b'),
        }}));
        """
    )
    assert out["count"] == 4
    assert out["hasDiscard"] is True
    assert out["other"] == 0


# ── 5 · the ghost toggle is a chip, not a row ─────────────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_ghost_toggle_sits_inside_the_controls_row():
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        const html = String(host.innerHTML);
        // Everything from the controls row up to the end of that card.
        const row = html.slice(html.indexOf('netz-card-controls'), html.indexOf('</article>'));
        console.log(JSON.stringify({{
          inRow: row.includes('data-tune-ghost'),
          afterPresets: row.indexOf('data-tune-ghost') > row.indexOf('data-tune-preset'),
          isChip: html.includes('netz-chip-toggle'),
          ownRow: html.includes('netz-card-ghost'),
          pressed: html.includes('aria-pressed="true"'),
        }}));
        """
    )
    assert out["inRow"] is True, "the ghost toggle left the controls row"
    assert out["afterPresets"] is True, "the ghost chip is not part of the preset row"
    assert out["isChip"] is True
    assert out["ownRow"] is False, "the ghost toggle still owns a full-width row"
    assert out["pressed"] is True, "the toggle does not report its state to assistive tech"


def test_the_ghost_chip_keeps_a_44px_touch_target():
    chip = _CSS[_CSS.index(".netz-chip-toggle {") :]
    assert "min-height: 44px" in chip[: chip.index("}")]
