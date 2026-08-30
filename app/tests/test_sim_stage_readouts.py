"""The Simulieren view's phone height budget: what earns a ROW.

The operator runs this on a 430 px iPhone and asked for the picture
back: "Bitte sparen in der Höhe mehr Platz ein, bringen die Elemente ins
Videodisplay, aber klein, die nur angezeigt werden und gar nicht
andrückbar sind." Three rows were spending height on things that are not
controls, and each one is pinned below:

  · the telemetry cost line ("ROI · 18 % TPU · 4 Kacheln/Rettung ·
    +186 ms"). Pure readout — no gesture does anything to it — yet it
    claimed a full-width row under the control cluster. It now rides the
    top-right corner of the picture, inert, so a tap aimed at a bbox
    still reaches the bbox.
  · the status-legend band. On a phone the legend collapses to ONE 44 px
    "?" chip, so the band was a full-width row carrying a single round
    button. The chip moved into the control row, which is already at
    least 44 px tall — the row it left collapses via :empty.
  · the title bar's prev/next chevrons. live-detect supplies neither
    handler, so both rendered permanently disabled: 2 × 36 px of dead
    width that pushed the camera name off centre.

The rule the readout has to obey is the one this view keeps relearning
(see test_sim_chrome_layout's stage-chrome note): two boxes pinned into
one strip, each sized to its own content, WILL collide on a phone. So
the readout and the overlay toggles opposite it are each capped at half
the stage — structurally unable to reach each other, not merely unlikely
to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static"
_SHELL = _ROOT / "js" / "mediaview" / "shell.js"
_LIVE_CHROME = _ROOT / "js" / "mediaview" / "live-detect-chrome.js"
_CSS_SHELL = _ROOT / "css" / "30g-mediaview-shell.css"
_CSS_TELE = _ROOT / "css" / "31-mediaview-telemetry.css"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    """The declaration block of the first rule whose selector list starts
    with ``selector`` at the beginning of a line."""
    hit = re.search(rf"^{re.escape(selector)}[^{{]*\{{(.*?)\}}", css, re.DOTALL | re.MULTILINE)
    assert hit, f"no rule for {selector!r}"
    return hit.group(1)


# ── the read-only readout moved onto the picture ─────────────────────


def test_the_stage_has_a_slot_for_read_only_readouts():
    src = _read(_SHELL)
    assert 'data-slot="readout"' in src
    # …and it is INSIDE the stage, unlike the control row.
    stage = src.index('data-slot="stage"')
    readout = src.index('data-slot="readout"')
    controls = src.index('data-slot="controls"')
    assert stage < readout < controls, "the readout must be pinned in the stage"


def test_the_readout_never_intercepts_a_tap():
    """ "die nur angezeigt werden und gar nicht andrückbar sind" — the
    bbox overlay and the picture are underneath it."""
    css = _read(_CSS_SHELL)
    assert "pointer-events: none" in _rule(css, ".mv-shell-readout")


def test_the_readout_and_the_toggles_cannot_share_a_pixel():
    """Two pinned corner boxes with no shared width budget is the
    collision this view has already had once (see the M note in 30g): the
    right cluster measured ~360 px on a 390 px stage, slid under the left
    one and was sheared off by overflow:hidden. Half each is a bound, not
    a hope."""
    css = _read(_CSS_SHELL)
    pinned = _rule(css, ".mv-shell-stage > .mv-shell-readout")
    assert "position: absolute" in pinned
    assert "max-width: calc(50% - 12px)" in pinned
    toggles = _rule(css, "#lightboxModal.lb-live-detect .mv-shell-stage > .mv-shell-toggles")
    assert "max-width: calc(50% - 12px)" in toggles


def test_the_cost_line_is_mounted_over_the_picture_not_in_the_control_row():
    src = _read(_LIVE_CHROME)
    body = src[src.rindex("mountModeCost") - 400 : src.rindex("mountModeCost") + 200]
    assert 'data-slot="readout"' in body
    assert 'data-slot="controls"' not in body, "the cost line is back in the control row"


def test_the_readout_pill_reads_over_a_bright_frame_and_a_dark_one():
    """Text straight on video is unreadable against one of the two. The
    card badges solved this with a dark translucent pill + blur; reuse
    that language rather than inventing a second one."""
    css = _read(_CSS_TELE)
    pill = _rule(css, ".mv-shell-readout .mv-tele-cost-line")
    assert "backdrop-filter: blur(" in pill
    assert re.search(r"background: rgba\(0, 0, 0, 0\.\d+\)", pill), "no contrast plate"
    assert "text-shadow" in pill
    assert "border:" not in pill, "no thin border lines — depth via colour contrast"
    radius = re.search(r"border-radius:\s*(\d+)px", pill)
    assert radius and int(radius.group(1)) >= 8, "rounded corners >= 8 px"


def test_the_tone_colours_still_beat_the_over_video_skin():
    """Equal specificity (0,2,0) both ways, so ONLY source order decides
    whether an over-budget 3×3 still shows up red on the picture."""
    css = _read(_CSS_TELE)
    assert css.index(".mv-tele-cost-line[data-tone='over']") > css.index(
        ".mv-shell-readout .mv-tele-cost-line"
    )


# ── the "?"-only row is gone ─────────────────────────────────────────


def test_live_folds_the_legend_into_the_row_that_already_exists():
    """A band of its own for one 44 px chip is ~48 px of a 667 px screen
    spent on whitespace. The control row below the stage is already that
    tall because the mode segments set a 44 px floor."""
    src = _read(_SHELL)
    assert "flags.interactiveMode ? slot('controls') : slot('legendband')" in src
    # The property test_sim_chrome_layout guards has to survive the move:
    # the legend is mounted BELOW the picture, never floated over it.
    assert "renderStatusLegend(legendBand, { float: false })" in src
    assert "float: true" not in src


def test_the_retrigger_pill_keeps_its_own_band():
    """It is a wide labelled pill; the control row it would otherwise
    join is the one that already has to fit Stream + four segments at
    375 px."""
    src = _read(_SHELL)
    assert "renderRetriggerButton(slot('legendband')" in src


def test_the_emptied_band_collapses_instead_of_reserving_a_row():
    css = _read(_CSS_SHELL)
    assert "display: none" in _rule(css, ".mv-shell-legendband:empty")
    # The band's live-only skin (its own padding, and the margin-left that
    # pushed the chip to the far edge of a row it owned alone) described a
    # row live no longer fills — dead weight, and a magnet for the next
    # person trying to work out where the chip actually lives.
    assert "#lightboxModal.lb-live-detect .mv-shell-legendband .mv-legend" not in css


def test_the_chip_sits_at_the_end_of_the_control_row():
    css = _read(_CSS_SHELL)
    rule = _rule(css, "#lightboxModal.lb-live-detect .mv-shell-controls .mv-legend")
    assert "margin-left: auto" in rule
    assert "flex-shrink: 0" in rule, "a 44 px touch target must not be crushed"


# ── the camera name is centred, the dead chevrons are gone ───────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_a_mode_that_pages_through_nothing_renders_no_chevrons():
    out = _js(
        """
        const tb = await import(JS + '/mediaview/title-bar.js');
        const render = (actions) => {
          const host = document.createElement('div');
          tb.renderTitleBar(host, { item: { camera_name: 'Hof' }, actions });
          return host.innerHTML;
        };
        console.log(JSON.stringify({
          live: render({ onClose: () => {} }),
          paging: render({ onClose: () => {}, onNext: () => {} }),
        }));
        """
    )
    assert 'data-nav="prev"' not in out["live"], "live-detect pages nowhere — no dead chevrons"
    assert 'data-nav="next"' not in out["live"]
    assert 'data-act="close"' in out["live"], "the close button is never optional"
    # A mode that CAN page keeps both, the unreachable end merely disabled
    # — that end-of-list affordance is a real one and must not be lost.
    assert 'data-nav="prev"' in out["paging"] and "disabled" in out["paging"]
    assert 'data-nav="next"' in out["paging"]


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_title_sits_between_two_equal_side_tracks():
    """Centring needs a lead cell even when it is empty — otherwise grid
    auto-placement drops the title into column 1 and it is left-aligned
    again the moment a mode has no prev handler."""
    out = _js(
        """
        const tb = await import(JS + '/mediaview/title-bar.js');
        const host = document.createElement('div');
        tb.renderTitleBar(host, { item: { camera_name: 'Hof' }, actions: {} });
        console.log(JSON.stringify({ html: host.innerHTML }));
        """
    )
    assert 'class="mv-tb-lead"' in out["html"]
    assert out["html"].index("mv-tb-lead") < out["html"].index("mv-tb-titles")
    assert out["html"].index("mv-tb-titles") < out["html"].index("mv-tb-actions")


def test_the_title_bar_is_a_three_track_grid():
    css = _read(_CSS_SHELL)
    bar = _rule(css, ".mv-titlebar")
    assert "display: grid" in bar
    assert "grid-template-columns: 1fr minmax(0, auto) 1fr" in bar, (
        "two equal side tracks are what centre the name in the BAR rather "
        "than in whatever the clusters left over"
    )
    titles = _rule(css, ".mv-tb-titles")
    assert "justify-self: center" in titles
    assert "min-width: 0" in titles, "a long camera name must ellipsis, not shove the close button"


def test_an_absent_timestamp_costs_no_line_box():
    """Live has no clip time. An empty span still reserves a line and
    pushed the picture down by it."""
    css = _read(_CSS_SHELL)
    assert "display: none" in _rule(css, ".mv-tb-time:empty")


def test_the_title_bar_keeps_its_44px_touch_targets():
    """36 px visible + a -4 px inset ::before = 44 px of hit area. The
    grid rewrite must not have dropped either half."""
    css = _read(_CSS_SHELL)
    btn = _rule(css, ".mv-tb-nav,\n.mv-tb-close")
    assert "width: 36px" in btn and "height: 36px" in btn
    inset = _rule(css, ".mv-tb-nav::before,\n.mv-tb-close::before")
    assert "inset: -4px" in inset
    assert "position: absolute" in inset


def test_no_touched_rule_measures_itself_in_vh():
    """iOS collapses the address bar and vh does not follow."""
    for path in (_CSS_SHELL, _CSS_TELE):
        css = _read(path)
        for hit in re.finditer(r"\b\d+(?:\.\d+)?vh\b", css):
            line_start = css.rfind("\n", 0, hit.start()) + 1
            line = css[line_start : css.find("\n", hit.start())]
            assert "vw" in line or "60vw" in line, f"{path.name}: raw vh in {line.strip()!r}"
