"""Regression guards for the 2026-08-31 species-dossier redesign
(sichtungen/_dossier-panel.js + sichtungen/_achievements.js).

Why source-grep instead of a real `node --test` DOM test: `_dossier-
panel.js` statically imports `bindLibraryGrid` from `library/_bind.js`,
whose own module graph reaches `lightbox.js` → `core/ios-video.js`
(`document.addEventListener('visibilitychange', ...)` at MODULE-LOAD
time) and `mediathek/bbox-overlay/index.js` (`window.addEventListener
('resize', ...)`, also at load time). `library/_tests/bind.test.js`
already documents hitting exactly this wall for the same module
("a much heavier DOM stub than library/_tests/_setup.js provides —
confirmed by trying it first") and deliberately tests only an
extractable pure leaf instead. `_dossier-panel.js` has no such
extractable leaf — its interesting logic lives in the same file as the
heavy import — so a real import-and-exercise test was tried here too
and hits the identical wall one level further down the chain
(`ios-video.js`, not even `_bind.js` itself). This file follows
test_lightbox_weather_render.py's own documented fallback for exactly
this situation: source-level regression pins via `_slice_function`.

Covers:
  * no modal/backdrop/X-close chrome anywhere in the redesigned panel
    (the operator's core complaint: "hässliche Box mit X").
  * a locked (sighting_count 0) species renders a locked hint, never a
    tier badge or a fabricated "× gesehen" count.
  * the hero photo's overlap is the safe "negative margin cancels the
    card's own padding" technique — net column width is unchanged, so
    it can never cause horizontal scroll at any viewport (an actual
    CSS invariant, pinned numerically, not just "some negative margin
    exists somewhere").
  * the bronze/silver/gold legend renders in exactly ONE place (the
    grid header slot) — not duplicated between the template and the
    JS, and not left over in its old below-grid spot.
  * a bird achievement tile is clickable even while locked (the
    Rotkehlchen ask); a locked mammal tile is not (no dossier data
    exists for mammals).
"""

from __future__ import annotations

import re
from pathlib import Path

_JS_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js"
_CSS_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "css"
_TEMPLATES_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "templates"

_DOSSIER_PANEL_JS = _JS_ROOT / "sichtungen" / "_dossier-panel.js"
_ACHIEVEMENTS_JS = _JS_ROOT / "sichtungen" / "_achievements.js"
_SICHTUNGEN_HTML = _TEMPLATES_ROOT / "partials" / "sichtungen.html"
_BIRDS_CSS = _CSS_ROOT / "29-birds.css"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing at {path}"
    return path.read_text(encoding="utf-8")


def _slice_function(path: Path, name: str) -> str:
    """Extract the body of a top-level ``[export] [async] function NAME(...)``.
    Returns the source between the opening ``{`` and its matching ``}``.
    Not a full JS parser — adequate as a regression guard because these
    files carry no unbalanced braces inside string literals. (Copied
    from test_lightbox_weather_render.py — small enough that a shared
    helper module isn't worth the indirection for two test files.)"""
    src = _read(path)
    pattern = re.compile(
        rf"(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{"
    )
    m = pattern.search(src)
    if not m:
        raise AssertionError(f"function {name!r} not found in {path.name}")
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"unbalanced braces inside {name!r} in {path.name}")


# ── no modal / X chrome ──────────────────────────────────────────────────


def test_dossier_panel_has_no_modal_backdrop():
    src = _read(_DOSSIER_PANEL_JS)
    for banned in ("bird-modal", "modal-backdrop", "position: fixed", "position:fixed"):
        assert banned not in src, (
            f"{banned!r} found in _dossier-panel.js — the redesigned panel must be inline "
            "content, never a popup/modal (the operator's 'hässliche Box mit X' complaint)."
        )


def test_dossier_panel_has_no_close_button():
    src = _read(_DOSSIER_PANEL_JS)
    assert "Schließen" not in src, (
        "_dossier-panel.js must not render a close/dismiss control — selecting another "
        "species is a plain re-point, not an open/close toggle."
    )
    assert "✕" not in src and "×</button" not in src


# ── locked species shows a hint, never a fabricated tier/count ──────────


def test_locked_species_gets_a_hint_not_a_tier_badge():
    body = _slice_function(_DOSSIER_PANEL_JS, "_tierBadgeOrLockedHint")
    assert "sd-locked-hint" in body
    assert "'locked'" in body or '"locked"' in body


def test_meta_html_only_shows_the_sighting_count_when_positive():
    body = _slice_function(_DOSSIER_PANEL_JS, "_metaHtml")
    # The count line must be gated on count > 0 — a pre-built,
    # never-detected species (sighting_count 0) must never show
    # "0× gesehen" or any other invented sighting count.
    assert re.search(r"count\s*>\s*0", body), (
        "_metaHtml must gate the '× gesehen' count on count > 0 — a "
        "sighting_count of 0 (pre-built, never detected) must not render "
        "a fabricated count line."
    )


def test_select_by_name_no_ops_on_an_unknown_species():
    body = _slice_function(_DOSSIER_PANEL_JS, "selectSpeciesDossierByName")
    assert "return" in body, (
        "selectSpeciesDossierByName must return early when the name has no "
        "matching dossier yet, instead of throwing or blanking the panel."
    )


# ── legend renders exactly once ──────────────────────────────────────────


def _strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


def test_legend_removed_from_the_template():
    html = _strip_html_comments(_read(_SICHTUNGEN_HTML))
    assert "Top-20 Bayern" not in html, (
        "the old plain-text 'Top-20 Bayern · Bronze / Silber / Gold' subtitle must be gone "
        "from sichtungen.html's rendered markup, not merely hidden — it duplicated the "
        "icon-based legend."
    )
    assert 'id="achievementsLegendSlot"' in html, (
        "sichtungen.html must carry the header slot the icon-based legend renders into."
    )
    # Only ONE legend-shaped div in the header markup — the old below-grid
    # legend div must not have been left behind alongside the new slot.
    assert html.count('class="ach-legend"') == 1


def test_legend_renders_exactly_once_across_the_sichtungen_package():
    """The legend's distinctive range label ("Bronze 1–4×", unique to
    _renderLegend's markup — the bare word "Bronze" alone also appears
    legitimately as a tier-badge label in _dossier-panel.js, which is
    NOT a duplicate legend) must appear in exactly one render function
    across the whole package — not once in the header AND again
    somewhere below the grid (the original duplication complaint)."""
    hits = []
    for js_file in sorted((_JS_ROOT / "sichtungen").glob("*.js")):
        src = _read(js_file)
        if "Bronze 1" in src:
            hits.append(js_file.name)
    assert hits == ["_achievements.js"], (
        f"the 'Bronze 1–4×' legend label found in {hits} — expected only "
        "_achievements.js's _renderLegend. A second occurrence means the legend is "
        "duplicated again."
    )


def test_legend_targets_the_header_slot_not_the_grid():
    body = _slice_function(_ACHIEVEMENTS_JS, "_renderLegend")
    assert "achievementsLegendSlot" in body
    grid_render = _slice_function(_ACHIEVEMENTS_JS, "renderAchievements")
    assert "Bronze" not in grid_render, (
        "renderAchievements must not build the legend inline into the grid HTML any more — "
        "that was the below-grid duplicate; _renderLegend owns it now."
    )


# ── tile click routing (the Rotkehlchen ask) ─────────────────────────────


def test_locked_bird_tiles_are_clickable():
    body = _slice_function(_ACHIEVEMENTS_JS, "_tileClickAttrs")
    # The bird branch must not be gated behind `isUnlocked` — a locked
    # bird tile (never detected) still opens the dossier panel.
    bird_branch = body.split("if (a.cat === 'birds')")[1].split("if (isUnlocked)")[0]
    assert "isUnlocked" not in bird_branch, (
        "the bird-tile click branch must not check isUnlocked — a locked, never-detected "
        "species must still open its (pre-built) dossier panel."
    )
    assert "selectSpeciesDossierByName" in bird_branch


def test_locked_mammal_tiles_stay_non_clickable():
    body = _slice_function(_ACHIEVEMENTS_JS, "_tileClickAttrs")
    mammal_branch = body.split("if (isUnlocked)")[1]
    assert "toggleAchDrilldown" in mammal_branch


# ── hero overlap is the safe padding-cancelling technique ───────────────


def _numeric_margins(css: str, selector: str) -> list[int]:
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, f"{selector} not found in 29-birds.css"
    margin_line = re.search(r"margin:\s*([^;]+);", block.group(1))
    assert margin_line, f"{selector} has no shorthand margin rule"
    return [int(n) for n in re.findall(r"-?\d+", margin_line.group(1))]


def _numeric_padding(css: str, selector: str) -> list[int]:
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, f"{selector} not found in 29-birds.css"
    padding_line = re.search(r"padding:\s*([^;]+);", block.group(1))
    assert padding_line, f"{selector} has no shorthand padding rule"
    return [int(n) for n in re.findall(r"-?\d+", padding_line.group(1))]


def test_hero_bleed_exactly_cancels_the_cards_own_padding():
    css = _read(_BIRDS_CSS)
    card_padding = _numeric_padding(css, ".sd-card")  # top, [right,] bottom, left (shorthand)
    hero_margin = _numeric_margins(css, ".sd-hero")  # top, [right,] bottom
    # .sd-card { padding: 30px 22px 22px; } → top=30, side=22
    # .sd-hero { margin: -30px -22px 18px; } → top=-30, side=-22
    top_pad, side_pad, _bottom_pad = card_padding
    top_margin, side_margin, _bottom_margin = hero_margin
    assert top_margin == -top_pad, (
        "the hero's top bleed must exactly cancel .sd-card's own top padding — a mismatch "
        "either leaves a gap (not a real bleed) or overshoots outside the card's own box."
    )
    assert side_margin == -side_pad, (
        "the hero's side bleed must exactly cancel .sd-card's own side padding — this is "
        "what keeps the overlap contained within the grid column (zero horizontal-scroll "
        "risk) instead of bleeding past the whole page."
    )


def test_hero_bleed_still_cancels_padding_on_the_mobile_card():
    css = _read(_BIRDS_CSS)
    mobile_block = re.search(r"@media \(max-width: 480px\)\s*\{(.*)\}\s*$", css, re.DOTALL)
    assert mobile_block, "expected a <=480px media query at the end of 29-birds.css"
    block_src = mobile_block.group(1)
    card_padding = _numeric_padding(block_src, ".sd-card")
    hero_margin = _numeric_margins(block_src, ".sd-hero")
    top_pad, side_pad = card_padding[0], card_padding[1]
    top_margin, side_margin = hero_margin[0], hero_margin[1]
    assert top_margin == -top_pad
    assert side_margin == -side_pad
