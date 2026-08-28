"""Regression guards for the Simulieren view's chrome layout on iPhone.

Everything here pins a STRUCTURAL property — an arrangement that cannot
collide — rather than a pixel value, because the failures were all of
the "two independently-sized boxes were asked to share one 390 px strip"
kind and re-appear the moment someone re-pins a cluster to a corner.

  · Stage chrome. The overlay-toggle pills (top-left) and the Stream +
    detection-mode cluster (top-right) were both `position: absolute`
    inside the same stage, each sized to its own content with no shared
    width budget. On a 390 px iPhone the right cluster alone measured
    ~360 px, slid underneath the left one, and had its leading chips
    sheared off mid-word by the stage's overflow:hidden. The interactive
    cluster now lives in its own row BELOW the stage, in normal flow.

  · Swimlane chips. Anchored by their LEFT edge at
    `calc(pct% - 24px)`, so a chip carrying an "×6" label overshot 100 %
    and lost its label to the lane's overflow:hidden.

  · Dashboard corner buttons. `.cv-chrome-btn` declares an explicit
    `min-width: 36px`, which overrides the `min-width: auto` that
    normally stops a flex item collapsing under its own content — so the
    "Simulieren" button squeezed to 36 px while its label kept rendering
    at ~110 px and spilled over the cog next to it ("Simul⚙re").
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static"
_SHELL = _ROOT / "js" / "mediaview" / "shell.js"
_LIVE_CHROME = _ROOT / "js" / "mediaview" / "live-detect-chrome.js"
_SWIMLANE = _ROOT / "js" / "mediaview" / "live-swimlane.js"
_MODE = _ROOT / "js" / "mediaview" / "mode-indicator.js"
_CSS_SHELL = _ROOT / "css" / "30g-mediaview-shell.css"
_CSS_DASH = _ROOT / "css" / "03-dashboard.css"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


# ── stage chrome ─────────────────────────────────────────────────────


def test_shell_has_a_control_row_below_the_stage():
    src = _read(_SHELL)
    assert 'data-slot="controls"' in src
    # …and it is a sibling of the stage, not a child of it.
    stage = src.index('data-slot="stage"')
    controls = src.index('data-slot="controls"')
    assert controls > stage
    between = src[stage:controls]
    assert between.count("</div>") >= 1, "controls slot must close out of the stage"


def test_interactive_modes_relocate_the_stream_mode_cluster():
    src = _read(_SHELL)
    assert "_relocateControls" in src
    body = src[src.index("function _relocateControls") :]
    body = body[: body.index("\n}")]
    assert "if (!interactive) return;" in body, "read-only modes keep their badge on the frame"
    assert 'data-slot="controls"' in body and 'data-slot="topright"' in body
    assert "_relocateControls(root, flags.interactiveMode)" in src


def test_pinned_chrome_is_scoped_to_direct_stage_children():
    """`position: absolute` must hang off a `.mv-shell-stage >` selector.
    An unscoped `.mv-shell-topright { position: absolute }` would keep
    the relocated cluster absolutely positioned in its new row and put
    it straight back on top of something."""
    css = _read(_CSS_SHELL)
    for cls in (".mv-shell-toggles", ".mv-shell-topright"):
        pinned = re.search(rf"\.mv-shell-stage > {re.escape(cls)}\s*\{{(.*?)\}}", css, re.DOTALL)
        assert pinned, f"{cls} has no stage-scoped pinning rule"
        assert "position: absolute" in pinned.group(1)
        base = re.search(rf"^{re.escape(cls)}\s*\{{(.*?)\}}", css, re.DOTALL | re.MULTILINE)
        assert base, f"{cls} has no unscoped base rule"
        assert "position:" not in base.group(1), f"{cls} base rule must not position anything"


def test_pinned_clusters_are_width_capped():
    """A cluster wider than the stage gets clipped by overflow:hidden;
    capping + wrapping keeps every chip reachable instead."""
    css = _read(_CSS_SHELL)
    for cls in (".mv-shell-toggles", ".mv-shell-topright"):
        rule = re.search(rf"\.mv-shell-stage > {re.escape(cls)}\s*\{{(.*?)\}}", css, re.DOTALL)
        assert "max-width: calc(100% - 16px)" in rule.group(1), f"{cls} is not width-capped"
        base = re.search(rf"^{re.escape(cls)}\s*\{{(.*?)\}}", css, re.DOTALL | re.MULTILINE)
        assert "flex-wrap: wrap" in base.group(1), f"{cls} must wrap rather than overflow"


def test_live_offers_only_the_detection_overlays():
    """Zone / mask polygons have no bearing on what the simulator
    computes (the endpoint gates on score threshold + object filter,
    never on geometry) — four chips over a 220 px stage for a question
    the cam-edit zone editor already answers."""
    src = _read(_LIVE_CHROME)
    m = re.search(r"overlays:\s*\{([^}]*)\}", src)
    assert m, "live-detect no longer declares an overlays set"
    decl = m.group(1)
    assert "bboxes" in decl and "trails" in decl
    assert "zones" not in decl and "masks" not in decl


def test_mode_segments_stay_short_enough_to_share_one_row():
    """Four segments plus the Stream chip have to fit ~360 px. The old
    'Motion-ROI' label alone was wider than the other three together."""
    src = _read(_MODE)
    block = src[src.index("MV_DETECTION_MODES = [") :]
    block = block[: block.index("];")]
    labels = re.findall(r"\[\s*'[^']+',\s*'([^']+)'", block)
    assert labels, "mode labels not parseable"
    assert all(len(lbl) <= 4 for lbl in labels), f"a segment label is too long: {labels}"
    assert "Motion-ROI" in block, "the full term must survive in the tooltip"


def test_mode_group_carries_a_visible_key():
    """Below the picture, four bare chips name nothing."""
    src = _read(_MODE)
    assert "mv-sim-seg-k" in src
    assert "Modus" in src


def test_control_row_skin_wins_the_cascade_over_the_on_frame_skin():
    """`.mv-shell-topright .mv-sim-ctl` and `.mv-shell-controls
    .mv-sim-ctl` carry IDENTICAL specificity, so source order is the only
    thing deciding which skin applies. The control-row block must stay
    BELOW the on-frame (G2 dark-glass) block — moving it up silently
    restores the dark-on-dark chips and the untrimmed padding."""
    css = _read(_CSS_SHELL)
    for on_frame, in_row in (
        (".mv-shell-topright .mv-sim-ctl,", ".mv-shell-controls .mv-sim-ctl,"),
        (
            ".mv-shell-topright .mv-sim-seg[data-on='1'] .mv-sim-ctl-chip",
            ".mv-shell-controls .mv-sim-seg[data-on='1'] .mv-sim-ctl-chip",
        ),
        (".mv-shell-topright .mv-sim-seg-group", ".mv-shell-controls .mv-sim-seg-group"),
    ):
        assert on_frame in css and in_row in css
        assert css.index(in_row) > css.index(
            on_frame
        ), f"{in_row!r} must come after {on_frame!r} — equal specificity, order decides"


# ── swimlane right edge ──────────────────────────────────────────────


def test_swimlane_chips_anchor_to_their_right_edge():
    src = _read(_SWIMLANE)
    body = src[src.index("function _syncBars") :]
    assert "style=\"right:" in body or "right:${right}" in body, "chips must anchor right"
    assert (
        "- ${_CHIP_W}px" not in body.split("const conn")[-1]
    ), "no left-anchored chip placement — that is what overshot 100 %"


def test_swimlane_axis_end_ticks_anchor_to_their_own_edge():
    src = _read(_SWIMLANE)
    body = src[src.index("const axisLabels") :]
    body = body[: body.index("const gridlines")]
    assert "'left:0'" in body and "'right:0'" in body


def test_swimlane_panel_has_side_padding():
    """Edge-to-edge, the LIVE pill sat flush against the screen border."""
    css = _read(_ROOT / "css" / "30f-live-detect-skeleton.css")
    rule = re.search(r"^\.mv-ld-swim \{(.*?)\}", css, re.DOTALL | re.MULTILINE)
    assert rule, ".mv-ld-swim rule missing"
    pad = re.search(r"padding:\s*([^;]+);", rule.group(1))
    assert pad, ".mv-ld-swim has no padding"
    parts = pad.group(1).split()
    assert len(parts) >= 2 and parts[1] != "0", f"no horizontal padding: {pad.group(1)}"


# ── dashboard corner cluster ─────────────────────────────────────────


def test_corner_buttons_never_shrink_below_their_content():
    css = _read(_CSS_DASH)
    rule = re.search(r"^\.cv-chrome-btn \{(.*?)\}", css, re.DOTALL | re.MULTILINE)
    assert rule, ".cv-chrome-btn rule missing"
    assert "flex-shrink: 0" in rule.group(
        1
    ), "an explicit min-width lets flex crush the SIM button under its own label"


def test_sim_label_abbreviates_at_phone_tile_width():
    """A single-column iPhone tile is ~343-377 px wide. The container
    query has to fire ABOVE that, or the phone never gets the compact
    label the rule exists for."""
    css = _read(_CSS_DASH)
    m = re.search(r"@container \(max-width:\s*(\d+)px\)", css)
    assert m, "the SIM-label container query is gone"
    assert int(m.group(1)) >= 380, f"breakpoint {m.group(1)}px is below phone tile width"


def test_bottom_corner_clusters_do_not_both_reserve_half_the_tile():
    """`50% - 110px` each left 77 px apiece on a 374 px tile and a 220 px
    dead zone between them."""
    css = _read(_CSS_DASH)
    for cls in (".cv-chrome-bottom-left", ".cv-chrome-bottom-right"):
        rule = re.search(rf"^{re.escape(cls)} \{{(.*?)\}}", css, re.DOTALL | re.MULTILINE)
        assert rule, f"{cls} rule missing"
        assert "calc(50% - 110px)" not in rule.group(1), f"{cls} still reserves half the tile"


# ── desktop: the panels row must survive a wide window ───────────────
#
# `.mv-shell-stage` is sized `aspect-ratio: 16/9` off 100 % width inside a
# column pinned to 100dvh, and `.mv-shell-panels` was the only flexible
# row with `flex-basis: 0`. Past ~1050 px the stage alone exceeded the
# column, free space went negative, and the panels row resolved to 0 px —
# then its own overflow:hidden erased the tab strip. No ancestor could
# scroll to it either. Both guards below pin the two properties that
# actually broke.


def test_live_panels_row_has_a_height_floor():
    css = _read(_CSS_SHELL)
    rule = re.search(r"#lightboxModal\.lb-live-detect \.mv-shell-panels \{(.*?)\}", css, re.DOTALL)
    assert rule, "the live panels rule is gone"
    body = rule.group(1)
    assert "flex: 1 1 0" in body
    assert re.search(r"min-height:\s*min\(", body), (
        "flex:1 1 0 with no floor resolves to 0 px whenever the rows above "
        "over-subscribe the 100dvh column — that is the desktop bug"
    )


def test_desktop_gives_the_panels_their_own_column():
    """A wide window has more room on the HORIZONTAL axis, which a single
    stacked column cannot spend. The panels get column 2, full height."""
    css = _read(_CSS_SHELL)
    grid_at = css.rindex("grid-template-columns")
    m = None
    for hit in re.finditer(r"@media \(min-width:\s*(\d+)px\)", css):
        if hit.start() < grid_at:
            m = hit
    assert m, "no desktop breakpoint guards the live grid"
    assert int(m.group(1)) >= 1000, "the breakpoint must sit above phone/tablet widths"
    desktop = css[m.start() :]
    assert "grid-template-columns" in desktop
    panels = re.search(
        r"#lightboxModal\.lb-live-detect \.mv-shell-panels \{([^}]*grid-column[^}]*)\}",
        desktop,
        re.DOTALL,
    )
    assert panels, "the panels are not placed into their own grid column"
    assert "grid-column: 2" in panels.group(1)


def test_compact_mode_falls_back_to_one_column():
    """ "Video ausblenden" folds the whole left column away; keeping the
    two-column grid would leave the panels beside 1fr of nothing."""
    css = _read(_CSS_SHELL)
    assert "#lightboxModal.lb-live-detect .mv-shell[data-compact='1']" in css


# ── the legend must not be placed over the picture ───────────────────


def test_live_mounts_the_legend_inline_not_over_the_frame():
    """The floating legend positioned itself "opposite the OSD band", but
    where a camera burns its timestamp is invisible to this app — the flag
    said top, the camera said bottom, and the two collided. Below the
    frame is the only placement that cannot collide."""
    src = _read(_SHELL)
    assert "renderStatusLegend(legendBand, { float: false })" in src
    assert "float: true" not in src, "live must not float the legend over the stage"
    assert "osdBand" not in src, "the OSD-avoid guess is what produced the overlap"


# ── swimlane colour must agree with the painted overlays ─────────────


def test_swimlane_lane_colour_is_the_track_number_only():
    """Colour encodes IDENTITY everywhere (bbox, trail, legend tail
    "Farbe = Person-Nr."). The lane used to repaint a filtered track slate,
    so an orange trail on the picture had no orange in the strip below."""
    src = _read(_SWIMLANE)
    body = src[src.index("function _computeLanes") : src.index("function _buildStructure")]
    assert "liveTrackColor(lane.num)" in body
    assert "_MASKED_COLOR" not in src, "status must not travel in the colour channel"
    assert "lane.status = mvStatusCategory" in body, "status needs the legend's vocabulary"


def test_filtered_tracks_are_folded_not_dropped():
    """They stay reachable (the operator needs to see what the detector is
    spending inferences on) but must not crowd out the real lanes."""
    src = _read(_SWIMLANE)
    assert "data-action=\"swim-filtered\"" in src
    body = src[src.index("function _computeLanes") :]
    assert (
        "every((s) => s.verdict === 'filtered')" in body
    ), "a lane that passed even once is a real track having a bad frame"
