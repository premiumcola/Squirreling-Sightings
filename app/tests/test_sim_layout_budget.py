"""The Simulieren shell's height budget, solved arithmetically.

The layout is a column pinned to exactly 100dvh with ONE elastic row, so
every regression in it has been the same shape: two boxes were given a
claim on the same pixels and the loser collapsed to nothing. Screenshots
find that late and only on the device that was photographed. The budget
is small enough to solve on paper, so this file solves it — for the five
viewports the view is actually used at — against the numbers parsed out
of the stylesheet, so the arithmetic and the CSS cannot drift apart.

Two failures are pinned here, one of each direction:

  * `min-height: min(46dvh, 460px)` on the panels row. A floor on the
    only flexible row in a fixed-height column does not create space, it
    takes it from whichever row can still yield — the stage, whose
    children are all absolutely positioned and whose automatic minimum is
    therefore 0. Meant to rescue the desktop, it starved the phone: at
    375 × 667 the 16:9 stage fell from 211 px to about 58 px, a letterbox
    strip where the live picture had been. It was then switched OFF above
    1000 px, which is the only place it could have helped.

  * `(100dvh - 230px)` as the desktop grid's chrome allowance. Real fixed
    chrome is around 300 px, and the playbar inside it is content-sized
    (44 px per swimlane lane), so the constant was both stale and
    unstalable. Under-counting it over-subscribes the left column, and
    #lightboxInner is `overflow: hidden !important` in this mode — what
    falls off the bottom is gone, not scrolled to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_CSS = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "web"
    / "static"
    / "css"
    / "30g-mediaview-shell.css"
)

# The five viewports named in the review, CSS px.
VIEWPORTS = [
    ("iPhone SE", 375, 667),
    ("iPhone 14", 390, 844),
    ("short desktop", 900, 600),
    ("laptop", 1440, 900),
    ("desktop", 1920, 1080),
]

# Fixed chrome envelope, px. Lower bound: title bar 40 (.mv-titlebar
# min-height) + control row 54 (chip row + the telemetry cost line) +
# legend band 48 (the 44 px "?" chip plus its padding) + playbar ~78 (one
# swimlane lane) + 5 × 4 px column gaps. Upper bound: the same with a
# three-lane playbar. The layout has to hold across the whole range —
# that is the property the hard-coded 230 px did not have.
CHROME_MIN = 240
CHROME_MAX = 340

# What each region needs to still be the thing it is called.
MIN_STAGE_PX = 140  # below this the 16:9 frame is a letterbox strip
MIN_PANELS_PX = 96  # the tab strip plus one line of the active panel


@dataclass(frozen=True)
class Layout:
    """The handful of numbers the stylesheet actually decides."""

    grid_min_width: int  # px — breakpoint the two-column grid starts at
    grid_left_floor: int  # px — clamp() lower bound on the left column
    grid_left_vw: int  # vw — clamp() upper bound on the left column
    grid_right_min: int  # px — minmax() floor on the panels column
    grid_col_gap: int  # px
    stage_cap_dvh: float | None  # share-of-column cap, stacked layout
    panels_floor_dvh: float | None  # legacy min-height floor, if any
    panels_floor_px: float | None
    row_gap: int = 4
    # Set only by the historical layout below: the chrome allowance the
    # column formula subtracted, which was a constant and therefore did
    # not track the chrome the page actually rendered.
    grid_chrome_const: float | None = None


def solve(layout: Layout, w: int, h: int, chrome: float) -> dict:
    """Heights the browser would resolve, for one viewport and chrome.

    ``chrome`` is every fixed row plus the gaps — i.e. what is NOT the
    stage and NOT the panels.
    """
    if w >= layout.grid_min_width:
        # Two columns. The panels own column 2 for the full height below
        # the title bar, so only the LEFT column can over-subscribe.
        avail = max(0.0, w - layout.grid_right_min - layout.grid_col_gap)
        allowance = layout.grid_chrome_const if layout.grid_chrome_const is not None else chrome
        wanted = (h - allowance) * 16 / 9
        left = min(max(layout.grid_left_floor, min(wanted, layout.grid_left_vw / 100 * w)), avail)
        stage = left * 9 / 16
        if layout.grid_chrome_const is None:
            # The stage's own max-height, which the stale-constant layout
            # did not have — nothing stopped the left column growing past
            # the window there.
            stage = min(stage, h - chrome)
        return {
            "grid": True,
            "stage": max(0.0, stage),
            "panels": max(0.0, h - 40 - layout.row_gap),
            "left_column": chrome + max(0.0, stage),
        }
    # One stacked column. The stage is width-driven, capped; the panels
    # take what is left unless a floor overrides them.
    cap = h - chrome
    if layout.stage_cap_dvh is not None:
        cap = min(cap, layout.stage_cap_dvh / 100 * h)
    floor = 0.0
    if layout.panels_floor_dvh is not None:
        floor = min(layout.panels_floor_dvh / 100 * h, layout.panels_floor_px or float("inf"))
    stage = min(w * 9 / 16, cap)
    # A floor on the panels is honoured before the stage keeps anything:
    # flex-shrink cannot go below a min-height, and the stage's automatic
    # minimum is 0.
    if floor:
        stage = max(0.0, min(stage, h - chrome - floor))
    panels = max(floor, h - chrome - stage)
    return {"grid": False, "stage": stage, "panels": panels, "left_column": chrome + stage}


def _css() -> str:
    assert _CSS.exists(), f"missing: {_CSS}"
    return _CSS.read_text(encoding="utf-8")


def parse_layout() -> Layout:
    """Read the live-detect layout numbers back out of the stylesheet."""
    css = _css()
    # The live grid is the one whose column template consults the
    # measured chrome; the file holds several others (weather rows, …).
    cols = None
    for hit in re.finditer(r"grid-template-columns:([^;]*);", css):
        if "--mv-live-chrome" in hit.group(1):
            cols = hit
    assert cols, "the desktop grid has no column template"
    decl = cols.group(1)
    left = re.search(r"clamp\(\s*(\d+)px,\s*calc\(\(100dvh - var\(--mv-live-chrome\)\)", decl)
    assert left, "the left column no longer derives its width from the measured chrome"
    vw = re.search(r"(\d+)vw\s*\)", decl)
    right = re.search(r"minmax\(\s*(\d+)px,\s*1fr\s*\)", decl)
    assert vw and right, f"unexpected column template: {decl.strip()}"
    bp = None
    for hit in re.finditer(r"@media \(min-width:\s*(\d+)px\)", css):
        if hit.start() < cols.start():
            bp = int(hit.group(1))
    assert bp, "no breakpoint guards the live grid"
    gap = re.search(r"column-gap:\s*(\d+)px", css[cols.start() : cols.end() + 400])
    stage_rule = re.search(
        r"#lightboxModal\.lb-live-detect \.mv-shell-stage \{(.*?)\}", css, re.DOTALL
    )
    assert stage_rule, "the stacked stage has no cap"
    cap = re.search(r"--mv-stage-cap:\s*([\d.]+)dvh", css)
    assert cap, "--mv-stage-cap is gone"
    panels = re.search(
        r"#lightboxModal\.lb-live-detect \.mv-shell-panels \{(.*?)\}", css, re.DOTALL
    )
    assert panels, "the live panels rule is gone"
    floor = re.search(r"min-height:\s*min\(([\d.]+)dvh,\s*(\d+)px\)", panels.group(1))
    return Layout(
        grid_min_width=bp,
        grid_left_floor=int(left.group(1)),
        grid_left_vw=int(vw.group(1)),
        grid_right_min=int(right.group(1)),
        grid_col_gap=int(gap.group(1)) if gap else 10,
        stage_cap_dvh=float(cap.group(1)),
        panels_floor_dvh=float(floor.group(1)) if floor else None,
        panels_floor_px=float(floor.group(2)) if floor else None,
    )


# The layout as it stood in f6ff0b7 — kept so the two defects stay
# described by something executable rather than by a paragraph.
REVIEWED = Layout(
    grid_min_width=1000,
    grid_left_floor=0,
    grid_left_vw=60,
    grid_right_min=340,
    grid_col_gap=10,
    stage_cap_dvh=None,
    panels_floor_dvh=46.0,
    panels_floor_px=460.0,
    grid_chrome_const=230.0,
)


def test_the_reviewed_layout_starved_the_stage_on_a_phone():
    """375 × 667 with ~300 px of chrome: the floor claims 307 px, the
    chrome is fixed, and the 211 px stage is the only row left to pay."""
    got = solve(REVIEWED, 375, 667, 302)
    assert got["stage"] < 70, f"expected the stage to collapse, got {got['stage']:.0f} px"
    assert got["panels"] >= 306


def test_the_reviewed_layout_left_the_panels_at_zero_below_the_breakpoint():
    """900 × 600 sat under the 1000 px grid, so it kept the stacked column
    AND the floor: 506 px of stage, 302 of chrome, 600 to spend."""
    got = solve(REVIEWED, 900, 600, 302)
    assert got["stage"] < 40, "the 769–999 px band was the worse half of the bug"


def test_the_stale_chrome_constant_pushed_the_playbar_out_of_the_window():
    """Defect 4, at the window shape that exposes it. `(100dvh - 230px)`
    hands the left column a stage sized for 230 px of chrome; the page
    renders about 300. The surplus goes off the bottom, and
    #lightboxInner's `overflow: hidden !important` keeps it there."""
    over = solve(REVIEWED, 1440, 700, 302)
    assert over["left_column"] > 700, "expected the left column to over-subscribe"
    # The measured allowance cannot over-subscribe: it is the same number
    # the browser will lay out with, and the stage's max-height catches
    # whatever rounding is left.
    fixed = solve(parse_layout(), 1440, 700, 302)
    assert fixed["left_column"] <= 700


def test_every_viewport_keeps_both_a_picture_and_a_panel():
    layout = parse_layout()
    failures = []
    for name, w, h in VIEWPORTS:
        for chrome in (CHROME_MIN, CHROME_MAX):
            got = solve(layout, w, h, chrome)
            if got["stage"] < MIN_STAGE_PX:
                failures.append(f"{name} {w}×{h} chrome={chrome}: stage {got['stage']:.0f} px")
            if got["panels"] < MIN_PANELS_PX:
                failures.append(f"{name} {w}×{h} chrome={chrome}: panels {got['panels']:.0f} px")
    assert not failures, "; ".join(failures)


def test_the_left_column_never_over_subscribes_the_window():
    """#lightboxInner is `overflow: hidden !important` here, so a left
    column taller than the window does not scroll — it loses the playbar.
    """
    layout = parse_layout()
    for name, w, h in VIEWPORTS:
        for chrome in (CHROME_MIN, CHROME_MAX):
            got = solve(layout, w, h, chrome)
            assert got["left_column"] <= h + 1, (
                f"{name} {w}×{h} chrome={chrome}: left column wants "
                f"{got['left_column']:.0f} px of {h}"
            )


def test_the_phone_stage_is_untouched_by_the_new_cap():
    """The cap must not cost the platform that already worked a pixel.
    A portrait phone's stage is 0.5625 × w/h of the column — 31.6 % at
    375 × 667, 26.0 % at 390 × 844 — so it has to sit under the cap with
    room to spare, whatever the chrome does."""
    layout = parse_layout()
    for name, w, h in VIEWPORTS[:2]:
        natural = w * 9 / 16
        assert layout.stage_cap_dvh is not None
        assert natural <= layout.stage_cap_dvh / 100 * h, (
            f"{name}: the {layout.stage_cap_dvh}dvh cap clips the natural "
            f"{natural:.0f} px stage"
        )
        for chrome in (CHROME_MIN, CHROME_MAX):
            assert solve(layout, w, h, chrome)["stage"] == natural


def test_the_chrome_allowance_is_measured_and_not_a_constant():
    """No number in the sizing formulas may stand in for the chrome: the
    playbar alone is 44 px per swimlane lane, so any constant is wrong for
    most of the time the view is open."""
    css = _css()
    assert "--mv-live-chrome" in css
    assert "100dvh - 230px" not in css, "the stale constant is back"
    js = _CSS.parents[1] / "js" / "mediaview" / "live-chrome-budget.js"
    assert js.exists(), "nothing measures the chrome"
    src = js.read_text(encoding="utf-8")
    assert "getBoundingClientRect" in src and "ResizeObserver" in src
    assert "--mv-live-chrome" in src
    shell = (_CSS.parents[1] / "js" / "mediaview" / "shell.js").read_text(encoding="utf-8")
    assert "observeLiveChromeBudget(root)" in shell, "the observer is never mounted"


def test_the_panels_row_carries_no_unconditional_floor():
    """A floor on the only flexible row of a fixed-height column is taken
    from the stage, at every width where the rule is live."""
    layout = parse_layout()
    assert layout.panels_floor_dvh is None, (
        "min-height on .mv-shell-panels does not create space — it moves it "
        "off the stage; bound the stage instead"
    )


def test_the_grid_covers_the_band_that_was_stacked_and_broken():
    """900 × 600 has to reach the two-column layout: stacked, its 506 px
    stage cannot share 600 px with 300 px of chrome no matter how the
    remainder is divided."""
    layout = parse_layout()
    assert layout.grid_min_width <= 900
    assert (
        layout.grid_min_width >= layout.grid_left_floor + layout.grid_right_min
    ), "the breakpoint must not start the grid before both columns fit"
    assert solve(layout, 900, 600, 302)["grid"]
    assert not solve(layout, 390, 844, 302)["grid"], "a phone must stay on one column"
