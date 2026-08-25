"""Regression — the weather/sunrise lightbox bug where the playbar
rendered twice and produced two empty red-bordered placeholder cards.

Original root cause: ``openTLPlayer`` called ``_setupVideoChrome(item)``
— which already mounted playbar + panel strip internally — and THEN
called both again at the end. The second mount stacked on top of the
first, doubling every panel element and corrupting the SVG playbar.

The MediaView migration retired ``_setupVideoChrome`` and the legacy
chrome entirely: ``mediaview/shell.js`` is now the single mount point,
``openTLPlayer`` is a one-line delegate into it, and the tracks fetcher
moved to ``mediaview/recorded-mode.js``. The guard follows the invariant
to its new home rather than the function it used to live in — one
playbar mount, no second call on the caller side.

We don't ship a JS test harness yet, so this stays a source-grep
regression. When a JS harness lands, the caller-side render assertion
(non-zero video width, no duplicated playbar) can join it here.
"""

from __future__ import annotations

import re
from pathlib import Path

_JS_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js"
_LIGHTBOX_JS = _JS_ROOT / "lightbox.js"
_SHELL_JS = _JS_ROOT / "mediaview" / "shell.js"
_RECORDED_JS = _JS_ROOT / "mediaview" / "recorded-mode.js"


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


def test_shell_renders_track_timeline_exactly_once():
    """``mountMediaView`` is the canonical chrome mount — it owns the
    single ``lbRenderTrackTimeline`` call for recorded/timelapse."""
    body = _slice_function(_SHELL_JS, "mountMediaView")
    count = body.count("lbRenderTrackTimeline(")
    assert count == 1, (
        f"mountMediaView calls lbRenderTrackTimeline {count}x — expected 1. "
        "If you're adding a deliberate second call, update this test."
    )


def test_shell_clears_the_timeline_on_teardown():
    """The mount is paired with a teardown, otherwise reopening the
    modal stacks a second playbar on the first — the original bug in
    its new location."""
    body = _slice_function(_SHELL_JS, "mountMediaView")
    assert "lbClearTrackTimeline(" in body, (
        "mountMediaView mounts the playbar but never registers "
        "lbClearTrackTimeline as teardown — reopening will double-render."
    )


def test_open_tl_player_only_delegates_to_the_shell():
    """``openTLPlayer`` is the public entry (``window.openTLPlayer`` +
    the openLightbox dispatch) and must do nothing but hand off to the
    shell. Any direct chrome call here is the double-render bug."""
    body = _slice_function(_LIGHTBOX_JS, "openTLPlayer")
    assert "openMediaView(" in body, "openTLPlayer must delegate to openMediaView"
    assert body.count("lbRenderTrackTimeline(") == 0, (
        "openTLPlayer calls lbRenderTrackTimeline directly — the shell "
        "already mounted the playbar. This is the weather-lightbox "
        "double-render bug. Drop the call."
    )


def test_legacy_chrome_mount_stays_retired():
    """``_setupVideoChrome`` / ``mountRecordedPanels`` were the legacy
    mount pair. They are gone; a re-declaration means a parallel
    implementation next to the shell. Prose comments that reference the
    old names as history are fine — only a definition trips this."""
    for symbol in ("_setupVideoChrome", "mountRecordedPanels"):
        decl = re.compile(
            rf"(?:function\s+{re.escape(symbol)}\s*\(|"
            rf"(?:const|let|var)\s+{re.escape(symbol)}\s*=)"
        )
        hits = [
            p.name for p in _JS_ROOT.rglob("*.js") if decl.search(p.read_text(encoding="utf-8"))
        ]
        assert not hits, (
            f"{symbol} is declared again in {hits} — the MediaView shell is "
            "the single chrome mount point. Extend the shell instead."
        )


def test_recorded_mode_loads_tracks_sidecar():
    """The tracks fetcher lives on the recorded path, not in the shell.
    Pin its presence so a cleanup doesn't drop the bbox/trail overlay
    and the swimlane data along with it."""
    body = _slice_function(_RECORDED_JS, "_openRecordedVideoShell")
    assert "lbLoadTracksForItem(" in body, (
        "_openRecordedVideoShell must still trigger the tracks fetcher"
    )


def test_close_lightbox_unmounts_zone_overlay():
    """closeLightbox tears down the zone overlay so the
    ResizeObserver inside it doesn't leak across modal opens
    (cm-43)."""
    body = _slice_function(_LIGHTBOX_JS, "closeLightbox")
    assert "unmountZoneOverlayForLightbox" in body, (
        "closeLightbox must call unmountZoneOverlayForLightbox to "
        "release the zone-overlay ResizeObserver."
    )
