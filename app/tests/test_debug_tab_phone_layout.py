"""The Debug tab has to work with one thumb on a 375 px phone.

The operator opens this view on an iPhone while SSH'd into an Unraid
box. Two properties decide whether it beats the root console:

  · the copy button is reachable WITHOUT scrolling — copying is the
    primary action, everything else on the tab is secondary;
  · the video + swimlane can be folded away, because on a 375 px screen
    they eat the room the debug content needs.

Everything below pins a structural property rather than a pixel, in the
same spirit as test_sim_chrome_layout.py: the failures this guards
against are all "someone moved the control back under the fold" or
"someone re-introduced a hover-only affordance".
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static"
_PKG = _ROOT / "js" / "mediaview" / "live-detect-debug"
_INDEX = _PKG / "index.js"
_VERDICT = _PKG / "_verdict.js"
_COPY = _PKG / "_copy-bar.js"
_TABS = _ROOT / "js" / "mediaview" / "live-detect-tabs.js"
_CSS_LD = _ROOT / "css" / "30f-live-detect-skeleton.css"
_CSS_SHELL = _ROOT / "css" / "30g-mediaview-shell.css"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


# ── the copy button stays above the fold ──────────────────────────────


def test_the_head_is_the_first_thing_in_the_panel():
    """Rendered first + sticky = reachable without a scroll."""
    src = _read(_INDEX)
    body = src[src.index("host.innerHTML =") :]
    head = body.index("_renderVerdictBar")
    status = body.index("_renderLiveStatusHeader")
    assert head < status, "the copy/verdict head must render before anything else"


def test_the_head_is_sticky_at_the_top():
    css = _read(_CSS_LD)
    block = css[css.index(".mv-ld-debug-head {") :]
    block = block[: block.index("}")]
    assert "position: sticky" in block
    assert "top: 0" in block


def test_both_actions_clear_the_44px_touch_minimum():
    css = _read(_CSS_LD)
    start = css.index(".mv-ld-debug-copy,\n.mv-ld-debug-compact {")
    block = css[start : css.index("}", start)]
    assert "min-height: 44px" in block, "iOS touch target floor"


def test_hover_states_are_guarded():
    """A hover-only affordance is invisible on a touch screen."""
    css = _read(_CSS_LD)
    for sel in (".mv-ld-debug-copy:hover", ".mv-ld-debug-compact:hover"):
        idx = css.index(sel)
        assert "@media (hover: hover)" in css[max(0, idx - 400) : idx]


def test_the_panel_reserves_the_home_indicator_strip():
    """In compact mode the debug panel runs to the bottom edge."""
    css = _read(_CSS_LD)
    block = css[css.index(".mv-ld-debug {") :]
    block = block[: block.index("}")]
    assert "env(safe-area-inset-bottom" in block


# ── folding the video away ────────────────────────────────────────────


def test_compact_mode_hides_the_stage_and_the_timeline():
    """ "Das Video und der Zwischenbereich mit der Timeline — dass ich das
    einklappen kann." All four shell regions, not just the picture."""
    css = _read(_CSS_SHELL)
    start = css.index("[data-compact='1'] .mv-shell-stage")
    block = css[start : css.index("}", start)]
    for slot in ("stage", "controls", "legendband", "playbar"):
        assert f".mv-shell-{slot}" in block, f"compact mode must fold the {slot}"
    assert "display: none" in block


def test_the_title_and_tabs_survive_compact_mode():
    """They are how the user gets back — folding them would strand them."""
    css = _read(_CSS_SHELL)
    start = css.index("[data-compact='1'] .mv-shell-stage")
    block = css[start : css.index("}", start)]
    assert ".mv-shell-titlebar" not in block
    assert ".mv-shell-tabs" not in block


def test_compact_is_a_toggle_not_a_hijack():
    src = _read(_VERDICT)
    assert 'data-action="toggle-compact"' in src
    assert "aria-pressed" in src, "the toggle must announce its own state"
    assert "Video zeigen" in src, "the label must offer the way back"


def test_the_choice_is_remembered_for_the_session_only():
    """sessionStorage, not localStorage: hiding the video is aggressive
    enough that it should not silently outlive the browser tab."""
    src = _read(_VERDICT)
    assert "sessionStorage" in src
    assert "localStorage" not in src


def test_leaving_the_debug_tab_brings_the_video_back():
    src = _read(_TABS)
    assert "syncCompactForDebugTab" in src
    assert "id === 'debug'" in src


# ── the wall of text stays in the clipboard ───────────────────────────


def test_the_snapshot_body_is_never_rendered():
    """ "den Text les ich ja sowieso nicht alles durch" — the screen gets
    the verdict, the clipboard gets the document."""
    src = _read(_INDEX)
    assert "markdown" not in src, "the snapshot text must not reach the DOM"


def test_the_screen_shows_only_a_handful_of_findings():
    src = _read(_VERDICT)
    assert "_VERDICT_VISIBLE" in src
    assert "im Kopieren-Text" in src, "the overflow must point at the full list"


def test_the_frontend_fills_in_what_the_server_cannot_know():
    """next-tick delay and bbox hold live in the browser scheduler; the
    server emits tokens instead of a misleading "?"."""
    src = _read(_COPY)
    for token in ("<<tick_next_ms>>", "<<hold_ms>>", "<<frontend_state_ua>>"):
        assert token in src, f"{token} must be substituted before the copy"


def test_the_clipboard_write_stays_inside_the_gesture():
    """iOS Safari revokes clipboard access across an await boundary — the
    cache exists purely so writeText runs synchronously on the tap."""
    src = _read(_COPY)
    click = src[src.index("btn.addEventListener('click'") :]
    click = click[: click.index("\n}")]
    code = "\n".join(l for l in click.splitlines() if not l.strip().startswith("//"))
    assert "await" not in code, "an await before writeText loses iOS clipboard permission"
    assert "writeText" in code


def test_screen_and_paste_share_one_diagnosis():
    """Two renderings of the same server-computed findings — a second
    client-side implementation would drift."""
    src = _read(_COPY)
    assert "format=json" in src
    assert "data.findings" in src
