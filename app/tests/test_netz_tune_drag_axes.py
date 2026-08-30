"""The settings radar's drag needs `netzState.tuneAxes` to be populated.

Shipped broken in 5efa6ab: `_state.js` DECLARES `tuneAxes: []` and
`_tune_drag.js:_axisByKey` READS it, but nothing ever assigned it. Every
`pointerdown` on a vertex therefore hit `if (!axis || !spec) return;`
and the vertex never moved — silently, because a bail-out looks exactly
like "the user didn't drag far enough".

A source-grep would not have caught this (both the declaration and the
read are present and spelled correctly); only executing the render and
then looking at the state does.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

# A camera payload shaped like GET /api/netz/state's `tuning` block.
_STATE = """
  const st = { cam_id: 'cam_a', cam_name: 'Werkstatt', tuning: {
    frame_interval_ms: 500, motion_sensitivity: 0.5, post_motion_tail_s: 0,
    track_miss_grace_seconds: 0, track_iou_match_threshold: 0,
    roi_mode: 'off', wildlife_motion_sensitivity: 0, roi_min_net_disp_frac: 0,
  } };
"""


def test_rendering_the_settings_radar_populates_the_drag_lookup():
    """THE regression test — this is what made the drag inert."""
    out = _js(
        f"""
        const tuning = await import(JS + '/netz/_tuning.js');
        const {{ netzState }} = await import(JS + '/netz/_state.js');
        {_STATE}
        netzState.state = st;
        netzState.camId = 'cam_a';
        tuning.tuningHtml(st);
        console.log(JSON.stringify({{
          n: (netzState.tuneAxes || []).length,
          keys: (netzState.tuneAxes || []).map((a) => a.key),
        }}));
        """
    )
    assert out["n"] == 8, "tuneAxes never populated — every vertex drag bails out"
    assert "frame_interval_ms" in out["keys"]


def test_the_lookup_the_drag_actually_performs_resolves():
    """Mirrors `_tune_drag.js:_axisByKey` exactly. If this returns null
    the pointerdown handler returns before anything moves."""
    out = _js(
        f"""
        const tuning = await import(JS + '/netz/_tuning.js');
        const {{ netzState }} = await import(JS + '/netz/_state.js');
        {_STATE}
        netzState.state = st;
        netzState.camId = 'cam_a';
        tuning.tuningHtml(st);
        const found = (netzState.tuneAxes || []).find((a) => a.key === 'motion_sensitivity');
        console.log(JSON.stringify({{ ok: !!found, e: found ? found.E : null }}));
        """
    )
    assert out["ok"] is True
    # motion_sensitivity 0.5 on a 0.1-1.0 non-inverted scale ~= E 44.
    assert out["e"] == pytest.approx(44, abs=1)


def test_the_staged_value_survives_into_the_axis_rows():
    """A staged (dragged, uncommitted) value must be what the next
    render — and therefore the next drag's starting point — reads."""
    out = _js(
        f"""
        const tuning = await import(JS + '/netz/_tuning.js');
        const {{ netzState }} = await import(JS + '/netz/_state.js');
        {_STATE}
        netzState.state = st;
        netzState.camId = 'cam_a';
        netzState.tuneStaged = {{ roi_mode: '3x3' }};
        tuning.tuningHtml(st);
        const roi = (netzState.tuneAxes || []).find((a) => a.key === 'roi_mode');
        console.log(JSON.stringify({{ raw: roi ? roi.raw : null, e: roi ? roi.E : null }}));
        """
    )
    assert out["raw"] == "3x3"
    assert out["e"] == 100
