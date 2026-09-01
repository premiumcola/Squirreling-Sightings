"""One Erkennungsprofil panel per camera, beside its own Live-Feed tile.

The operator, from a screenshot of the dashboard's top section: three
independent panels, one per camera, each directly beside its own camera
tile — not one shared panel next to the whole grid. That retires the
single `#netz` section with its camera-chip switcher entirely; these
tests pin the replacement shape.

Three operator complaints from the PREVIOUS shape still apply verbatim to
every panel now (they were never about the page-level chrome that is
gone):

  3. „Wenn ich die einfach anklick, dann verdreht's ja alles, dann komm
     ich nicht zurück." A preset used to PATCH four fields immediately.
     It still stages them, so the staging bar's „Verwerfen" is the way
     back.
  5. Ghost-Spuren was a full-width row of its own for a single switch.
     It is still a chip in the controls row.

There is no jsdom here: the DOM-shaped assertions run the real modules
under node via ``_node_js.run_js``, and the rest are source/CSS
assertions in the style of test_storms_archive.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_REPO = Path(__file__).resolve().parents[2]
_JS = _REPO / "app" / "web" / "static" / "js"
_CSS = (_REPO / "app" / "web" / "static" / "css" / "32-netz.css").read_text(encoding="utf-8")
_DASHBOARD_CSS = (_REPO / "app" / "web" / "static" / "css" / "03-dashboard.css").read_text(
    encoding="utf-8"
)
_DASHBOARD_JS = (_JS / "dashboard.js").read_text(encoding="utf-8")
_CARDS = (_JS / "netz" / "_cards.js").read_text(encoding="utf-8")
_PANEL = (_JS / "netz" / "_panel.js").read_text(encoding="utf-8")

_TUNING = """{
  frame_interval_ms: 500, motion_sensitivity: 0.5, post_motion_tail_s: 0,
  track_miss_grace_seconds: 0, track_iou_match_threshold: 0,
  roi_mode: 'off', wildlife_motion_sensitivity: 0, roi_min_net_disp_frac: 0,
}"""

_SETUP = f"""
  const cards = await import(JS + '/netz/_cards.js');
  const S = await import(JS + '/netz/_state.js');
  S.netzState.cameras = [
    {{ id: 'cam_a', name: 'Werkstatt' }},
    {{ id: 'cam_b', name: 'Garten' }},
  ];
  S.netzState.states = {{
    cam_a: {{ cam_id: 'cam_a', cam_name: 'Werkstatt', role: 'security',
             axes: [], frozen: [{{key: 'a_key', de: 'A-Wert'}}], tuning: {_TUNING} }},
    cam_b: {{ cam_id: 'cam_b', cam_name: 'Garten', role: 'garden',
             axes: [], frozen: [], tuning: {_TUNING} }},
  }};
"""


# ── 1 · one panel per camera, mounted beside its own tile ────────────


def test_dashboard_renders_a_net_slot_beside_every_camera_tile():
    """dashboard.js's own camera-tile template is what a panel mounts
    into — without this sibling slot netz/_panel.js has nowhere to go."""
    assert "cam-net-slot" in _DASHBOARD_JS
    row = _DASHBOARD_JS[_DASHBOARD_JS.index('class="cv-card') :]
    assert row.index("</article>") < row.index("cam-net-slot")


def test_the_camera_grid_is_a_two_column_tile_panel_row():
    seg = _DASHBOARD_CSS[_DASHBOARD_CSS.index(".camera-grid {") :][:200]
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in seg


def test_the_grid_collapses_to_one_column_on_a_phone():
    """The same breakpoint the grid already used for its old multi-column
    collapse — matching an existing convention rather than picking a new
    number, and it is what stacks each panel directly under its own tile
    on mobile (grid auto-flow: tile, panel, next tile, next panel)."""
    assert "@media (max-width: 900px)" in _DASHBOARD_CSS
    seg = _DASHBOARD_CSS[_DASHBOARD_CSS.index("@media (max-width: 900px)") :][:160]
    assert "grid-template-columns: minmax(0, 1fr)" in seg


def test_dashboard_calls_initnetpanels_after_every_render():
    assert "initNetPanels()" in _DASHBOARD_JS


def test_a_drag_in_progress_blocks_the_poll_rebuild():
    """The pointer-capture hazard netz/_tune_drag.js's own resize comment
    warns about: rebuilding #cameraCards mid-drag would tear the dragged
    SVG node out from under the finger."""
    assert "isTuneDragging()" in _DASHBOARD_JS


def test_the_old_per_count_grid_classes_are_gone():
    """Every camera gets the same tile+panel row now — there is no longer
    a distinct 1/2/4/N-camera column layout to pick a class for."""
    assert "_camGridCols" not in _DASHBOARD_JS
    assert "cam-grid-1" not in _DASHBOARD_CSS


# ── 2 · the shared camera-chip switcher and multi-card strip are gone ──


def test_there_is_no_camera_chip_switcher_left():
    assert "renderCamChips" not in _CARDS
    assert "netzCamChips" not in _CARDS
    assert "focusCam" not in _CARDS
    assert ".netz-cards {" not in _CSS
    assert ".netz-head-row {" not in _CSS


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
    """Four staged fields → the bar with „Verwerfen" is on the panel."""
    out = _js(
        f"""
        {_SETUP}
        ['track_spawn_min_score', 'track_continue_min_score',
         'track_miss_grace_seconds', 'track_iou_match_threshold']
          .forEach((k, i) => S.stageValue('cam_a', k, 0.3 + i));
        const html = cards.netBodyHtml({{ id: 'cam_a', name: 'Werkstatt' }});
        console.log(JSON.stringify({{
          count: S.stagedCountFor('cam_a'),
          hasDiscard: html.includes('data-tune-discard'),
          other: S.stagedCountFor('cam_b'),
        }}));
        """
    )
    assert out["count"] == 4
    assert out["hasDiscard"] is True
    assert out["other"] == 0


# ── 4 · the ghost toggle is a chip, not a row ─────────────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_ghost_toggle_sits_after_the_presets_as_a_chip():
    out = _js(
        f"""
        {_SETUP}
        const html = cards.netBodyHtml({{ id: 'cam_a', name: 'Werkstatt' }});
        console.log(JSON.stringify({{
          hasGhost: html.includes('data-tune-ghost'),
          afterPresets: html.indexOf('data-tune-ghost') > html.indexOf('data-tune-preset'),
          isChip: html.includes('netz-chip-toggle'),
          ownRow: html.includes('netz-card-ghost'),
          pressed: html.includes('aria-pressed="true"'),
        }}));
        """
    )
    assert out["hasGhost"] is True
    assert out["afterPresets"] is True, "the ghost chip is not part of the preset row"
    assert out["isChip"] is True
    assert out["ownRow"] is False, "the ghost toggle still owns a full-width row"
    assert out["pressed"] is True, "the toggle does not report its state to assistive tech"


def test_the_ghost_chip_keeps_a_44px_touch_target():
    chip = _CSS[_CSS.index(".netz-chip-toggle {") :]
    assert "min-height: 44px" in chip[: chip.index("}")]


# ── 5 · "Werte, die fest bleiben" is per camera, not cameras[0] ───────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_frozen_list_reflects_its_own_camera_not_the_first_one():
    """Regression guard for a bug the single-header design carried
    unnoticed: the box always read `netzState.cameras[0]`, so camera B's
    operator saw camera A's frozen values (or none) regardless of which
    panel they were looking at."""
    out = _js(
        f"""
        {_SETUP}
        console.log(JSON.stringify({{
          camA: cards.frozenListHtml('cam_a'),
          camB: cards.frozenListHtml('cam_b'),
        }}));
        """
    )
    assert "A-Wert" in out["camA"]
    assert out["camB"] == ""


# ── 6 · "Was zusammen wirkt" is page-level, shown once ────────────────


def test_combos_html_is_called_exactly_once_not_per_panel():
    """Camera-independent reference text — netz/_panel.js mounts it
    behind ONE header button for the whole Live-Feed section rather than
    calling it again for every panel render (CLAUDE.md: no duplication)."""
    assert "export function combosHtml" in _CARDS
    assert _PANEL.count("combosHtml()") == 1
    # The one call sits in initCombosInfo, not in the per-camera renderer.
    call_at = _PANEL.index("combosHtml()")
    fn_start = _PANEL.index("function initCombosInfo(")
    fn_end = _PANEL.index("\n}", fn_start)
    assert fn_start < call_at < fn_end


def test_the_combos_box_has_a_hidden_opt_out():
    assert ".netz-combos[hidden]" in _CSS


# ── 7 · every write path still takes its camera from the DOM ─────────


def test_every_write_path_takes_its_camera_from_the_dom():
    """With every camera's net on screen at once, a module-level "current
    camera" is how a drag on one camera PATCHes another. The panel's own
    dataset is the only correct source."""
    assert "card.dataset.cam" in _CARDS
    assert "netzState.camId" not in _CARDS
