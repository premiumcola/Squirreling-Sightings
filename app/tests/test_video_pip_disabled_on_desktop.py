"""Regression — Chrome (and other Chromium browsers) offer native
Picture-in-Picture for any playing <video> by default, via the
browser's own Global Media Controls popup. The operator reported this
popping a recorded clip out of the app's own player entirely, with no
app chrome at all ("ganz komisch der player jetzt in chrome???") and
was explicit: every clip stays in OUR player on desktop; only iOS
keeps native video behaviour.

Fix: set `videoEl.disablePictureInPicture = !isIOS` (core/ios-video.js's
single isIOS detection) on every <video> element this app mounts for
playback. This cleanly disables the player's OWN PiP button too on
non-iOS — player/_pip.js::canPictureInPicture already checks
`videoEl.disablePictureInPicture` and returns false, so no dangling
control is left behind that would silently fail if tapped. Confirmed
with the operator directly: losing the custom PiP button on desktop
(rather than trying to suppress only the browser's auto-detach while
keeping the button) is the accepted trade-off, not an oversight.

Two call sites carry a <video> element:
  * mediaview/recorded-shell-compose.js — the reused #lightboxVideo
    node every recorded MOTION clip opens through.
  * mediaview/canvas/index.js::mountCanvasSource — weather clips (and
    anything else that mounts a fresh <video> via the canvas source
    switcher).

We don't ship a JS DOM test harness yet, so this stays a source-grep
regression, matching test_lightbox_weather_render.py's pattern.
"""

from __future__ import annotations

from pathlib import Path

_JS_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js"
_COMPOSE_JS = _JS_ROOT / "mediaview" / "recorded-shell-compose.js"
_CANVAS_JS = _JS_ROOT / "mediaview" / "canvas" / "index.js"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing at {path}"
    return path.read_text(encoding="utf-8")


def test_recorded_shell_video_disables_pip_on_non_ios():
    src = _read(_COMPOSE_JS)
    assert "import { isIOS } from '../core/ios-video.js';" in src
    assert "videoEl.disablePictureInPicture = !isIOS" in src


def test_canvas_source_video_disables_pip_on_non_ios():
    src = _read(_CANVAS_JS)
    assert "import { isIOS } from '../../core/ios-video.js';" in src
    assert "el.disablePictureInPicture = !isIOS" in src


def test_pip_disable_is_set_after_muted_and_loop_not_before():
    """The PiP flag has to land on the SAME element the src/muted/loop
    setup already configures, in the same synchronous block — not a
    separately-timed assignment that could race a re-mount."""
    src = _read(_COMPOSE_JS)
    muted_pos = src.index("videoEl.muted = true;")
    pip_pos = src.index("videoEl.disablePictureInPicture = !isIOS")
    assert muted_pos < pip_pos

    canvas_src = _read(_CANVAS_JS)
    canvas_muted_pos = canvas_src.index("el.muted = true;")
    canvas_pip_pos = canvas_src.index("el.disablePictureInPicture = !isIOS")
    assert canvas_muted_pos < canvas_pip_pos
