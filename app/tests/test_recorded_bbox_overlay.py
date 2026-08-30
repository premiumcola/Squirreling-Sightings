"""Regression guards for the recorded (Mediathek) bbox overlay.

Three things this pins, none of which were covered before (grepping
tests/ for tracks/bbox/overlay found nothing exercising renderer.js's
pure functions):

1. The status-legend fold is real. status-legend.js's own docstring used
   to claim mediathek/bbox-overlay/renderer.js's private _STATUS_STYLE /
   _classifyTrackStatus were "folded" into MV_STATUS_STYLE /
   mvStatusCategory — they were not; renderer.js kept an independent
   copy. The fold now lives in _box-style.js's resolveBoxStyle(), which
   imports and calls both. Mirrors test_live_bbox_overlay.py's
   `test_box_line_style_comes_from_the_shared_legend_table` for the
   live side.

2. The "triggering class" filter actually narrows. Recorded's
   `_classfilter.js` used to expose only the camera-wide object_filter
   allow-list (`_resolveAllowedLabels`) — every class the camera looks
   for painted, not just the one the event counts itself under. It now
   also narrows to `primaryLabel(item.labels)` (core/primary-label.js,
   mirroring app/app/labels.py::primary_label()).

3. The SVG box painter's output shape + positioning math. Following
   the canvas/trail-layer.js precedent (one shared geometry/style
   helper, two thin per-surface painters), the SVG sibling reuses
   core/video-fit.js's fittedRect() for the letterbox math instead of
   keeping a second copy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_JS_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "js"
_BOX_STYLE = (_JS_DIR / "mediathek" / "bbox-overlay" / "_box-style.js").read_text(encoding="utf-8")
_RENDERER = (_JS_DIR / "mediathek" / "bbox-overlay" / "renderer.js").read_text(encoding="utf-8")
_CLASSFILTER = (_JS_DIR / "mediathek" / "bbox-overlay" / "_classfilter.js").read_text(
    encoding="utf-8"
)
_SVG_BOXES = (_JS_DIR / "mediathek" / "bbox-overlay" / "svg-boxes.js").read_text(encoding="utf-8")


# ── 1 · the status-legend fold ──────────────────────────────────────────


def test_box_style_reads_the_shared_legend_table():
    assert "MV_STATUS_STYLE" in _BOX_STYLE
    assert "mvStatusCategory" in _BOX_STYLE


def test_renderer_no_longer_keeps_a_private_status_style_duplicate():
    assert "_STATUS_STYLE" not in _RENDERER, (
        "renderer.js must not keep its own status→style table any more — "
        "_box-style.js's resolveBoxStyle() is the one owner"
    )


def test_status_style_marker_and_pill_text_agree_on_spacing():
    """MV_STATUS_STYLE's marker carries NO trailing space (status-legend.js
    adds it at use time) — the pill-text builder must do the same, not
    assume the marker bakes it in like the old private duplicate did."""
    out = _js(
        """
        const mod = await import(JS + '/mediathek/bbox-overlay/_box-style.js');
        console.log(JSON.stringify({
          weak: mod.resolveBoxStyle({ score: 0.82 }, '#22c55e', 'weak', false, 3).text,
          ghost: mod.resolveBoxStyle({ score: 0.3 }, '#22c55e', 'ghost', false, 2).text,
          confirmed: mod.resolveBoxStyle({ score: 0.9 }, '#22c55e', 'confirmed', false, 1).text,
        }));
        """
    )
    assert out == {"weak": "↓ #3 · 82%", "ghost": "≈ #2 · 30%", "confirmed": "#1 · 90%"}


# ── 2 · the triggering-class filter ─────────────────────────────────────


def test_classfilter_narrows_to_the_primary_label():
    """A clip whose camera allows both 'person' and 'cat' — but whose event
    labels say the trigger was 'person' — must only paint person tracks."""
    out = _js(
        """
        const { lbState } = await import(JS + '/mediathek/state.js');
        const { state } = await import(JS + '/core/state.js');
        const mod = await import(JS + '/mediathek/bbox-overlay/_classfilter.js');
        state.cameras = [{ id: 'cam_a', object_filter: ['person', 'cat'] }];
        lbState.item = { camera_id: 'cam_a', labels: ['person', 'cat'] };
        const isVisible = mod._makeLabelVisibleFn();
        console.log(JSON.stringify({ person: isVisible('person'), cat: isVisible('cat') }));
        """
    )
    assert out == {"person": True, "cat": False}


def test_classfilter_does_not_narrow_a_motion_only_event():
    """No recognized object label on the event (primaryLabel falls back to
    'motion') — there is no single triggering class to narrow to, so the
    camera-wide allow-list still governs unchanged."""
    out = _js(
        """
        const { lbState } = await import(JS + '/mediathek/state.js');
        const { state } = await import(JS + '/core/state.js');
        const mod = await import(JS + '/mediathek/bbox-overlay/_classfilter.js');
        state.cameras = [{ id: 'cam_a', object_filter: ['person', 'cat'] }];
        lbState.item = { camera_id: 'cam_a', labels: ['motion'] };
        const isVisible = mod._makeLabelVisibleFn();
        console.log(JSON.stringify({ person: isVisible('person'), cat: isVisible('cat') }));
        """
    )
    assert out == {"person": True, "cat": True}


def test_classfilter_uses_the_shared_primary_label_helper():
    assert "primaryLabel" in _CLASSFILTER
    assert "core/primary-label.js" in _CLASSFILTER


# ── 3 · the SVG box painter ──────────────────────────────────────────────


def test_svg_boxes_reuses_the_shared_fit_helper_not_a_second_copy():
    """The audit flagged renderer.js's inline letterbox math as a
    duplicate of core/video-fit.js's fittedRect(). Both the canvas prep
    (renderer.js) and the SVG painter must import fittedRect rather than
    re-deriving the scale/offset formula."""
    assert "fittedRect" in _SVG_BOXES
    assert "core/video-fit.js" in _SVG_BOXES
    assert "fittedRect" in _RENDERER
    assert "core/video-fit.js" in _RENDERER


def test_svg_box_layer_does_not_collide_with_the_zone_overlay_z_index():
    """z-index 4 inside #lightboxMediaWrap is already claimed by the
    zone/mask overlay (mediaview/canvas/zone-overlay-mount.js) and
    #lightboxLabels — both of which must stay ABOVE detections, matching
    the pre-existing stacking. The box layer belongs at the same tier as
    the trails canvas (z-index 3); it visually sits above trails purely
    by DOM order (appended after the canvas), not a z-index bump."""
    assert "z-index:4" not in _SVG_BOXES
    assert "z-index:3" in _SVG_BOXES


def test_svg_box_group_has_a_rect_and_a_label_plate():
    """One track, one <g> with a stroked <rect> (the box) plus a filled
    <rect> + <text> (the pill) — mirrors live-detect-bbox-shapes.js's
    _buildBboxGroup output shape, just with recorded's own pill text
    convention (marker + #num + pct, no class name)."""
    out = _js(
        """
        const mod = await import(JS + '/mediathek/bbox-overlay/svg-boxes.js');

        function fakeEl() {
          const el = { style: {}, dataset: {}, parentNode: null,
            getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 300 }),
            setAttribute() {}, appendChild() {} };
          return el;
        }
        const wrap = fakeEl();
        const media = Object.assign(fakeEl(), { videoWidth: 800, videoHeight: 600 });
        let created = null;
        document.createElementNS = () => { created = fakeEl(); created.innerHTML = ''; return created; };
        document.getElementById = (id) => (id === 'lightboxBboxSvg' ? created : null);

        const sample = { bbox: { x1: 100, y1: 100, x2: 300, y2: 400 }, score: 0.82 };
        mod.drawTrackBoxesSvg(media, wrap, 800, 600, [
          { sample, trackColor: '#22c55e', status: 'weak', masked: false, trackNum: 3 },
        ]);
        console.log(JSON.stringify({
          rectCount: (created.innerHTML.match(/<rect/g) || []).length,
          hasTextEl: created.innerHTML.includes('<text'),
          hasDash: created.innerHTML.includes('stroke-dasharray="6 4"'),
          hasNonScaling: created.innerHTML.includes('vector-effect="non-scaling-stroke"'),
          labelText: /<text[^>]*>([^<]+)<\\/text>/.exec(created.innerHTML)[1],
        }));
        """
    )
    assert out["rectCount"] == 2, "expected the box rect + the pill background rect"
    assert out["hasTextEl"] is True
    assert out["hasDash"] is True, "weak status must paint a dashed stroke"
    assert out["hasNonScaling"] is True, "stroke must not thicken when the viewBox scales"
    assert out["labelText"] == "↓ #3 · 82%"


def test_svg_positioned_via_the_letterboxed_media_rect():
    """A 800x600 source letterboxed into a 400x300 host at (10,20) must
    position/size the SVG to the fitted rect, not the raw host box."""
    out = _js(
        """
        const mod = await import(JS + '/mediathek/bbox-overlay/svg-boxes.js');

        function fakeEl(rect) {
          return { style: {}, dataset: {}, parentNode: null,
            getBoundingClientRect: () => rect,
            setAttribute() {}, appendChild() {} };
        }
        const wrap = fakeEl({ left: 10, top: 20, width: 400, height: 300 });
        const media = Object.assign(fakeEl({ left: 10, top: 20, width: 400, height: 300 }),
          { videoWidth: 800, videoHeight: 600 });
        let created = null;
        document.createElementNS = () => { created = fakeEl({}); created.innerHTML = ''; return created; };
        document.getElementById = (id) => (id === 'lightboxBboxSvg' ? created : null);

        mod.drawTrackBoxesSvg(media, wrap, 800, 600, []);
        console.log(JSON.stringify({
          left: created.style.left, top: created.style.top,
          width: created.style.width, height: created.style.height,
        }));
        """
    )
    # 800x600 into 400x300 host → scale 0.5, fits exactly (same 4:3 aspect),
    # so no letterbox gutter and the rect covers the whole host.
    assert out == {"left": "0px", "top": "0px", "width": "400px", "height": "300px"}


def test_primary_label_mirrors_the_python_vocabulary():
    """core/primary-label.js's OBJECT_LABELS + primaryLabel() must agree
    with app/app/labels.py — same fallback-to-motion rule."""
    out = _js(
        """
        const { primaryLabel, MOTION_LABEL } = await import(JS + '/core/primary-label.js');
        console.log(JSON.stringify({
          firstWins: primaryLabel(['cat', 'person']),
          skipsUnknown: primaryLabel(['motion', 'fox']),
          emptyFallsBack: primaryLabel([]),
          nullFallsBack: primaryLabel(null),
          motionSentinel: MOTION_LABEL,
        }));
        """
    )
    assert out == {
        "firstWins": "cat",
        "skipsUnknown": "fox",
        "emptyFallsBack": "motion",
        "nullFallsBack": "motion",
        "motionSentinel": "motion",
    }
