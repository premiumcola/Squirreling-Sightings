"""Regression — the label-correction bubbles (tap an already-active
bubble to untoggle it, the "this is a Falscherkennung" gesture) were
reachable ONLY from the legacy photo lightbox
(``recorded-mode.js::_openRecordedPhoto``), never from
``_openRecordedVideoShell`` — the modern MediaView shell every
recorded VIDEO clip opens through (the overwhelming majority of what
this app records). A cat mislabelled off a door-handle-on-a-birdhouse
clip had no way to be corrected from the web player at all; the
operator's only path was a (possibly long-gone) Telegram alert
message.

Root cause, in two parts:
  1. ``_renderLbLabels`` (the bubble renderer + its POST /labels
     round-trip) was only ever CALLED from the photo branch.
  2. CSS force-hid ``#lightboxLabels`` outright in ``.lb-recorded``
     mode, and ``_openRecordedVideoShell`` always adds that class.

The fix reuses ``_renderLbLabels`` (moved to
``mediaview/panels/labels.js`` so it has one home reachable from both
the photo lightbox and the shell) as a new "Labels" tab in the
recorded-shell panel-tab system (``mediaview/_shell-layout.js``'s
``_TAB_META`` + ``recorded-shell-compose.js``'s
``buildRecordedShellConfig``) — the same tab system Aufnahme-Settings
and Wetter already ride. The renderer now takes an optional ``host``
so it can target either the legacy ``#lightboxLabels`` node (photo
path, unchanged) or the tab's own content div (video path, new).

``#lightboxLabels`` itself stays force-hidden in ``.lb-recorded`` mode
deliberately: with the new tab-panel host, that legacy node is never
populated in video mode any more (only the photo path still targets
it), so the hide rule keeps it inert rather than needing to go — see
``test_lightbox_labels_css_hide_rule_still_scoped_to_legacy_node``.

We don't ship a JS DOM test harness yet, so this stays a source-grep
regression, matching test_lightbox_weather_render.py's pattern.
"""

from __future__ import annotations

import re
from pathlib import Path

_JS_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js"
_CSS_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "css"
_LIGHTBOX_JS = _JS_ROOT / "lightbox.js"
_SHELL_LAYOUT_JS = _JS_ROOT / "mediaview" / "_shell-layout.js"
_COMPOSE_JS = _JS_ROOT / "mediaview" / "recorded-shell-compose.js"
_RECORDED_MODE_JS = _JS_ROOT / "mediaview" / "recorded-mode.js"
_LABELS_PANEL_JS = _JS_ROOT / "mediaview" / "panels" / "labels.js"
_SHELL_CSS = _CSS_ROOT / "30g-mediaview-shell.css"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing at {path}"
    return path.read_text(encoding="utf-8")


def _slice_function(path: Path, name: str) -> str:
    """Extract the body of a top-level ``[export] [async] function NAME(...)``.
    Returns the source between the opening ``{`` and its matching ``}``.
    Not a full JS parser — adequate as a regression guard because these
    files carry no unbalanced braces inside string literals."""
    src = _read(path)
    pattern = re.compile(
        rf"(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{"
    )
    m = pattern.search(src)
    if not m:
        raise AssertionError(f"function {name!r} not found in {path.name}")
    start = m.end() - 1  # at the opening brace
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


def test_labels_tab_registered_in_shell_layout():
    """The panel-tab system needs a `labels` entry in _TAB_META, exactly
    like `settings` / `weather`, or buildRecordedShellConfig's
    `panels.labels` flag has no tab to attach to."""
    src = _read(_SHELL_LAYOUT_JS)
    m = re.search(r"_TAB_META\s*=\s*\{(.*?)\n\};", src, re.DOTALL)
    assert m, "_TAB_META object literal not found in _shell-layout.js"
    body = m.group(1)
    assert re.search(r"labels\s*:\s*\{[^}]*id\s*:\s*'labels'", body), (
        "_TAB_META must carry a `labels` tab descriptor — the recorded-shell "
        "Labels tab has nothing to render into without it"
    )


def test_video_shell_config_offers_labels_for_motion_clips():
    """buildRecordedShellConfig must turn the `labels` panel flag on for
    a real motion clip (not just settings/weather) so the label bubbles
    are actually reachable from the video player, not just built and
    silently unused."""
    body = _slice_function(_COMPOSE_JS, "buildRecordedShellConfig")
    assert re.search(r"panels\s*:\s*\{.*?labels\s*:\s*true", body, re.DOTALL), (
        "buildRecordedShellConfig's `panels` object must include "
        "`labels: true` for motion clips — the gap this regression closes"
    )
    assert "panelRenderers" in body and re.search(
        r"labels\s*:\s*\(host\)\s*=>\s*_renderLbLabels\(host\)", body
    ), (
        "panelRenderers.labels must call _renderLbLabels(host) — the SAME "
        "renderer the photo lightbox uses, not a second implementation"
    )


def test_video_shell_config_skips_labels_for_timelapses():
    """Timelapses carry the synthetic 'timelapse' pseudo-label, never a
    real classifier verdict — offering a correction tab for them would
    show 8 permanently-inactive bubbles. Must be gated the same way as
    `settings` (isTL ? {} : {...})."""
    body = _slice_function(_COMPOSE_JS, "buildRecordedShellConfig")
    m = re.search(r"panels\s*:\s*\{(.*?)\n\s*\},", body, re.DOTALL)
    assert m, "panels object not found inside buildRecordedShellConfig"
    panels_body = m.group(1)
    assert re.search(
        r"isTL\s*\?\s*\{\}\s*:\s*\{[^}]*settings[^}]*labels", panels_body
    ) or re.search(r"isTL\s*\?\s*\{\}\s*:\s*\{[^}]*labels[^}]*settings", panels_body), (
        "`labels: true` must be gated behind the same `isTL ? {} : {...}` "
        "branch as `settings` — timelapses must not offer a labels tab"
    )


def test_renderer_moved_to_panels_module_not_duplicated():
    """_renderLbLabels must have exactly ONE definition (mediaview/
    panels/labels.js) — CLAUDE.md forbids a parallel implementation.
    lightbox.js must no longer define it directly (it moved out), but
    every consumer (the photo path in recorded-mode.js, the video-shell
    panel renderer in recorded-shell-compose.js) must still resolve it
    from the same module."""
    decl = re.compile(r"(?:export\s+)?function\s+_renderLbLabels\s*\(")
    defining_files = [
        p
        for p in _JS_ROOT.rglob("*.js")
        if not p.name.endswith(".test.js") and decl.search(p.read_text(encoding="utf-8"))
    ]
    assert defining_files == [_LABELS_PANEL_JS], (
        f"_renderLbLabels must be defined exactly once, in {_LABELS_PANEL_JS.name} — "
        f"found definitions in {[p.name for p in defining_files]}"
    )
    assert "function _renderLbLabels" not in _read(_LIGHTBOX_JS), (
        "lightbox.js must not redeclare _renderLbLabels after the move to "
        "mediaview/panels/labels.js"
    )
    assert "from './panels/labels.js'" in _read(_RECORDED_MODE_JS), (
        "recorded-mode.js's photo path must import _renderLbLabels from "
        "the panels module, not (a since-removed) lightbox.js export"
    )
    assert "_renderLbLabels" in _read(_COMPOSE_JS), (
        "recorded-shell-compose.js must call the shared _renderLbLabels, "
        "not a second bubble renderer"
    )


def test_renderer_accepts_a_host_so_it_can_target_either_surface():
    """The renderer must be parameterised on its target host: the photo
    lightbox's legacy #lightboxLabels node (no arg — defaulted) and the
    recorded-shell tab's own content div (host passed explicitly) are
    two different DOM nodes belonging to two different code paths."""
    body = _slice_function(_LABELS_PANEL_JS, "_renderLbLabels")
    assert re.search(
        r"_renderLbLabels\s*\(\s*host\s*\)", _read(_LABELS_PANEL_JS)
    ), "_renderLbLabels must declare a `host` parameter"
    assert "host || byId('lightboxLabels')" in body, (
        "with no host given, _renderLbLabels must still fall back to the "
        "legacy #lightboxLabels node — the photo path's call site passes "
        "no argument and must keep working unchanged"
    )


def test_css_hide_rule_still_scoped_to_the_legacy_node_only():
    """`#lightboxModal.lb-recorded #lightboxLabels { display: none }`
    hides the OLD photo-only node — which the video shell reparents
    (inside #lightboxMediaWrap) but, with the new tab-panel host, never
    populates any more. That's still correct: it keeps an always-empty
    legacy node inert. What must NOT happen is that hide rule (or any
    other .lb-recorded rule) also catching the NEW tab-panel surface
    (.mv-labels-row / .mv-tabs-content) — that would silently re-open
    this exact bug in the new location."""
    css = _read(_SHELL_CSS)
    assert re.search(
        r"#lightboxLabels\s*\{\s*\n?\s*display:\s*none\s*!important", css
    ) or re.search(r"#lightboxLabels\s*\{[^}]*display:\s*none\s*!important", css), (
        "expected the existing #lightboxLabels hide rule (scoped to the "
        "legacy node only) to still be present"
    )
    # None of the broad .lb-recorded hide/collapse rules may name the new
    # tab surface — a regression here would silently re-hide the Labels tab.
    for bad in (".mv-labels-row", ".mv-tabs-content", "labels"):
        for m in re.finditer(r"\.lb-recorded[^{]*\{[^}]*display:\s*none[^}]*\}", css, re.DOTALL):
            assert bad not in m.group(0), (
                f"a .lb-recorded hide rule mentions {bad!r} — the new Labels "
                "tab must never be force-hidden the way #lightboxLabels was"
            )


def test_labels_row_css_class_is_styled():
    """_renderLbLabels wraps its bubbles in a `.mv-labels-row` div so the
    renderer needs no host-specific layout — pin that the class is
    actually styled (flex row), not just referenced and silently inert."""
    assert 'class="mv-labels-row"' in _read(
        _LABELS_PANEL_JS
    ), "_renderLbLabels must wrap its bubbles in a .mv-labels-row div"
    css = _read(_SHELL_CSS)
    m = re.search(r"\.mv-labels-row\s*\{([^}]*)\}", css)
    assert m, ".mv-labels-row must be styled in 30g-mediaview-shell.css"
    assert "display: flex" in m.group(1), ".mv-labels-row must lay its bubbles out as a flex row"
