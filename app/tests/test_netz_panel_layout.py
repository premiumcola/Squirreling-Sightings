"""One Erkennungsprofil panel per camera, beside its own Live-Feed tile.

The operator, from a screenshot of the dashboard's top section: three
independent panels, one per camera, each directly beside its own camera
tile — not one shared panel next to the whole grid. That retires the
single `#netz` section with its camera-chip switcher entirely; these
tests pin the replacement shape.

One operator complaint from the PREVIOUS shape still applies verbatim to
every panel now (it was never about the page-level chrome that is gone):

  5. Ghost-Spuren was a full-width row of its own for a single switch.
     It is still a chip in the controls row.

The Vorlage/preset row this file used to pin (three buttons that staged
four fields at once) is GONE — "nimm die Vorlagen raus, ich will da
nichts einfach anklicken und mit einem Klick die ganzen Einstellungen
verhauen." track_continue_min_score, the one field that existed only to
be preset-written, is still a real backend field (app/app/tracker_core/
_resolve.py, app/app/thresholds/_ladder.py) — it just lost its one-click
UI shortcut, not its meaning; the cam-edit form's own field still writes
it directly.

"Werte, die fest bleiben" also moved: FROZEN_KEYS (app/app/routes/
_netz_helpers.py) is one flat constant sent identically to every camera,
so there was never a real per-camera difference to preserve by repeating
it on N panels — it now shares the page-level "Was zusammen wirkt" box.

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


# ── 3 · the preset row is gone, and its field is still reachable ──────


def test_the_preset_row_is_gone():
    """„Ich will da nichts einfach anklicken und mit einem Klick die
    ganzen Einstellungen verhauen." CLAUDE.md: don't leave a corpse."""
    assert "_TRACK_PRESETS" not in _CARDS
    assert "_presetsHtml" not in _CARDS
    assert "data-tune-preset" not in _CARDS
    assert "erk-track-preset" not in _CSS


def test_the_preset_only_field_is_still_a_real_backend_field():
    """track_continue_min_score lost its one-click preset shortcut, not
    its meaning — the cam-edit form still writes it directly."""
    resolve = (_REPO / "app" / "app" / "tracker_core" / "_resolve.py").read_text(encoding="utf-8")
    assert "track_continue_min_score" in resolve


# ── 4 · the ghost toggle is a chip, not a row ─────────────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_ghost_toggle_is_a_chip_not_a_row():
    out = _js(
        f"""
        {_SETUP}
        const html = cards.netBodyHtml({{ id: 'cam_a', name: 'Werkstatt' }});
        console.log(JSON.stringify({{
          hasGhost: html.includes('data-tune-ghost'),
          isChip: html.includes('netz-chip-toggle'),
          ownRow: html.includes('netz-card-ghost'),
          pressed: html.includes('aria-pressed="true"'),
        }}));
        """
    )
    assert out["hasGhost"] is True
    assert out["isChip"] is True
    assert out["ownRow"] is False, "the ghost toggle still owns a full-width row"
    assert out["pressed"] is True, "the toggle does not report its state to assistive tech"


def test_the_ghost_chip_keeps_a_44px_touch_target():
    chip = _CSS[_CSS.index(".netz-chip-toggle {") :]
    assert "min-height: 44px" in chip[: chip.index("}")]


# ── 5 · "Werte, die fest bleiben" is page-level, not per panel ────────


def test_the_frozen_box_has_no_per_panel_home():
    """No per-panel button, no per-panel `hidden` box any more — see
    frozenSectionHtml below for where it actually lives now."""
    assert "netz-frozen-box" not in _PANEL
    assert "data-netz-toggle-frozen" not in _PANEL
    assert "netzFrozenBox-" not in _PANEL


def test_frozen_section_html_lives_in_the_shared_combos_box():
    assert "export function frozenSectionHtml" in _CARDS
    assert _PANEL.count("frozenSectionHtml()") == 1
    call_at = _PANEL.index("frozenSectionHtml()")
    fn_start = _PANEL.index("function initCombosInfo(")
    fn_end = _PANEL.index("\n}", fn_start)
    assert fn_start < call_at < fn_end


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_frozen_list_html_still_reflects_whichever_camera_its_asked_for():
    """frozenSectionHtml picks any one loaded camera — this pins that the
    underlying per-camera lookup it relies on is still correct, in case a
    future camera-specific `frozen` list ever needs the box to say more
    than one camera's worth."""
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


# ── 8 · the group/line/dot legend is page-level too ───────────────────


def test_the_group_legend_is_not_rendered_per_panel():
    """tuneGroupLegendHtml() used to be prepended into every renderPanel
    call — the same colour key, byte-for-byte, on every one of N cards."""
    fn_start = _PANEL.index("export function renderPanel(")
    fn_end = _PANEL.index("\n}", fn_start)
    assert "tuneGroupLegendHtml()" not in _PANEL[fn_start:fn_end]


def test_the_group_legend_has_one_page_level_home():
    assert "export function initGroupLegend" in _PANEL
    assert "netzGroupLegend" in _PANEL
    tpl = (_REPO / "app" / "web" / "templates" / "partials" / "dashboard.html").read_text(
        encoding="utf-8"
    )
    assert tpl.count('id="netzGroupLegend"') == 1


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_legend_explains_the_dashed_and_solid_lines():
    """„Erklär mir, was ist die gestrichelte Linie und was die feste?"
    — answered on the chart itself now, not only once in chat."""
    out = _js(
        """
        const radar = await import(JS + '/netz/_tune_radar.js');
        const html = radar.tuneGroupLegendHtml();
        console.log(JSON.stringify({
          current: html.includes('Aktuelles Profil'),
          werk: html.includes('Werkseinstellung'),
          changed: html.includes('Geändert'),
          dashed: html.includes('stroke-dasharray'),
        }));
        """
    )
    assert out["current"] is True
    assert out["werk"] is True
    assert out["changed"] is True
    assert out["dashed"] is True, "the Werk swatch must actually look dashed, not just be labelled"


# ── 9 · the header is camera identity + one toggle, nothing else ──────


def test_the_header_has_no_role_badge():
    assert "_ROLE_DE" not in _PANEL
    assert "netz-card-role" not in _PANEL
    assert "netz-card-role" not in _CSS


def test_the_verlauf_toggle_is_a_labelled_chip_not_a_bare_icon():
    """The history-clock icon read as "Aktualisieren" (refresh) to an
    operator — a text label removes the ambiguity outright rather than
    hunting for a clearer icon."""
    hd = _PANEL[_PANEL.index("function _headerHtml(") : _PANEL.index("function _shellHtml(")]
    assert "data-netz-toggle-verlauf" in hd
    assert "netz-chip-toggle" in hd
    assert "_HIST_ICON" not in _PANEL
    assert "'Verlauf'" in hd or '"Verlauf"' in hd or "Verlauf" in hd


def test_there_is_no_icon_only_button_in_the_header():
    """„Ist jetzt dominiert das Icon mit den Informationen, wo ja oben
    schon 'n Icon ist" — the frozen-info button that used to sit beside
    the Verlauf icon is gone; the header's only button is a labelled
    text chip, not a second circular icon-only control."""
    hd = _PANEL[_PANEL.index("function _headerHtml(") : _PANEL.index("function _shellHtml(")]
    assert "netz-view-btn" not in hd
    assert hd.count("<button") == 1


# ── 10 · the panel matches its tile's height, not the phone's ─────────


def test_the_panel_stretches_to_the_tiles_height_on_desktop():
    seg = _DASHBOARD_CSS[_DASHBOARD_CSS.index("@media (min-width: 901px) {") :][:400]
    assert "contain: size" in seg
    assert "align-items: stretch" in seg


def test_the_chart_fills_its_flexed_box_on_desktop():
    seg = _CSS[_CSS.index("@media (min-width: 901px) {") :][:900]
    assert ".netz-card {" in seg and "height: 100%" in seg
    assert ".netz-svg.netz-tune-svg {" in seg
    assert "width: 100%" in seg[seg.index(".netz-svg.netz-tune-svg {") :]


def test_the_radar_is_wider_than_it_is_tall():
    tune_radar = (_JS / "netz" / "_tune_radar.js").read_text(encoding="utf-8")
    m_w = tune_radar[tune_radar.index("TUNE_W = ") :].split("\n", 1)[0]
    m_h = tune_radar[tune_radar.index("TUNE_H = ") :].split("\n", 1)[0]
    w = int("".join(c for c in m_w if c.isdigit()))
    h = int("".join(c for c in m_h if c.isdigit()))
    assert w > h


# ── 11 · every vertex carries real colour, moved or not ───────────────


def test_every_vertex_dot_is_filled_with_its_group_colour():
    tune_radar = (_JS / "netz" / "_tune_radar.js").read_text(encoding="utf-8")
    fn_start = tune_radar.index("function _vertexSvg(")
    fn_end = tune_radar.index("\n}", fn_start)
    fn = tune_radar[fn_start:fn_end]
    assert 'fill="${esc(axis.color)}"' in fn
    assert 'fill="none"' not in fn, "a hollow dot is no longer how 'still at Werk' is shown"
