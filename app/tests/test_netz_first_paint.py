"""The Erkennungsprofil panels have to mount as soon as the camera grid does.

The single-`#netz`-section design used to hydrate lazily, on an
IntersectionObserver watching the section scroll into view. That had a
real bug once (see the pre-reshape history of this file): the observer
callback could call a hash router that returned early on a non-`#netz`
URL, so the ordinary case — scrolling the page — painted nothing.

The Erkennungsprofil reshape (one panel per camera, mounted beside its
own Live-Feed tile) removes the whole hydration-gate class of bug rather
than re-fixing it: `initNetPanels()` runs unconditionally at the end of
every `renderDashboard()` call — the same render that builds the
`.cam-net-slot` a panel mounts into — so there is no separate "has this
scrolled into view yet" gate a panel's first paint can fall through.
These tests pin that shape: no hash check, no IntersectionObserver,
gates the mount on nothing but "did the camera grid just render".
"""

from __future__ import annotations

from pathlib import Path

_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js"
_DASHBOARD = (_JS / "dashboard.js").read_text(encoding="utf-8")
_INDEX = (_JS / "netz" / "index.js").read_text(encoding="utf-8")
_PANEL = (_JS / "netz" / "_panel.js").read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    return src[start : src.index("\n}", start)]


def test_dashboard_calls_initnetpanels_on_every_render():
    """The mount call rides the SAME function the camera-tile poll already
    calls every ~3 s — no separate lazy-hydration path to have a hole in.
    (renderDashboard's own template strings carry stray `}` characters
    from inline ternaries, so a naive brace-matched _fn_body would cut
    the body short — bound on the next top-level function instead.)"""
    start = _DASHBOARD.index("export function renderDashboard() {")
    end = _DASHBOARD.index("function _wirePillOpenClose(")
    assert "initNetPanels()" in _DASHBOARD[start:end]


def test_initnetpanels_has_no_hash_gate():
    """THE regression class this file used to guard against: a hydration
    path keyed to `location.hash` silently does nothing for the ordinary
    case (no deep link). initNetPanels must not be one of those paths —
    it has to run for every camera regardless of the URL."""
    src = _INDEX
    body = src[
        src.index("export async function initNetPanels(") : src.index("window.initNetPanels")
    ]
    assert "location.hash" not in body
    assert ".hash" not in body


def test_ensurepanelsmounted_gates_only_on_dom_state_not_visibility():
    """No IntersectionObserver, no viewport check — a panel mounts the
    moment its slot exists and is empty, whether or not the operator has
    scrolled anywhere near it yet."""
    assert "ensurePanelsMounted" in _PANEL
    assert "IntersectionObserver" not in _PANEL
    assert "IntersectionObserver" not in _INDEX


def test_the_open_questions_deep_link_is_a_separate_concern_from_mounting():
    """The bot's `#netz?tab=verlauf&filter=offen` link is real (messages
    already sent carry it) but it is additive — it switches already-
    mounted panels into their Verlauf tab, it does not gate whether they
    mounted in the first place. Confirms the deep-link handler runs AFTER
    the unconditional mount call, not instead of it."""
    body = _fn_body(_INDEX, "initNetPanels")
    assert body.index("ensurePanelsMounted()") < body.index("_openQuestionsDeepLink()")


def test_the_deep_link_handler_still_checks_the_hash():
    """The gate belongs here, not in the mount path: only THIS function
    may bail on a URL that isn't the bot's link — and it still has to
    handle a hashchange fired after boot, not just the initial arrival."""
    body = _fn_body(_INDEX, "_openQuestionsDeepLink")
    assert "startsWith('#netz')" in body and "return;" in body
    assert "addEventListener('hashchange'" in _INDEX
