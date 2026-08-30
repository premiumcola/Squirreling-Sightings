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
_BOX_STYLE = (_JS_DIR / "mediathek" / "bbox-overlay" / "_box-style.js").read_text(
    encoding="utf-8"
)
_RENDERER = (_JS_DIR / "mediathek" / "bbox-overlay" / "renderer.js").read_text(encoding="utf-8")
_CLASSFILTER = (_JS_DIR / "mediathek" / "bbox-overlay" / "_classfilter.js").read_text(
    encoding="utf-8"
)


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
