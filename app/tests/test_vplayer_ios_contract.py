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
    """At 375 px the segmented control outgrows the screen."""
    css = _strip_comments(_read(_SHELL))
    block = re.search(r"\.vp-toggles[^{]*\{([^}]*)\}", css)
    assert block, ".vp-toggles has no rule block"
    assert "overflow-x: auto" in block.group(
        1
    ), "the overlay row must scroll itself rather than widen the page"
