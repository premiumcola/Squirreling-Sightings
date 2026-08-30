"""`netz/_settings_axes.js` — E-normalization for the Erkennungsprofil's PRIMARY
axes (camera-wide settings, not per-class confidence).

Unlike the confidence axes (_mapping.js, mirrored against the Python
threshold math), these have no server-side counterpart to mirror — the
risk here is purely internal: an off-by-one in the step index, a wrong
`invert` direction, or a round-trip (raw → E → raw) that doesn't land
back on a value the backend's own range-validator accepts.
"""

from __future__ import annotations

import json

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_IMPORT = "const mod = await import(JS + '/netz/_settings_axes.js');"


def test_every_backend_field_has_a_spec():
    out = _js(
        f"""
        {_IMPORT}
        console.log(JSON.stringify(mod.TUNE_AXIS_ORDER.every(k => k in mod.TUNE_SPECS)));
        """
    )
    assert out is True


@pytest.mark.parametrize(
    "key,raw,expected_e",
    [
        ("frame_interval_ms", 100, 100),  # shortest interval = most vigilant = outer
        ("frame_interval_ms", 2000, 0),  # longest interval = most sparing = inner
        ("frame_interval_ms", 350, pytest.approx(87, abs=1)),
        ("motion_sensitivity", 0.1, 0),
        ("motion_sensitivity", 1.0, 100),
        ("track_iou_match_threshold", 0, 100),  # 0 = "use system default" = outer sentinel
        ("track_iou_match_threshold", 0.95, 0),
        ("roi_mode", "off", 0),
        ("roi_mode", "3x3", 100),
        ("roi_mode", "2x2", pytest.approx(66, abs=1)),
        ("post_motion_tail_s", 0, 0),
        ("post_motion_tail_s", 15, 100),
    ],
)
def test_tune_e_maps_raw_to_the_right_end(key, raw, expected_e):
    out = _js(
        f"""
        {_IMPORT}
        const spec = mod.TUNE_SPECS[{json.dumps(key)}];
        console.log(JSON.stringify(mod.tuneE(spec, {json.dumps(raw)})));
        """
    )
    assert out == expected_e


def test_roi_mode_round_trips_every_step_exactly():
    out = _js(
        f"""
        {_IMPORT}
        const spec = mod.TUNE_SPECS['roi_mode'];
        const results = spec.steps.map(step => {{
          const e = mod.tuneE(spec, step);
          return mod.tuneRawFromE(spec, e);
        }});
        console.log(JSON.stringify(results));
        """
    )
    assert out == ["off", "roi", "2x2", "3x3"]


def test_post_motion_tail_round_trips_every_step_exactly():
    out = _js(
        f"""
        {_IMPORT}
        const spec = mod.TUNE_SPECS['post_motion_tail_s'];
        const results = spec.steps.map(step => {{
          const e = mod.tuneE(spec, step);
          return mod.tuneRawFromE(spec, e);
        }});
        console.log(JSON.stringify(results));
        """
    )
    assert out == [0, 3, 5, 8, 10, 15]


def test_frame_interval_e_from_raw_from_e_stays_within_a_50ms_step():
    """Linear round-trip won't be bit-exact (E is an integer 0-100 over
    a 1900-wide range), but it must land within one snap-step of the
    original — not silently drift to a different setting."""
    out = _js(
        f"""
        {_IMPORT}
        const spec = mod.TUNE_SPECS['frame_interval_ms'];
        const original = 500;
        const e = mod.tuneE(spec, original);
        const back = mod.tuneRawFromE(spec, e);
        console.log(JSON.stringify({{back, diff: Math.abs(back - original)}}));
        """
    )
    assert out["diff"] <= 50


def test_default_values_report_werk_provenance():
    out = _js(
        f"""
        {_IMPORT}
        const axes = mod.buildTuneAxes({{}});
        console.log(JSON.stringify(axes.map(a => a.provenance)));
        """
    )
    assert out == ["werk"] * 10


def test_a_changed_value_reports_manuell_provenance_only_for_itself():
    out = _js(
        f"""
        {_IMPORT}
        const axes = mod.buildTuneAxes({{motion_sensitivity: 0.9}});
        console.log(JSON.stringify(Object.fromEntries(axes.map(a => [a.key, a.provenance]))));
        """
    )
    assert out["motion_sensitivity"] == "manuell"
    assert out["frame_interval_ms"] == "werk"
    assert out["roi_mode"] == "werk"


def test_ghost_filter_is_not_one_of_the_eight_axes():
    """L07's ghost-track filter is a plain boolean toggle beside the
    chart, not a spoke — a bool has no continuum to drag along."""
    out = _js(f"{_IMPORT}\nconsole.log(JSON.stringify(mod.TUNE_AXIS_ORDER));")
    assert "track_filter_ghosts" not in out
    assert len(out) == 10
