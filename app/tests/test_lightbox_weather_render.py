"""Regression — the weather/sunrise lightbox bug where the playbar
rendered twice and produced two empty red-bordered placeholder cards.

Root cause: ``openTLPlayer`` called ``_setupVideoChrome(item)`` —
which already internally calls ``lbRenderTrackTimeline + mountRecordedPanels`` —
and THEN called both again at the end. The second mount stacked
on top of the first, doubling every panel element and corrupting
the SVG playbar layout.

We don't ship a JS test harness yet, so this guard is a source-grep
regression: it scans ``lightbox.js`` for the duplicate-call shape
and fails if it reappears. When a JS harness is added later, the
caller-side render assertion (non-zero video width, no duplicated
playbar) can land here too.
"""
from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIGHTBOX_JS = _REPO_ROOT / "app" / "web" / "static" / "js" / "lightbox.js"


def _read_lightbox() -> str:
    assert _LIGHTBOX_JS.exists(), f"lightbox.js missing at {_LIGHTBOX_JS}"
    return _LIGHTBOX_JS.read_text(encoding="utf-8")


def _slice_function(src: str, name: str) -> str:
    """Extract the body of a top-level function declared as
    ``export function NAME(...)`` or ``function NAME(...)``. Returns
    the source between the opening ``{`` and its matching ``}``. Not
    a full JS parser — the lightbox file's functions don't contain
    nested ``{`` patterns inside template literals that would fool
    a naive brace counter. Adequate as a regression guard."""
    pattern = re.compile(rf"(?:export\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{")
    m = pattern.search(src)
    if not m:
        raise AssertionError(f"function {name!r} not found in lightbox.js")
    start = m.end() - 1   # at the opening brace
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(f"unbalanced braces inside {name!r}")


def test_setup_video_chrome_calls_render_track_timeline_exactly_once():
    """``_setupVideoChrome`` is the canonical chrome mount — it must
    call ``lbRenderTrackTimeline`` once."""
    body = _slice_function(_read_lightbox(), "_setupVideoChrome")
    count = body.count("lbRenderTrackTimeline(")
    assert count == 1, (
        f"_setupVideoChrome calls lbRenderTrackTimeline {count}x — expected 1. "
        "If you're adding a deliberate second call, update this test."
    )


def test_setup_video_chrome_calls_mount_recorded_panels_exactly_once():
    body = _slice_function(_read_lightbox(), "_setupVideoChrome")
    count = body.count("mountRecordedPanels(")
    assert count == 1, (
        f"_setupVideoChrome calls mountRecordedPanels {count}x — expected 1."
    )


def test_open_tl_player_does_not_double_call_render_track_timeline():
    """``openTLPlayer`` already calls ``_setupVideoChrome(item)``
    which mounts the playbar internally. Calling
    ``lbRenderTrackTimeline`` AGAIN here stacks a second playbar on
    top and produced the duplicated "0s ... 1s" axis + the two
    empty red-bordered cards in the weather/sunrise lightbox."""
    body = _slice_function(_read_lightbox(), "openTLPlayer")
    # _setupVideoChrome call is mandatory.
    assert "_setupVideoChrome(" in body, \
        "openTLPlayer must call _setupVideoChrome to mount chrome"
    # The post-fix body must NOT carry an additional direct call.
    assert body.count("lbRenderTrackTimeline(") == 0, (
        "openTLPlayer is calling lbRenderTrackTimeline AGAIN after "
        "_setupVideoChrome already mounted the playbar — this is the "
        "weather-lightbox double-render bug. Drop the duplicate call."
    )
    assert body.count("mountRecordedPanels(") == 0, (
        "openTLPlayer is calling mountRecordedPanels AGAIN after "
        "_setupVideoChrome already mounted the panel strip — duplicate "
        "Wetter card + Nach-Erkennung button results."
    )


def test_open_tl_player_loads_tracks_sidecar():
    """The tracks-fetcher call IS expected to live in openTLPlayer
    (it isn't inside _setupVideoChrome). Pin its presence so a
    future cleanup doesn't accidentally drop tracks-sidecar loading
    along with the duplicate render."""
    body = _slice_function(_read_lightbox(), "openTLPlayer")
    assert "lbLoadTracksForItem(" in body, \
        "openTLPlayer must still trigger the tracks fetcher"


def test_close_lightbox_unmounts_zone_overlay():
    """closeLightbox tears down the zone overlay so the
    ResizeObserver inside it doesn't leak across modal opens
    (cm-43)."""
    body = _slice_function(_read_lightbox(), "closeLightbox")
    assert "unmountZoneOverlayForLightbox" in body, (
        "closeLightbox must call unmountZoneOverlayForLightbox to "
        "release the zone-overlay ResizeObserver."
    )
