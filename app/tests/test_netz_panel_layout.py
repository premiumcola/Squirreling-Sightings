"""One Erkennungsprofil panel per camera, beside its own Live-Feed tile.

The operator, from a screenshot of the dashboard's top section: three
independent panels, one per camera, each directly beside its own camera
tile — not one shared panel next to the whole grid. That retires the
single `#netz` section with its camera-chip switcher entirely; these
tests pin the replacement shape.

One operator complaint from the PREVIOUS shape still applies verbatim to
every panel now (it was never about the page-level chrome that is gone):

  5. Ghost-Spuren was a full-width row of its own for a single switch.
     It is now an icon button in the header — the controls row it used
     to be a chip in is gone too ("Brauchen wir's, sonst nehmen's raus
     und macht das Netz einfach viel größer").

And the one that started the latest reshape: the net was "so viel zu
klein, man kann's gar nicht erkennen" — a 560 x 300 viewBox letterboxed
inside a box far bigger than that. The radar is now drawn at its chart
box's own measured px size (section 10), the header is one button-row
tall, and the staging bar overlays the net instead of reserving a row.

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


# ── 4 · the ghost toggle is a header icon button, not a row ──────────

_GHOST_SENTENCE = "Ghost: Spur ohne Objekt — läuft nur noch in der Gnadenfrist weiter, "


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_ghost_toggle_is_a_header_icon_button_not_a_row():
    """It sits in the header (rendered by _panel.js for BOTH sub-views),
    so the net body no longer carries it — and no controls row either."""
    out = _js(
        f"""
        {_SETUP}
        const btn = cards.ghostToggleHtml('cam_a');
        const body = cards.netBodyHtml({{ id: 'cam_a', name: 'Werkstatt' }});
        console.log(JSON.stringify({{
          hasGhost: btn.includes('data-tune-ghost'),
          isIconBtn: btn.includes('netz-view-btn'),
          pressed: btn.includes('aria-pressed="true"'),
          label: btn.includes('aria-label="Ghost-Spuren ausblenden'),
          tip: btn.includes('title="Ghost-Spuren ausblenden'),
          explains: btn.includes('Gnadenfrist'),
          bodyHasGhost: body.includes('data-tune-ghost'),
          bodyHasControls: body.includes('netz-card-controls'),
        }}));
        """
    )
    assert out["hasGhost"] is True
    assert out["isIconBtn"] is True
    assert out["pressed"] is True, "the toggle does not report its state to assistive tech"
    assert out["label"] is True, "an icon-only button needs its explanation as aria-label"
    assert out["tip"] is True
    assert out["explains"] is True
    assert out["bodyHasGhost"] is False, "the ghost toggle is still in the net body"
    assert out["bodyHasControls"] is False, "the controls row is still reserving height"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_key_row_says_what_a_ghost_is_without_a_hover():
    """„Ich weiß immer noch nicht, was das bedeutet." A `title` is a thing
    no phone ever shows, so the sentence stands in the key row under the
    net — and it names the switch's CURRENT state, not just the concept."""
    out = _js(
        f"""
        {_SETUP}
        const key = await import(JS + '/netz/_key.js');
        const cam = {{ id: 'cam_a', name: 'Werkstatt' }};
        const onRow = cards.netBodyHtml(cam, {{ width: 700, height: 340 }});
        S.netzState.states.cam_a.tuning.track_filter_ghosts = false;
        const offRow = cards.netBodyHtml(cam, {{ width: 700, height: 340 }});
        console.log(JSON.stringify({{
          inBody: onRow.includes('{_GHOST_SENTENCE}'),
          hidden: onRow.includes('{_GHOST_SENTENCE}wird ausgeblendet'),
          shown: offRow.includes('{_GHOST_SENTENCE}wird angezeigt'),
          ownLine: onRow.includes('netz-key-ghost'),
          sameGlyph: cards.ghostToggleHtml('cam_a').includes(
            key.ghostIconSvg(18).slice(key.ghostIconSvg(18).indexOf('<path'))),
        }}));
        """
    )
    assert out["inBody"] is True, "the explanation is still tooltip-only"
    assert out["hidden"] is True
    assert out["shown"] is True, "the key must follow the switch, not describe one fixed state"
    assert out["ownLine"] is True
    assert out["sameGlyph"] is True, "the key and the button must show the same ghost"


def test_the_ghost_line_never_pushes_a_colour_chip_around():
    seg = _CSS[_CSS.index(".netz-key-ghost {") :]
    assert "flex-basis: 100%" in seg[: seg.index("}")]


def test_the_controls_row_and_the_chip_style_are_gone():
    assert "netz-card-controls" not in _CARDS
    assert "netz-card-controls" not in _CSS
    assert "netz-chip-toggle" not in _CARDS
    assert "netz-chip-toggle" not in _PANEL
    assert "netz-chip-toggle" not in _CSS


def test_the_header_buttons_keep_a_44px_touch_target():
    btn = _CSS[_CSS.index(".netz-view-btn {") :]
    rule = btn[: btn.index("}")]
    assert "width: 44px" in rule
    assert "height: 44px" in rule


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


# ── 8 · the legend sits under the net it explains ─────────────────────


def test_the_legend_has_no_page_level_home_any_more():
    """It sat above the FIRST camera tile, explaining a chart nowhere near
    it — "die Legende steht ganz oben über der ersten Videokachel, dort
    ergibt sie keinen Sinn"."""
    assert "initGroupLegend" not in _PANEL
    assert "netzGroupLegend" not in _PANEL
    tpl = (_REPO / "app" / "web" / "templates" / "partials" / "dashboard.html").read_text(
        encoding="utf-8"
    )
    assert "netzGroupLegend" not in tpl
    # The separate "Was zusammen wirkt" / "Werte, die fest bleiben" box
    # stays page-level — it is reference text, not a key to a chart.
    assert tpl.count('id="netzCombosBox"') == 1


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_every_panel_ends_with_the_legend_row():
    out = _js(
        f"""
        {_SETUP}
        const html = cards.netBodyHtml({{ id: 'cam_a', name: 'Werkstatt' }},
                                       {{ width: 700, height: 340 }});
        console.log(JSON.stringify({{
          hasRow: html.includes('netz-key'),
          once: html.split('netz-key"').length - 1,
          afterChart: html.indexOf('netz-key') > html.indexOf('netz-tune-svg'),
          block: html.includes('netz-tgroups'),
        }}));
        """
    )
    assert out["hasRow"] is True
    assert out["once"] == 1, "the key is one row, not one per group"
    assert out["afterChart"] is True, "the key belongs under the net, not above it"
    assert out["block"] is False, "the old multi-line block is still being rendered"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_legend_explains_the_dashed_and_solid_lines():
    """„Erklär mir, was ist die gestrichelte Linie und was die feste?"
    — answered under the chart itself now, not only once in chat."""
    out = _js(
        """
        const key = await import(JS + '/netz/_key.js');
        const html = key.netKeyHtml();
        console.log(JSON.stringify({
          current: html.includes('Aktuelles Profil'),
          werk: html.includes('Werkseinstellung'),
          changed: html.includes('Geändert'),
          dashed: html.includes('stroke-dasharray'),
          groups: html.includes('Tempo') && html.includes('Meldung'),
        }));
        """
    )
    assert out["current"] is True
    assert out["werk"] is True
    assert out["changed"] is True
    assert out["dashed"] is True, "the Werk swatch must actually look dashed, not just be labelled"
    assert out["groups"] is True, "the group colour key moved with the rest of the legend"


def test_the_legend_row_wraps_and_carries_no_margin_of_its_own():
    """It shares the panel's height with the net, so it may wrap on a
    phone but must never push the net smaller than it has to."""
    seg = _CSS[_CSS.index(".netz-key {") :]
    rule = seg[: seg.index("}")]
    assert "flex-wrap: wrap" in rule
    assert "font-size: 11px" in rule
    assert "margin" not in rule


def test_the_measured_box_is_the_one_the_legend_left_over():
    """The probe lays out the REAL body minus the radar — chart box plus
    legend row — so the radar is drawn for the space actually left."""
    assert "export function netProbeHtml" in _CARDS
    assert "netz-key" not in _PANEL, "the probe must not rebuild the legend markup itself"
    fn_start = _PANEL.index("function _measureChart(")
    fn_end = _PANEL.index("\n}", fn_start)
    assert "netProbeHtml(camId)" in _PANEL[fn_start:fn_end]


# ── 9 · the header is ONE row: identity + two icon buttons ───────────

_VERLAUF_TITLE = "Verlauf – frühere Profile dieser Kamera ansehen und wiederherstellen"


def _header_src():
    return _PANEL[_PANEL.index("function _headerHtml(") : _PANEL.index("function _shellHtml(")]


def test_the_header_has_no_role_badge():
    assert "_ROLE_DE" not in _PANEL
    assert "netz-card-role" not in _PANEL
    assert "netz-card-role" not in _CSS


def test_the_header_names_the_panel_not_the_camera_again():
    """„Links steht die Kachel mit Werkstatt, rechts das Panel mit
    Werkstatt — doppelt." The camera's own tile sits directly beside this
    header and already carries the name; the icon (camera colour, camera
    glyph) is the assignment, so the words name the thing instead."""
    hd = _header_src()
    assert "<h4>${_PANEL_TITLE}</h4>" in hd
    assert "const _PANEL_TITLE = 'Erkennungsnetz'" in _PANEL
    assert "esc(cam.name)" not in hd.split("<h4>")[0].split("netz-card-ic")[0]
    assert "<h4>${esc(cam.name)}</h4>" not in hd
    # …but the name is still the icon's accessible name: a screen reader
    # must be able to tell one panel's net from the next.
    assert 'aria-label="${esc(cam.name)}"' in hd


def test_the_header_is_icon_name_and_exactly_two_icon_buttons():
    """Camera icon + title on the left, Verlauf and ghost on the right —
    nothing else, so the row is one 44 px button tall and every other
    px of the panel goes to the net."""
    hd = _header_src()
    assert "netz-card-ic" in hd
    assert "<h4>" in hd
    assert "data-netz-toggle-verlauf" in hd
    assert "ghostToggleHtml(camId)" in hd
    # One literal <button> (Verlauf) + the ghost one built in _cards.js.
    assert hd.count("<button") == 1
    assert hd.count("netz-view-btn") == 1
    assert "netz-card-controls" not in hd


def test_the_verlauf_button_explains_itself_in_its_tooltip():
    """The history-clock icon once read as "Aktualisieren" (refresh) to
    an operator and got a text label for it. That label cost header
    height; the explanation now rides the button as title + aria-label,
    verbatim, and the pressed state is exposed for assistive tech."""
    hd = _header_src()
    assert f"const _VERLAUF_TITLE = '{_VERLAUF_TITLE}'" in _PANEL
    assert "_HISTORY_ICON" in hd
    assert 'aria-label="${title}" title="${title}"' in hd
    assert "aria-pressed=" in hd


def test_the_header_row_ellipsises_the_name_instead_of_wrapping():
    """A long camera name must not make the header two lines tall, and
    the buttons must not be pushed with `margin-left: auto` (the documented
    iOS inline-flex hazard) — the h4 eats the slack instead."""
    hd = _CSS[_CSS.index(".netz-card-hd h4 {") :]
    rule = hd[: hd.index("}")]
    assert "white-space: nowrap" in rule
    assert "text-overflow: ellipsis" in rule
    assert "flex: 1 1 auto" in rule
    hd_rule = _CSS[_CSS.index(".netz-card-hd {") :]
    assert "margin-left: auto" not in hd_rule[: hd_rule.index("}")]


# ── 10 · the panel matches its tile's height, not the phone's ─────────


def test_the_panel_stretches_to_the_tiles_height_on_desktop():
    seg = _DASHBOARD_CSS[_DASHBOARD_CSS.index("@media (min-width: 901px) {") :][:400]
    assert "contain: size" in seg
    assert "align-items: stretch" in seg


def test_the_chart_box_fills_the_flexed_card_on_desktop():
    """The card is the tile's height; the body flexes to fill it; the
    chart box takes whatever the body has left."""
    seg = _CSS[_CSS.index("@media (min-width: 901px) {") :][:900]
    assert ".netz-card {" in seg and "height: 100%" in seg
    chart = seg[seg.index(".netz-card-chart {") :]
    assert "flex: 1 1 auto" in chart[: chart.index("}")]
    assert "min-height: 0" in chart[: chart.index("}")]


def test_the_chart_box_has_a_real_height_on_a_phone():
    """No tile height to inherit in the single-column layout — a clamp()
    whose 260 px floor wins on a 375/393 px screen (60vw = 225–236 px)."""
    chart = _CSS[_CSS.index(".netz-card-chart {") :]
    rule = chart[: chart.index("}")]
    assert "height: clamp(260px, 60vw, 380px)" in rule
    assert "position: relative" in rule
    assert "vh" not in rule


def test_the_svg_is_edge_to_edge_in_both_directions():
    """Outside any media block: the same 100 % x 100 % on every screen.
    Letterboxing is what made the net "so viel zu klein"."""
    svg = _CSS[_CSS.index(".netz-svg.netz-tune-svg {") :]
    rule = svg[: svg.index("}")]
    assert "width: 100%" in rule
    assert "height: 100%" in rule
    assert "display: block" in rule


# ── 10b · the radar is drawn at the box's own px size ─────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_net_body_draws_the_radar_at_the_measured_size():
    """viewBox == the box's px size, 1 unit = 1 px — a bigger box is a
    bigger ring, not the same 560 x 300 drawing with more margin."""
    out = _js(
        f"""
        {_SETUP}
        const cam = {{ id: 'cam_a', name: 'Werkstatt' }};
        const big = cards.netBodyHtml(cam, {{ width: 700, height: 340 }});
        const none = cards.netBodyHtml(cam);
        console.log(JSON.stringify({{
          bigBox: big.includes('viewBox="0 0 700 340" width="700" height="340"'),
          fallback: none.includes('viewBox="0 0 560 300" width="560" height="300"'),
          chartWrapsSvg: big.indexOf('netz-card-chart') < big.indexOf('netz-tune-svg'),
        }}));
        """
    )
    assert out["bigBox"] is True
    assert out["fallback"] is True
    assert out["chartWrapsSvg"] is True


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_staging_bar_lives_inside_the_chart_box():
    """It overlays the net's bottom edge (absolute inside .netz-card-chart,
    see the CSS test below) — so it has to be a child of that box, and it
    only exists while values are staged."""
    out = _js(
        f"""
        {_SETUP}
        const cam = {{ id: 'cam_a', name: 'Werkstatt' }};
        const clean = cards.netBodyHtml(cam, {{ width: 700, height: 340 }});
        S.stageValue('cam_a', 'roi_mode', '2x2');
        const staged = cards.netBodyHtml(cam, {{ width: 700, height: 340 }});
        const chartEnd = staged.lastIndexOf('</div>');
        console.log(JSON.stringify({{
          cleanHasBar: clean.includes('netz-stage'),
          stagedHasBar: staged.includes('netz-stage'),
          barInsideChart: staged.indexOf('netz-stage') < chartEnd,
        }}));
        """
    )
    assert out["cleanHasBar"] is False, "the bar reserves height while nothing is staged"
    assert out["stagedHasBar"] is True
    assert out["barInsideChart"] is True


def test_the_staging_bar_is_an_overlay_not_a_row():
    stage = _CSS[_CSS.index(".netz-stage {") :]
    rule = stage[: stage.index("}")]
    assert "position: absolute" in rule
    assert "bottom:" in rule
    assert "position: fixed" not in rule
    assert "position: sticky" not in rule


def test_the_panel_measures_the_box_before_drawing_into_it():
    """The empty-probe measurement: lay out an empty .netz-card-chart in
    the body, read its px size, then render the radar for that size."""
    assert "function _measureChart(" in _PANEL
    assert "getBoundingClientRect()" in _PANEL
    assert "netBodyHtml(cam, _measureChart(body, camId))" in _PANEL


def test_the_panel_repaints_when_its_box_changes_size():
    """A ResizeObserver per slot (rotation, sidebar, window drag) on top
    of the window-resize path in netz/index.js — and never mid-drag, which
    would tear the dragged SVG out from under the finger."""
    assert "ResizeObserver" in _PANEL
    assert "function _repaintIfResized(" in _PANEL
    fn_start = _PANEL.index("function _repaintIfResized(")
    fn_end = _PANEL.index("\n}", fn_start)
    assert "isTuneDragging()" in _PANEL[fn_start:fn_end]
    assert "export function redrawOnResize" in _PANEL


def test_the_fallback_radar_is_wider_than_it_is_tall():
    geometry = (_JS / "netz" / "_tune_geometry.js").read_text(encoding="utf-8")
    m_w = geometry[geometry.index("TUNE_W = ") :].split("\n", 1)[0]
    m_h = geometry[geometry.index("TUNE_H = ") :].split("\n", 1)[0]
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
