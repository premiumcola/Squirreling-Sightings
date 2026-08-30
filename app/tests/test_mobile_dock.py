"""Regression guards for the mobile bottom dock (Live / Statistik / …).

This component has the longest bugfix tail in the repo — eleven commits
between 24bf294 and 7c880de, all fighting the same three symptoms on a
real iPhone: the bar creeps upward, the shadow behind it drifts out of
register, and page content shows through the strips the plate does not
cover. CLAUDE.md names it explicitly ("If a component has been patched
more than twice for the same iOS symptom … rewrite from scratch").

There is no jsdom or headless-browser harness here — package.json carries
eslint + prettier only, and every frontend test in this suite is a
structural source assertion (see test_storms_archive.py, which says so in
its own docstring). These follow that pattern.

The two defects these tests would have caught, both of which shipped:

  · `.m-dock` grew a SECOND `box-shadow` declaration in the same rule
    (296f2b6). A later declaration silently wins, so the "single diffuse
    drop shadow" 3fbd046 wrote — with a comment explaining that the
    upward sharp layer "painted as a hard line on iPhone" — never
    reached a single device. The dead copy was then edited twice more by
    people who believed it was live.

  · The bottom gap moved from `env(…) + 2px` to `env(…) + 6px` and later
    gained a `max(8px, …)` floor, but the fog scrim and the body scroll
    clearance kept a hardcoded `env(…) + 2px + 70px`. Three consumers,
    one of them in another stylesheet, each restating a formula the dock
    had already moved away from.

So the invariants pinned below are: one shadow, zero literals, and every
number that has to line up with the plate derived from the same tokens.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CSS = _REPO / "app" / "web" / "static" / "css"
_TPL = _REPO / "app" / "web" / "templates"

_DOCK = _CSS / "05-chrome-dock.css"
_MOBILE = _CSS / "25-mobile.css"

_PHONE = "@media (max-width: 768px)"


def _read(path: Path) -> str:
    """Source with /* … */ comments stripped.

    This file's rules are heavily commented — deliberately, the reasoning
    is the expensive part — and the prose names the very properties the
    assertions look for ("no inset highlight either", "body::after").
    Every assertion here is about declarations, so strip the prose once
    at the door instead of teaching each test to ignore it.
    """
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def _rule(css: str, selector: str, occurrence: int = 1) -> str:
    """Declaration block of the n-th `selector {` in css, braces matched.

    Brace matching rather than a lazy `.*?}` because the dock rules live
    inside a media query and one of them nests another.
    """
    pattern = re.compile(re.escape(selector) + r"\s*\{")
    found = 0
    for match in pattern.finditer(css):
        found += 1
        if found < occurrence:
            continue
        depth = 0
        for i in range(match.end() - 1, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    return css[match.end() : i]
        raise AssertionError(f"unbalanced braces after {selector}")
    raise AssertionError(f"{selector} (occurrence {occurrence}) is missing")


def _tokens() -> dict[str, str]:
    """The dock's :root custom properties, from inside the phone query."""
    css = _read(_DOCK)
    root = _rule(css[css.index(_PHONE, css.index(".m-dock")) :], ":root")
    found = {name: value.strip() for name, value in re.findall(r"(--m-dock-[\w-]+):([^;]+);", root)}
    missing = {
        "--m-dock-margin",
        "--m-dock-inner-pad",
        "--m-dock-btn-h",
        "--m-dock-h",
        "--m-dock-bottom-gap",
        "--m-dock-screen-radius",
        "--m-dock-radius",
        "--m-dock-pill-radius",
        "--m-dock-fog-fade",
    } - set(found)
    assert not missing, (
        f"dock geometry declared outside the :root block: {sorted(missing)}. "
        "Every number the scrim, the scroll clearance and the compare bar "
        "have to agree on lives there, once."
    )
    return found


def _px(value: str) -> int:
    match = re.search(r"(\d+)px", value)
    assert match, f"no px value in {value!r}"
    return int(match.group(1))


# ── complaint 1 · "die ist wieder hochgerutscht" ──────────────────────


def test_the_bottom_gap_clears_the_home_indicator_via_safe_area():
    """`safe-area-inset-*` is on CLAUDE.md's every-UI-change checklist and
    it is where this component regresses. The page ships
    viewport-fit=cover, so the inset is a real number on a notched
    iPhone; without it the plate would sit on the home indicator."""
    gap = _tokens()["--m-dock-bottom-gap"]
    assert "env(safe-area-inset-bottom" in gap
    assert "0px" in gap, "env() needs a fallback for devices without an inset"
    assert 'content="width=device-width,initial-scale=1,viewport-fit=cover"' in _read(
        _TPL / "index.html"
    ), "without viewport-fit=cover every safe-area inset resolves to 0"


def test_the_dock_sits_low_without_going_flush_against_the_indicator():
    """The operator's calibration, twice over: +8 px felt like the bar was
    floating mid-screen (a5f7fc8), 0 px read as a chrome partition glued
    to the screen edge (296f2b6, reverted). The additive over the inset
    is what crept back to +6 px and drew the "wieder hochgerutscht"
    report — pin it at or below the side margin."""
    tokens = _tokens()
    margin = _px(tokens["--m-dock-margin"])
    additive = re.search(
        r"env\(safe-area-inset-bottom[^)]*\)\s*\+\s*(\d+)px",
        tokens["--m-dock-bottom-gap"],
    )
    assert additive, "the bottom gap no longer adds a design margin to the inset"
    assert 0 < int(additive.group(1)) <= margin, (
        "0 px is the rejected flush-bottom layout; anything above the side "
        "margin lifts the bar off the bottom edge again"
    )


def test_the_bottom_gap_keeps_a_floor_for_devices_without_an_inset():
    """Android, older iPads and narrow desktop report no inset at all. The
    floor keeps the bottom gap from collapsing below the side margin,
    which would break the concentric geometry below."""
    tokens = _tokens()
    gap = tokens["--m-dock-bottom-gap"]
    assert gap.startswith("max("), "no floor — inset-less devices lose the gap"
    assert _px(gap) == _px(tokens["--m-dock-margin"])


def test_the_dock_is_anchored_to_bottom_and_never_sized_in_vh():
    """`dvh` not `vh`, and no fixed element sized in viewport units —
    both from the iOS checklist. A bottom-anchored fixed element rides
    the address-bar collapse instead of jumping."""
    body = _rule(_read(_DOCK), ".m-dock", occurrence=2)
    assert "position: fixed" in body
    assert "bottom: var(--m-dock-bottom-gap)" in body
    assert not re.search(
        r"\d\s*vh\b", _read(_DOCK)
    ), "vh ignores the iOS address bar; use dvh or anchor to bottom"


# ── complaint 2 · "der Schatten … hängt son bisschen drüber" ──────────


def test_the_dock_declares_exactly_one_box_shadow():
    """THE bug. Two `box-shadow` declarations in one rule: the second
    wins in silence, so the first is dead code that still reads as
    intent. 3fbd046 replaced the upward double-shadow with a single
    diffuse one and shipped nothing, because a5f7fc8's four-layer stack
    further down the same rule kept winning."""
    body = _rule(_read(_DOCK), ".m-dock", occurrence=2)
    assert (
        body.count("box-shadow:") == 1
    ), "a second box-shadow in the same rule silently overrides the first"


def test_the_dock_shadow_never_hangs_above_the_plate():
    """A negative y-offset paints a halo ABOVE the bar — the operator's
    "der hängt son bisschen drüber". Depth above the dock is the scrim's
    job; the plate's own shadow only anchors it downward."""
    body = _rule(_read(_DOCK), ".m-dock", occurrence=2)
    shadows = re.findall(r"box-shadow:([^;]+);", body)
    assert shadows, "the plate lost its shadow entirely"
    for shadow in shadows:
        assert not re.search(r"\s-\d+px", shadow), (
            "upward shadow layer on the plate; that halo reads as a smear "
            "floating over the bar, not as depth behind it"
        )


def test_the_dock_carries_no_thin_border_and_no_inset_hairline():
    """Design principles: no thin border lines, depth via colour
    contrast. A 1 px inset white top highlight is a border by another
    name — the old rule shipped one and apologised for it in a comment."""
    css = _read(_DOCK)
    body = _rule(css, ".m-dock", occurrence=2)
    assert "inset" not in body, "inset hairline highlight on the plate"
    offenders = [
        line.strip()
        for line in css.splitlines()
        if (m := re.match(r"\s*border(?:-(?:top|right|bottom|left))?:\s*([^;]+);", line))
        and m.group(1).strip() not in ("0", "none", "0px")
    ]
    assert not offenders, f"thin borders introduced: {offenders}"


# ── complaint 3 · "die Seite darunter oder außenrum durchlaufen" ──────


def test_the_scrim_covers_the_strips_the_plate_does_not():
    """The plate is inset by --m-dock-margin left and right and floats
    --m-dock-bottom-gap above the screen edge. Those three strips are
    where page content was visibly running around the dock. The scrim
    therefore starts at the viewport bottom, full width — the previous
    version started at the plate's TOP edge and left all three raw."""
    body = _rule(_read(_DOCK), "body::after")
    assert "position: fixed" in body
    assert "bottom: 0" in body, (
        "a scrim anchored above the plate cannot cover the under-dock " "strip or the side margins"
    )
    assert "left: 0" in body and "right: 0" in body
    assert "pointer-events: none" in body, "the scrim must not eat taps"


def test_the_scrim_is_registered_to_the_dock_by_derivation():
    """It went 4 px out of register because it restated `env(…) + 2px +
    70px` while the plate had moved on. No literals: both edges of the
    band come from the same two tokens the plate uses."""
    body = _rule(_read(_DOCK), "body::after")
    assert "var(--m-dock-bottom-gap)" in body and "var(--m-dock-h)" in body
    assert "env(safe-area-inset-bottom" not in body, (
        "the scrim must read the inset through --m-dock-bottom-gap, not " "re-derive it and drift"
    )
    assert "70px" not in body, "the dock height is a token, not a literal"


def test_the_scrim_stays_translucent_enough_for_the_plate_to_blur():
    """An opaque scrim would leave the plate's backdrop-filter nothing to
    sample and the frosted look would die. Below the plate it must still
    fog the page, above it must fade fully out."""
    body = _rule(_read(_DOCK), "body::after")
    alphas = [float(a) for a in re.findall(r"rgba\(17, 17, 17, ([\d.]+)\)", body)]
    assert alphas, "the scrim no longer paints the page background colour"
    assert 0.5 <= max(alphas) < 1.0, "opaque scrim kills the plate's blur"
    assert min(alphas) == 0.0, "the scrim must fade out, not end on an edge"


def test_the_scrim_sits_under_the_plate_but_over_the_page():
    dock = _rule(_read(_DOCK), ".m-dock", occurrence=2)
    scrim = _rule(_read(_DOCK), "body::after")
    assert _px(re.search(r"z-index: (\d+)", scrim).group(0) + "px") < _px(
        re.search(r"z-index: (\d+)", dock).group(0) + "px"
    ), "the scrim would paint over the dock plate"


def test_the_compare_bar_is_not_fogged_by_the_scrim():
    """The Gewitter-Archiv action bar is the one interactive control
    inside the scrim's band. It has to out-stack the scrim or it reads
    as disabled."""
    scrim = _rule(_read(_DOCK), "body::after")
    selbar = _rule(_read(_MOBILE), ".st-selbar")
    scrim_z = int(re.search(r"z-index: (\d+)", scrim).group(1))
    selbar_z = int(re.search(r"z-index: (\d+)", selbar).group(1))
    assert selbar_z > scrim_z


# ── radii · "anlehnen an die Radien vom Display" ──────────────────────


def test_the_plate_radius_is_concentric_with_the_device_screen():
    """Not merely round — nested inside the phone's own display curve.
    Screen radius minus the side margin is what makes the two curves
    share a centre; a bare literal drifts the moment the margin moves."""
    tokens = _tokens()
    radius = tokens["--m-dock-radius"]
    assert "var(--m-dock-screen-radius)" in radius and "var(--m-dock-margin)" in radius
    assert _px(tokens["--m-dock-screen-radius"]) > _px(tokens["--m-dock-margin"])


def test_the_active_pill_nests_inside_the_plate_curve():
    pill = _tokens()["--m-dock-pill-radius"]
    assert "var(--m-dock-radius)" in pill and "var(--m-dock-inner-pad)" in pill


def test_every_dock_radius_clears_the_eight_px_design_floor():
    """Design principles: rounded corners everywhere, >= 8 px."""
    css = _read(_DOCK)
    for value in re.findall(r"border-radius:\s*([^;]+);", css):
        if "var(" in value or "%" in value:
            continue
        assert _px(value) >= 8, f"border-radius below the 8 px floor: {value}"


# ── one source of truth ───────────────────────────────────────────────


def test_the_plate_height_is_derived_from_padding_and_button_height():
    """`70px` was restated in four places. Derive it, and a future resize
    propagates instead of silently desynchronising the scrim."""
    tokens = _tokens()
    height = tokens["--m-dock-h"]
    assert "var(--m-dock-inner-pad)" in height and "var(--m-dock-btn-h)" in height


def test_no_consumer_of_the_dock_band_restates_a_literal():
    """Every element that has to line up with the plate — the scrim, the
    page scroll clearance, the compare action bar in another stylesheet
    — reads the tokens. This is the assertion that fails first when
    someone tunes the dock and forgets a consumer."""
    css = _read(_DOCK)
    clearance = _rule(css[css.index("body::after") :], "body")
    for body in (clearance, _rule(_read(_MOBILE), ".st-selbar")):
        assert "var(--m-dock-bottom-gap" in body and "var(--m-dock-h" in body
    assert "env(safe-area-inset-bottom" not in clearance
    assert "70px" not in clearance


def test_the_scroll_clearance_actually_clears_the_plate():
    """Short clearance is how the last row of a section ends up sitting
    under the bar. Gap + height is the plate's full footprint; anything
    on top of that is breathing room."""
    css = _read(_DOCK)
    clearance = _rule(css[css.index("body::after") :], "body")
    padding = re.search(r"padding-bottom:\s*calc\(([^;]+)\)", clearance)
    assert padding
    assert "+ 8px" in padding.group(1), "no breathing room above the plate"
    assert "!important" in clearance, (
        "page-level bottom padding is set by many panels; the dock's " "clearance has to win"
    )


# ── iOS checklist + desktop containment ───────────────────────────────


def test_touch_targets_clear_forty_four_px():
    tokens = _tokens()
    assert _px(tokens["--m-dock-btn-h"]) >= 44
    assert "min-height: var(--m-dock-btn-h)" in _rule(_read(_DOCK), ".m-dock-btn")


def test_no_unguarded_hover_state_on_the_dock():
    """iOS latches :hover after a tap, leaving a tab looking selected."""
    css = _read(_DOCK)
    for match in re.finditer(r"\.m-dock[\w-]*:hover", css):
        before = css[: match.start()]
        assert before.rfind("@media (hover: hover)") > before.rfind(
            "\n}\n"
        ), f"{match.group(0)} is not inside a (hover: hover) query"


def test_the_dock_is_hidden_outside_the_phone_breakpoint():
    """Desktop keeps the sidebar; the sidebar-slot work in 01-base.css
    must stay the only navigation change there."""
    css = _read(_DOCK)
    assert "display: none" in _rule(css, ".m-dock", occurrence=1)
    assert css.index(_PHONE) > css.index(
        ".m-dock {"
    ), "the display:none default has to precede the phone breakpoint"


def test_dock_geometry_never_leaks_onto_desktop():
    """Every geometry token and both scrims live inside the phone query,
    so a wide viewport sees none of them."""
    css = _read(_DOCK)
    phone_blocks = []
    for match in re.finditer(re.escape(_PHONE) + r"\s*\{", css):
        depth = 0
        for i in range(match.end() - 1, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    phone_blocks.append(css[match.end() : i])
                    break
    guarded = "".join(phone_blocks)
    for needle in ("--m-dock-bottom-gap:", "--m-dock-radius:", "body::after", "body::before"):
        assert needle in guarded, f"{needle} escaped the phone breakpoint"
        assert css.count(needle) == guarded.count(needle)


def test_the_desktop_sidebar_slot_is_collapsed_on_phones():
    """01-base.css reserves 260 px of flex width for the sidebar. The
    phone shell is display:block with the sidebar lifted out of flow, so
    that reservation is a leftover box inside the breakpoint."""
    css = _read(_CSS / "04-coral-1.css")
    assert ".sidebar-slot" in css, (
        "the phone breakpoint that lifts .sidebar out of flow never "
        "collapses the flex slot 01-base.css reserved for it"
    )
    phone = css[css.index(_PHONE, max(css.index(".sidebar-slot") - 4000, 0)) :]
    assert "width: 0" in _rule(phone, ".sidebar-slot")
