"""The drag-zoom panels actually disappear when JS sets `hidden`.

The operator's report: after saving a manual weather event the edit
panel "bleibt einfach komplett offen". The JS was innocent —
weather/_manual-event-save.js does reach `panel.hidden = true`, and so
do the Abbrechen button, the second click on "Als Ereignis speichern",
and weather/stats.js::_closeZoomSavePanel on a fresh drag or a zoom
reset. What defeated all four is the cascade: the UA stylesheet's
`[hidden] { display: none }` loses to ANY author rule that sets
`display`, regardless of specificity, because author origin outranks
user-agent origin. `.ws-zoom-save { display: grid }` and
`.ws-zoom-actions { display: flex }` are exactly such rules, so the
attribute flipped and nothing moved.

Both panels therefore need an explicit `[hidden]` opt-out — the pattern
this codebase already uses in a dozen partials (`.mv-shell-grid[hidden]`,
`.set-tab-content[hidden]`, `.alert-conflict[hidden]`, …). A file-level
test rather than a node one: the defect lives in CSS, and no DOM stub
would have caught it.
"""

from __future__ import annotations

import re
from pathlib import Path

_CSS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "css"
_ZOOM_CSS = _CSS / "23b-weather-zoom.css"


def _rule(css: str, selector: str) -> str:
    m = re.search(rf"^{re.escape(selector)} \{{(.*?)\}}", css, re.DOTALL | re.MULTILINE)
    assert m, f"no rule for {selector}"
    return m.group(1)


def _sets_own_display(css: str, selector: str) -> bool:
    return "display:" in _rule(css, selector).replace(" ", "")


def test_the_save_panel_has_an_explicit_hidden_opt_out():
    css = _ZOOM_CSS.read_text(encoding="utf-8")
    assert _sets_own_display(css, ".ws-zoom-save"), "precondition: the panel sets its own display"
    assert "none" in _rule(css, ".ws-zoom-save[hidden]").replace(" ", "")


def test_the_zoom_action_row_has_an_explicit_hidden_opt_out():
    """Same trap, same file: weather/stats.js toggles
    `#weatherZoomActions`.hidden off every render without an active
    zoom, and `display: flex` kept the row (and its dead "Als Ereignis
    speichern" button) on screen anyway."""
    css = _ZOOM_CSS.read_text(encoding="utf-8")
    assert _sets_own_display(css, ".ws-zoom-actions"), "precondition: the row sets its own display"
    assert "none" in _rule(css, ".ws-zoom-actions[hidden]").replace(" ", "")


def test_the_new_card_flash_respects_prefers_reduced_motion():
    """The saved event announces where it landed instead of a success
    toast — but a motion-sensitive operator must be able to opt out, and
    the highlight must stay an animation (transient) rather than a
    permanent background override."""
    css = _ZOOM_CSS.read_text(encoding="utf-8")
    rule = _rule(css, ".ws-manual-card--new")
    assert "animation:" in rule.replace(" ", "")[:20] or "animation" in rule
    assert "background" not in rule, "the highlight must fade, not repaint the card for good"
    reduced = re.search(
        r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}",
        css,
        re.DOTALL,
    )
    assert reduced, "no prefers-reduced-motion block"
    assert ".ws-manual-card--new" in reduced.group(1)
    assert "animation: none" in reduced.group(1)


def test_no_other_rule_in_this_partial_sets_display_without_a_hidden_opt_out():
    """A guard for the next panel added here. Any selector this file
    gives a `display` to, whose element the templates mark `hidden`,
    needs the same opt-out — so keep the list of `hidden` ids in
    partials/weather.html and the opt-outs here in step."""
    html = (
        Path(__file__).resolve().parents[2] / "app" / "web" / "templates" / "partials"
    ) / "weather.html"
    css = _ZOOM_CSS.read_text(encoding="utf-8")
    markup = html.read_text(encoding="utf-8")
    # Every element in the weather partial that carries a bare `hidden`
    # attribute AND a class this partial styles with `display`.
    for cls in re.findall(r'class="(ws-zoom-[a-z-]+)"[^>]*\bhidden\b', markup):
        selector = f".{cls}"
        if not _sets_own_display(css, selector):
            continue
        assert f"{selector}[hidden]" in css, f"{selector} needs a [hidden] opt-out"
