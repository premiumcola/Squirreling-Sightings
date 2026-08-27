"""Regression guards for the Simulieren (live-detect) bbox overlay.

Two separate failures used to make the live boxes invisible, and both
are the kind that no unit test can catch after the fact because the
symptom is "nothing is drawn" rather than an exception.

1 · The `inset` shorthand.
    ``_positionSvgOverImage`` measured the letterboxed picture rect
    correctly, wrote ``style.left`` / ``style.top`` — and then, on the
    very next line, wrote ``style.inset = 'auto'``. ``inset`` is the
    shorthand for top/right/bottom/left, so that single assignment reset
    the offsets it had just computed. The SVG fell back to its static
    position, i.e. below the <img> inside a host with overflow:hidden,
    and every box was clipped away. The only visible evidence was an
    empty picture with a populated Detections panel.

    The fix is structural: the positioner writes the four longhands and
    never the shorthand. These tests pin that, because a future "tidy
    this up into `inset`" refactor would silently re-break it.

2 · Label scale.
    The overlay's viewBox is the SNAPSHOT's pixel size (typically
    960×540) while the element on screen is ~390 px wide on an iPhone.
    A `font-size="12"` authored in viewBox units therefore renders at
    12 × 390/960 ≈ 5 px. The shapes module multiplies every text/plate
    dimension by ``k = frameW / screenW`` so the plate is a constant
    size on screen; the maths is replicated below.
"""

from __future__ import annotations

import re
from pathlib import Path

_JS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js" / "mediaview"
_FIT = _JS / "live-detect-bbox-fit.js"
_SHAPES = _JS / "live-detect-bbox-shapes.js"
_OVERLAYS = _JS / "live-detect-overlays.js"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


# ── 1 · the inset-shorthand guard ────────────────────────────────────


def test_positioner_never_writes_the_inset_shorthand():
    """`style.inset` anywhere in the positioner re-expands to all four
    offsets and clobbers the left/top it just computed."""
    src = _read(_FIT)
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )
    assert "style.inset" not in code, "live-detect-bbox-fit.js must not touch the inset shorthand"
    assert not re.search(r"\binset\s*:", code), "no `inset:` declaration in the positioner either"


def test_overlay_layer_css_text_uses_longhands():
    """The layer's initial cssText seeds the same four offsets. Using
    `inset:0` there puts a shorthand in the SAME declaration block the
    positioner later rewrites — one CSSOM quirk away from the bug."""
    src = _read(_OVERLAYS)
    m = re.search(r"el\.style\.cssText\s*=\s*(.+?);\n", src, re.DOTALL)
    assert m, "_ensureOverlayLayer no longer assigns cssText"
    decl = m.group(1)
    assert "inset:" not in decl, "seed the offsets as longhands, never as `inset`"
    for prop in ("left:", "top:", "right:", "bottom:"):
        assert prop in decl, f"cssText seed is missing {prop}"


def test_place_overlay_writes_all_four_offsets():
    """A rect is only unambiguous when both the anchored and the
    released edges are stated — otherwise a leftover `right`/`bottom`
    from a previous layout over-constrains the box."""
    src = _read(_FIT)
    body = src[src.index("export function _placeOverlay") :]
    body = body[: body.index("\n}")]
    for prop in ("s.left", "s.top", "s.right", "s.bottom", "s.width", "s.height"):
        assert prop in body, f"_placeOverlay must set {prop}"


# ── 2 · the letterbox fallback (object-fit: contain, centred) ─────────


def _aspect_fallback(host_w: float, host_h: float, src_w: float, src_h: float):
    """Python mirror of ``_aspectFallback`` in live-detect-bbox-fit.js.
    Keep in lockstep:
        scale = min(host_w / src_w, host_h / src_h)
        w, h  = src_w * scale, src_h * scale
        dx,dy = (host_w - w) / 2, (host_h - h) / 2
    """
    scale = min(host_w / src_w, host_h / src_h)
    w = src_w * scale
    h = src_h * scale
    return ((host_w - w) / 2, (host_h - h) / 2, w, h)


def test_fallback_fills_a_matching_aspect_exactly():
    """16:9 snapshot in a 16:9 stage — no letterbox, no offset."""
    dx, dy, w, h = _aspect_fallback(390, 219.375, 960, 540)
    assert abs(dx) < 1e-6 and abs(dy) < 1e-6
    assert abs(w - 390) < 1e-6
    assert abs(h - 219.375) < 1e-6


def test_fallback_centres_a_four_three_camera():
    """A 4:3 camera in the 16:9 stage letterboxes on the SIDES and must
    be centred. The previous fallback pinned dx=0/dy=0 and stretched to
    the host width, which pushed every box left and off the picture."""
    dx, dy, w, h = _aspect_fallback(400, 225, 1280, 960)
    assert abs(h - 225) < 1e-6, "height is the limiting dimension"
    assert abs(w - 300) < 1e-6
    assert abs(dx - 50) < 1e-6, "equal gutters left and right"
    assert abs(dy) < 1e-6


def test_fallback_never_overflows_the_host():
    for host_w, host_h, src_w, src_h in (
        (390, 219, 2560, 1440),
        (375, 211, 640, 480),
        (393, 221, 1920, 1080),
    ):
        dx, dy, w, h = _aspect_fallback(host_w, host_h, src_w, src_h)
        assert dx >= -1e-9 and dy >= -1e-9
        assert dx + w <= host_w + 1e-9
        assert dy + h <= host_h + 1e-9


# ── 3 · label scale ──────────────────────────────────────────────────


def _js_const(name: str) -> float:
    src = _read(_SHAPES)
    m = re.search(rf"const {re.escape(name)}\s*=\s*([0-9.]+)\s*;", src)
    assert m, f"{name} not found in live-detect-bbox-shapes.js"
    return float(m.group(1))


def test_overlay_scale_is_frame_over_screen():
    src = _read(_SHAPES)
    body = src[src.index("export function _overlayScale") :]
    body = body[: body.index("\n}")]
    assert "frameW / screenW" in body, "k must be viewBox units per CSS pixel"


def test_label_renders_at_a_constant_on_screen_size():
    """font_px_on_screen = (_FONT_PX * k) * (screenW / frameW) = _FONT_PX
    for every snapshot resolution. The whole point of the k factor."""
    font_px = _js_const("_FONT_PX")
    assert font_px >= 11, "anything under ~11 px is unreadable on a phone"
    for frame_w, screen_w in ((960, 390), (960, 375), (2560, 393), (640, 800)):
        k = frame_w / screen_w
        authored = font_px * k
        on_screen = authored * (screen_w / frame_w)
        assert abs(on_screen - font_px) < 1e-9


def test_unscaled_label_would_have_been_invisible():
    """Documents the bug this guards: the pre-fix renderer authored a
    literal font-size of 11 into a 960-wide viewBox shown at 390 px."""
    assert 11 * (390 / 960) < 5


def test_plate_is_taller_than_its_text():
    assert _js_const("_PLATE_H_PX") > _js_const("_FONT_PX")


def test_label_carries_track_class_and_confidence():
    """The box must name the same thing the Detections panel row does —
    "#1 Person · 82 %" — otherwise the picture and the panel can't be
    matched up by eye."""
    src = _read(_SHAPES)
    body = src[src.index("export function _bboxLabelText") :]
    body = body[: body.index("\n}")]
    assert "track_num" in body, "track number missing from the box label"
    assert "OBJ_LABEL" in body, "class name missing from the box label"
    assert "d.score" in body, "confidence missing from the box label"


def test_box_line_style_comes_from_the_shared_legend_table():
    """Dash + alpha are read from status-legend.js' MV_STATUS_STYLE so a
    painted box and the swatch that explains it cannot drift apart."""
    src = _read(_SHAPES)
    assert "MV_STATUS_STYLE" in src
    assert "mvStatusCategory" in src
