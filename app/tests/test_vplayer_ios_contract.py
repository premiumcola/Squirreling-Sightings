"""The iOS contract for the vplayer stylesheets.

CLAUDE.md calls iOS layout "the single most recurring regression class"
in this project and lists the checks every UI commit runs. This file
turns the mechanical half of that checklist into a test, for the three
36* partials, so the next edit cannot quietly drop one.

Each rule here corresponds to a failure this codebase has actually
shipped:

  · bare `vh` for a full-height layout — on iOS Safari `100vh` is the
    viewport with the address bar COLLAPSED, so the bottom of a
    `100vh` overlay sits below the fold while the bar is visible.
  · a `:hover` rule with no `@media (hover: hover)` guard — on a touch
    device it sticks after the tap and the control reads as active.
  · a touch target under 44 px.
  · a missing safe-area inset — content under the notch or behind the
    home indicator.
  · an input under 16 px — iOS auto-zooms the whole page on focus.
"""

from __future__ import annotations

import re
from pathlib import Path

_CSS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "css"
_SHELL = _CSS / "36a-vplayer-shell.css"
_TIMELINE = _CSS / "36b-vplayer-timeline.css"
_PANELS = _CSS / "36c-vplayer-panels.css"
_ALL = (_SHELL, _TIMELINE, _PANELS)


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _tokens() -> dict:
    """Every --vp-* custom property declared across the three partials."""
    out = {}
    for path in _ALL:
        for name, value in re.findall(r"(--vp-[a-z-]+)\s*:\s*([^;]+);", _read(path)):
            out[name] = value.strip()
    return out


def _expand(value: str) -> str:
    """Resolve var() indirection so a check can look at the real value.

    The stylesheets deliberately go through tokens — `min-height:
    var(--vp-pnl-row-h)` where that token is `var(--vp-tap)` which is
    `44px`. Asserting on the literal would punish exactly the layering
    these files are supposed to have.
    """
    tokens = _tokens()
    for _ in range(4):
        expanded = re.sub(
            r"var\((--vp-[a-z-]+)(?:\s*,[^)]*)?\)",
            lambda m: tokens.get(m.group(1), m.group(0)),
            value,
        )
        if expanded == value:
            break
        value = expanded
    return value


def test_every_partial_exists_and_is_registered_in_the_load_order():
    builder = (Path(__file__).resolve().parents[1] / "app" / "css_builder.py").read_text(
        encoding="utf-8"
    )
    for path in _ALL:
        assert path.exists(), f"missing partial: {path.name}"
        assert f'"{path.name}"' in builder, f"{path.name} is not in LOAD_ORDER"


def test_no_bare_vh_without_a_dvh_partner():
    """A vh line is allowed only as the fallback beside a dvh one."""
    for path in _ALL:
        css = _strip_comments(_read(path))
        for prop in set(re.findall(r"([a-z-]+)\s*:\s*[^;]*\bvh\b", css)):
            assert re.search(
                rf"{prop}\s*:\s*[^;]*\bdvh\b", css
            ), f"{path.name}: '{prop}' is sized in vh with no dvh partner"


def test_no_fixed_positioning_without_a_dvh_height():
    css = _strip_comments(_read(_SHELL))
    if "position: fixed" in css:
        assert "dvh" in css, "a fixed overlay must be sized in dvh"


def test_every_hover_rule_sits_inside_a_hover_media_query():
    for path in _ALL:
        css = _strip_comments(_read(path))
        # Blank out every @media (hover: hover) block, then any :hover
        # left over is an unguarded one.
        guarded = re.sub(
            r"@media\s*\(hover:\s*hover\)\s*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}",
            "",
            css,
            flags=re.DOTALL,
        )
        assert (
            ":hover" not in guarded
        ), f"{path.name}: a :hover rule is not behind @media (hover: hover)"


def test_the_shell_carries_both_safe_area_insets():
    css = _read(_SHELL)
    assert "env(safe-area-inset-top" in css, "no notch inset"
    assert "env(safe-area-inset-bottom" in css, "no home-indicator inset"


def test_the_touch_target_token_is_the_ios_minimum():
    css = _read(_SHELL)
    assert re.search(r"--vp-tap:\s*44px", css), "the touch-target token must be 44px"


def test_every_interactive_control_meets_the_touch_minimum():
    """Either a 44 px box, or a smaller paint with a 44 px ::before."""
    css = _strip_comments(_read(_SHELL))
    for selector in (".vp-menu-item", ".vp-seg"):
        block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert block, f"{selector} has no rule block"
        body = block.group(1)
        assert (
            "min-height: var(--vp-tap)" in body or "min-height: 44px" in body
        ), f"{selector} does not meet the 44 px touch minimum"
    # The top-bar buttons paint at 36 px on purpose and carry the target
    # as a transparent ::before instead.
    before = re.search(r"\.vp-top-btn::before[^{]*\{([^}]*)\}", css)
    assert before, ".vp-top-btn::before hitbox missing"
    assert "var(--vp-tap)" in before.group(1), "the ::before hitbox must be 44 px"


def test_the_revision_picker_is_a_full_touch_target_at_sixteen_pixels():
    """The simulation's profile-revision <select>.

    Its class name contains no bare ``select``, so the generic input
    sweep below cannot see it — and it is the one control in the panels
    file a finger actually drives. Both numbers are pinned here: 44 px
    or iOS gives it a target smaller than a fingertip, 16 px or iOS
    zooms the whole page the moment it takes focus.
    """
    css = _strip_comments(_read(_PANELS))
    block = re.search(r"\.vp-pnl-rev-sel\s*\{([^}]*)\}", css)
    assert block, ".vp-pnl-rev-sel has no rule block"
    body = block.group(1)
    assert "min-height: var(--vp-tap)" in body or "min-height: 44px" in body
    assert re.search(r"font-size:\s*(\d+)px", body), "the picker must state its font-size"
    assert int(re.search(r"font-size:\s*(\d+)px", body).group(1)) >= 16


def test_the_revision_picker_wraps_rather_than_clipping():
    """German revision labels are long — "30.08. 12:00 · Netz-Änderung ·
    person" — and the row also carries its key. At 375 px they cannot
    share a line, so the row wraps and the control has no fixed width."""
    css = _strip_comments(_read(_PANELS))
    row = re.search(r"\.vp-pnl-rev\s*\{([^}]*)\}", css)
    assert row and "flex-wrap: wrap" in row.group(1), "the picker row must wrap"
    sel = re.search(r"\.vp-pnl-rev-sel\s*\{([^}]*)\}", css).group(1)
    assert "min-width: 0" in sel, "a flex child needs min-width:0 to be allowed to shrink"
    # A plain `width:` only — `min-width` is a hyphen away and must not
    # be caught by the guard against a fixed width.
    assert not re.search(r"(?<![-\w])width:\s*\d", sel), "a fixed width would clip the label"


def test_hidden_attribute_beats_the_display_rules():
    """A [hidden] node inside a display-assigning tree stays hidden."""
    css = _strip_comments(_read(_SHELL))
    assert re.search(
        r"\[hidden\]\s*\{\s*display:\s*none\s*!important", css
    ), "[hidden] { display: none !important } override missing"


def test_any_input_is_at_least_sixteen_pixels():
    """Below 16 px iOS zooms the whole page when the field takes focus."""
    for path in _ALL:
        css = _strip_comments(_read(path))
        for block in re.findall(r"(input|textarea|select)[^{]*\{([^}]*)\}", css):
            for size in re.findall(r"font-size:\s*(\d+)px", block[1]):
                assert int(size) >= 16, f"{path.name}: input font-size {size}px < 16px"


def test_wide_content_scrolls_inside_its_own_row():
    """At 375 px the overlay row outgrows the screen, and it must deal
    with that itself rather than widening the page.

    It WRAPS rather than scrolls. Scrolling satisfied the letter of the
    rule and failed its point: the ROI chip sat past the right edge, and
    a control parked off-screen in a row with no scrollbar is a control
    the operator cannot know exists. The screenshot harness measured it
    at 499 px in a 375 px viewport. Wrapping costs one line, and only
    when there is something to put on it."""
    css = _strip_comments(_read(_SHELL))
    block = re.search(r"\.vp-toggles[^{]*\{([^}]*)\}", css)
    assert block, ".vp-toggles has no rule block"
    body = block.group(1)
    assert "flex-wrap: wrap" in body, "the overlay row must wrap rather than widen the page"
    assert "overflow-x" not in body, "a wrapping row must not also hide content behind a scroll"


# ── 36b · the timeline ────────────────────────────────────────────────────


def test_the_scrub_band_meets_the_touch_minimum():
    """A 6 px rail is not a touch target; the band around it is."""
    css = _strip_comments(_read(_TIMELINE))
    block = re.search(r"\.vp-tl-hit\s*\{([^}]*)\}", css)
    assert block, ".vp-tl-hit has no rule block"
    body = block.group(1)
    assert "min-height: 44px" in body, "the drag band must be at least 44 px tall"


def test_the_roll_bands_hatch_with_a_gradient_not_an_image():
    """An image is a second request that fails silently offline, leaving
    the pre/post-roll bands invisible with no error anywhere."""
    css = _strip_comments(_read(_TIMELINE))
    block = re.search(r"\.vp-tl-band\s*\{([^}]*)\}", css)
    assert block, ".vp-tl-band has no rule block"
    body = block.group(1)
    assert "repeating-linear-gradient" in body
    assert "url(" not in body, "no image may be used for the hatch"


def test_no_hatch_anywhere_in_the_timeline_uses_an_image():
    css = _strip_comments(_read(_TIMELINE))
    assert "url(" not in css, "the timeline must not depend on any fetched asset"


def test_lane_rows_let_a_vertical_swipe_through():
    """A finger starting on a lane must still scroll the page; only the
    rail itself claims the gesture."""
    css = _strip_comments(_read(_TIMELINE))
    lane = re.search(r"\.vp-tl-lane\s*\{([^}]*)\}", css)
    assert lane, ".vp-tl-lane has no rule block"
    assert "touch-action: pan-y" in lane.group(1)
    hit = re.search(r"\.vp-tl-hit\s*\{([^}]*)\}", css)
    assert "touch-action: none" in hit.group(1), "the rail owns its own drag"


def test_the_lane_list_cannot_push_the_picture_off_screen():
    """Many objects at 375 px would otherwise grow the strip without
    limit and bury the video under its own timeline."""
    css = _strip_comments(_read(_TIMELINE))
    block = re.search(r"\.vp-tl-lanes\s*\{([^}]*)\}", css)
    assert block, ".vp-tl-lanes has no rule block"
    body = block.group(1)
    assert "overflow-y: auto" in body
    assert "dvh" in body, "the cap must track the visual viewport, not vh"


def test_the_panel_clears_the_home_indicator():
    """The panel is the last thing on the page. Without the inset its
    final row sits under the home bar — so the last object in the list
    is the one you cannot tap."""
    css = _strip_comments(_read(_PANELS))
    block = re.search(r"\.vp-panel\s*\{([^}]*)\}", css)
    assert block, ".vp-panel has no rule block in 36c"
    assert "env(safe-area-inset-bottom" in _expand(block.group(1))


def test_panel_rows_and_fold_headers_are_touch_targets():
    css = _strip_comments(_read(_PANELS))
    for selector in (r"\.vp-pnl-row", r"\.vp-fold-header", r"\.vp-pnl-btn"):
        block = re.search(selector + r"\s*\{([^}]*)\}", css)
        assert block, f"{selector} has no rule block"
        body = _expand(block.group(1))
        assert "44px" in body, f"{selector} is under the 44 px touch minimum"


def test_long_panel_content_scrolls_inside_itself():
    """A long trace must not stretch the page out from under the video."""
    css = _strip_comments(_read(_PANELS))
    block = re.search(r"\.vp-pnl-trace\s*\{([^}]*)\}", css)
    assert block, ".vp-pnl-trace has no rule block"
    body = block.group(1)
    assert "overflow-y: auto" in body
    assert "dvh" in body, "the cap must track the visual viewport, not vh"


def test_the_playhead_is_driven_by_one_custom_property():
    """Fill and head read the same variable, so one write paints both
    and they cannot drift apart mid-drag."""
    css = _strip_comments(_read(_TIMELINE))
    for selector in (r"\.vp-tl-fill", r"\.vp-tl-head"):
        block = re.search(selector + r"\s*\{([^}]*)\}", css)
        assert block, f"{selector} has no rule block"
        assert "--vp-play-pct" in block.group(1)
