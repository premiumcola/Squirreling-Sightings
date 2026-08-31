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
    partials/mediathek.html (partials/weather.html merged into it in
    Stage 6) and the opt-outs here in step."""
    html = (
        Path(__file__).resolve().parents[2] / "app" / "web" / "templates" / "partials"
    ) / "mediathek.html"
    css = _ZOOM_CSS.read_text(encoding="utf-8")
    markup = html.read_text(encoding="utf-8")
    # Every element in the weather partial that carries a bare `hidden`
    # attribute AND a class this partial styles with `display`.
    for cls in re.findall(r'class="(ws-zoom-[a-z-]+)"[^>]*\bhidden\b', markup):
        selector = f".{cls}"
        if not _sets_own_display(css, selector):
            continue
        assert f"{selector}[hidden]" in css, f"{selector} needs a [hidden] opt-out"


# ── the same bug, swept across the whole codebase ─────────────────────


def test_no_hidden_toggled_element_has_its_display_forced():
    """The repo-wide version of the bug above.

    Sweeping for it turned up a third instance the original report did
    not mention: `.shape-clear-row` in the zone/mask editor. `shape-
    editor/ui.js` hides that row when there is no polygon to clear, and
    `display: flex` defeated it, so "Alle löschen" sat on an empty
    editor offering to delete nothing.

    The sweep is deliberately narrow — only ids that JS actually
    assigns `.hidden` on, resolved to their classes via the templates —
    because a looser "any class that sets display" scan returns ~500
    rules, almost none of which are ever toggled.
    """
    js_root = Path(__file__).resolve().parents[1] / "web" / "static" / "js"
    tpl_root = Path(__file__).resolve().parents[1] / "web" / "templates"

    # Two shapes, because both occur: the direct
    # `byId('x').hidden = …`, and the far more common
    # `const el = byId('x'); … el.hidden = …` where the two halves sit
    # lines apart. Matching only the direct form is why the first draft
    # of this sweep missed `.shape-clear-row` — the very bug that
    # prompted widening it.
    toggled = set()
    for path in js_root.rglob("*.js"):
        src = path.read_text(encoding="utf-8", errors="ignore")
        toggled.update(re.findall(r"byId\(['\"]([A-Za-z0-9_-]+)['\"]\)\s*\??\.hidden\s*=", src))
        for var, eid in re.findall(
            r"(?:const|let|var)\s+(\w+)\s*=\s*byId\(['\"]([A-Za-z0-9_-]+)['\"]\)", src
        ):
            if re.search(rf"\b{re.escape(var)}\s*\??\.hidden\s*=", src):
                toggled.add(eid)

    id_classes: dict[str, set[str]] = {}
    for path in tpl_root.rglob("*.html"):
        for tag in re.finditer(
            r'<[^>]*\bid="([A-Za-z0-9_-]+)"[^>]*>',
            path.read_text(encoding="utf-8", errors="ignore"),
        ):
            cls = re.search(r'\bclass="([^"]+)"', tag.group(0))
            if cls:
                id_classes.setdefault(tag.group(1), set()).update(cls.group(1).split())

    forces_display: dict[str, str] = {}
    guarded: set[str] = set()
    for path in _CSS.glob("*.css"):
        src = path.read_text(encoding="utf-8")
        for rule in re.finditer(r"^\.([a-z0-9_-]+)\s*\{([^}]*)\}", src, re.M):
            if re.search(r"\bdisplay\s*:", rule.group(2)):
                forces_display.setdefault(rule.group(1), path.name)
        guarded.update(re.findall(r"\.([a-z0-9_-]+)\[hidden\]", src))

    broken = [
        f"#{eid} (.{cls} in {forces_display[cls]})"
        for eid in sorted(toggled)
        for cls in sorted(id_classes.get(eid, ()))
        if cls in forces_display and cls not in guarded
    ]
    assert not broken, (
        "these elements are toggled via the `hidden` attribute but their class "
        "forces `display`, so hiding them does nothing: " + ", ".join(broken)
    )
