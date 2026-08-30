"""The settings radar's drag lookup, and its per-camera isolation.

Two distinct hazards live here.

1. Shipped broken in 5efa6ab: `_state.js` DECLARED `tuneAxes` and
   `_tune_drag.js` READ it, but nothing ever assigned it, so every
   `pointerdown` bailed and the vertex silently never moved. A source
   grep could not catch that — both halves were spelled correctly; only
   executing the render and then inspecting the state can.

2. The page now shows EVERY camera's net at once. `tuneAxes` and
   `tuneStaged` are therefore keyed by camera id. If either ever
   collapses back to a flat map, a drag on camera B stages onto camera A
   and "Übernehmen" PATCHes the wrong camera — a silent wrong-target
   write, not an error.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_TUNING = """{
  frame_interval_ms: 500, motion_sensitivity: 0.5, post_motion_tail_s: 0,
  track_miss_grace_seconds: 0, track_iou_match_threshold: 0,
  roi_mode: 'off', wildlife_motion_sensitivity: 0, roi_min_net_disp_frac: 0,
}"""

# renderCards only ever assigns host.innerHTML; a plain sink is enough.
_SETUP = f"""
  const cards = await import(JS + '/netz/_cards.js');
  const S = await import(JS + '/netz/_state.js');
  const host = {{ innerHTML: '' }};
  S.netzState.cameras = [
    {{ id: 'cam_a', name: 'Werkstatt' }},
    {{ id: 'cam_b', name: 'Garten' }},
  ];
  S.netzState.states = {{
    cam_a: {{ cam_id: 'cam_a', cam_name: 'Werkstatt', role: 'security',
             axes: [], frozen: [], tuning: {_TUNING} }},
    cam_b: {{ cam_id: 'cam_b', cam_name: 'Garten', role: 'garden',
             axes: [], frozen: [], tuning: {_TUNING} }},
  }};
"""


def test_rendering_the_cards_populates_the_drag_lookup_per_camera():
    """THE regression test — an unpopulated lookup makes the drag inert."""
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        console.log(JSON.stringify({{
          a: (S.netzState.tuneAxes.cam_a || []).length,
          b: (S.netzState.tuneAxes.cam_b || []).length,
          keys: (S.netzState.tuneAxes.cam_a || []).map((x) => x.key),
        }}));
        """
    )
    assert out["a"] == 10, "cam_a's axes never populated — its vertex drags bail out"
    assert out["b"] == 10, "cam_b's axes never populated — its vertex drags bail out"
    assert "frame_interval_ms" in out["keys"]


def test_the_lookup_the_drag_actually_performs_resolves():
    """Mirrors `_tune_drag.js`'s `axisFor(camId, key)` exactly."""
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        const ax = S.axisFor('cam_b', 'motion_sensitivity');
        console.log(JSON.stringify({{ ok: !!ax, e: ax ? ax.E : null }}));
        """
    )
    assert out["ok"] is True
    # motion_sensitivity 0.5 on a 0.1-1.0 non-inverted scale ~= E 44.
    assert out["e"] == pytest.approx(44, abs=1)


def test_a_staged_drag_on_one_camera_does_not_touch_the_other():
    """THE multi-camera invariant. A flat (un-keyed) staging map would
    make this fail by showing cam_a's dragged value on cam_b's net."""
    out = _js(
        f"""
        {_SETUP}
        S.stageValue('cam_b', 'roi_mode', '3x3');
        cards.renderCards(host);
        const b = S.axisFor('cam_b', 'roi_mode');
        const a = S.axisFor('cam_a', 'roi_mode');
        console.log(JSON.stringify({{
          bRaw: b ? b.raw : null, aRaw: a ? a.raw : null,
          bCount: S.stagedCountFor('cam_b'), aCount: S.stagedCountFor('cam_a'),
        }}));
        """
    )
    assert out["bRaw"] == "3x3", "the dragged camera does not show its own staged value"
    assert out["aRaw"] == "off", "the OTHER camera picked up a value dragged on cam_b"
    assert out["bCount"] == 1
    assert out["aCount"] == 0, "staging leaked across cameras"


def test_discarding_one_camera_leaves_the_others_staged():
    out = _js(
        f"""
        {_SETUP}
        S.stageValue('cam_a', 'roi_mode', '2x2');
        S.stageValue('cam_b', 'roi_mode', '3x3');
        S.clearStagedFor('cam_a');
        console.log(JSON.stringify({{
          a: S.stagedCountFor('cam_a'), b: S.stagedCountFor('cam_b'),
        }}));
        """
    )
    assert out["a"] == 0
    assert out["b"] == 1, "discarding one camera wiped another camera's staged edits"


def test_each_card_carries_its_camera_id_in_the_dom():
    """The write paths read `card.dataset.cam` instead of a module-level
    "current camera". If the attribute stops being emitted, every write
    silently loses its target."""
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        const html = String(host.innerHTML);
        console.log(JSON.stringify({{
          a: html.includes('data-cam="cam_a"'),
          b: html.includes('data-cam="cam_b"'),
        }}));
        """
    )
    assert out["a"] is True
    assert out["b"] is True
