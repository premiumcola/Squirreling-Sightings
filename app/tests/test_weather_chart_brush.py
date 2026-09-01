"""weather/stats-chart/_hover.js's additive drag-to-zoom (opts.onRangeSelect).

The shared node-harness DOM stub (_node_js.py) is a generic proxy that
doesn't actually record addEventListener callbacks, so it can't drive a
real pointer-event sequence. Each test here builds its own minimal fake
`wrap`/`svg`/element objects with a REAL listener registry instead —
enough surface for bindChartHover to attach to and this test to fire
synthetic pointer events through, without touching the shared stub (it
stays generic for every other node-harness test).

Every defect this feature produces is a wrong RANGE (off-by-one sample,
a reversed drag not normalised, a tap firing a zero-width "zoom") or a
regression in the opts.onRangeSelect being undefined (the storm compare
chart's own usage) — both need the real function running, not a source
grep.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

# 20 samples, 5 minutes apart — plenty of resolution for a drag over a
# 300 px-wide fake plot area (pad.l=0, cw=300, vbW=300 so clientX maps
# 1:1 onto viewBox units).
_SETUP = """
function fakeEl() {
  const listeners = {};
  return {
    _listeners: listeners,
    _fire(type, ev) { (listeners[type] || []).forEach((cb) => cb(ev)); },
    addEventListener(type, cb) { (listeners[type] = listeners[type] || []).push(cb); },
    style: {},
    hidden: false,
    innerHTML: '',
    _attrs: {},
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k] ?? null; },
    setPointerCapture() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 300, height: 200 }; },
  };
}
function makeWrap() {
  const guide = fakeEl();
  const brush = fakeEl();
  const area = fakeEl();
  const tip = fakeEl();
  const svg = {
    querySelector(sel) {
      return { '.ws-chart-hover-area': area, '.ws-chart-guide': guide, '.ws-chart-brush': brush }[sel] || null;
    },
    getBoundingClientRect() { return { left: 0, top: 0, width: 300, height: 200 }; },
  };
  const wrap = {
    querySelector(sel) { return sel === 'svg' ? svg : sel === '.ws-chart-tooltip' ? tip : null; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 300, height: 200 }; },
  };
  return { wrap, area, guide, brush, tip };
}
function samples(n = 20, stepMin = 5) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(2026, 0, 1, 0, i * stepMin, 0);
    out.push({ ts: d.toISOString().slice(0, 19), values: {} });
  }
  return out;
}
const PAD = { l: 0, t: 0 };
"""


def test_a_wide_drag_fires_range_select_with_two_distinct_sample_timestamps():
    out = _js(
        _SETUP
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area } = makeWrap();
        let result = null;
        bindChartHover(wrap, samples(), [], PAD, 300, 300, null, {
          onRangeSelect: (a, b) => { result = [a, b]; },
        });
        area._fire('pointerdown', { clientX: 10, pointerId: 1 });
        area._fire('pointermove', { clientX: 250 });
        area._fire('pointerup', { clientX: 250, pointerId: 1 });
        console.log(JSON.stringify({ result }));
        """
    )
    assert out["result"] is not None
    start, end = out["result"]
    assert start < end, "a wide left-to-right drag must yield start < end"


def test_a_reversed_drag_is_normalised_start_before_end():
    out = _js(
        _SETUP
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area } = makeWrap();
        let result = null;
        bindChartHover(wrap, samples(), [], PAD, 300, 300, null, {
          onRangeSelect: (a, b) => { result = [a, b]; },
        });
        area._fire('pointerdown', { clientX: 250, pointerId: 1 });
        area._fire('pointermove', { clientX: 10 });
        area._fire('pointerup', { clientX: 10, pointerId: 1 });
        console.log(JSON.stringify({ result }));
        """
    )
    assert out["result"] is not None
    start, end = out["result"]
    assert start < end, "dragging right-to-left must still store start < end"


def test_a_tap_below_the_drag_threshold_does_not_fire_a_zero_width_zoom():
    out = _js(
        _SETUP
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area } = makeWrap();
        let fired = false;
        bindChartHover(wrap, samples(), [], PAD, 300, 300, null, {
          onRangeSelect: () => { fired = true; },
        });
        area._fire('pointerdown', { clientX: 100, pointerId: 1 });
        area._fire('pointerup', { clientX: 103, pointerId: 1 }); // 3px — a tap, not a drag
        console.log(JSON.stringify({ fired }));
        """
    )
    assert out["fired"] is False


def test_the_brush_rect_paints_during_the_drag_and_hides_after_release():
    out = _js(
        _SETUP
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area, brush } = makeWrap();
        bindChartHover(wrap, samples(), [], PAD, 300, 300, null, { onRangeSelect: () => {} });
        area._fire('pointerdown', { clientX: 10, pointerId: 1 });
        area._fire('pointermove', { clientX: 250 });
        const duringWidth = Number(brush._attrs.width);
        const duringDisplay = brush.style.display;
        area._fire('pointerup', { clientX: 250, pointerId: 1 });
        console.log(JSON.stringify({
          duringWidth, duringDisplay, afterDisplay: brush.style.display,
        }));
        """
    )
    assert out["duringWidth"] > 0
    assert out["duringDisplay"] == ''
    assert out["afterDisplay"] == 'none'


# ── markMode: the THIRD pointer behaviour (weather/_chart-annotations.js)
# ──────────────────────────────────────────────────────────────────────
# Mutually exclusive with drag-to-zoom — a truthy opts.markMode must
# never let a drag start, regardless of onRangeSelect also being set,
# and a plain (non-mark) chart must never route a tap into onMark.
# `PAD_CH` adds the `.b` _localYOf's vbH math needs — the shared _SETUP
# above never needed it because no existing behaviour touches Y.
_PAD_CH = """
const PAD_CH = { l: 0, t: 0, b: 0 };
"""


def test_a_tap_in_mark_mode_resolves_the_nearest_sample_and_calls_on_mark():
    out = _js(
        _SETUP
        + _PAD_CH
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area } = makeWrap();
        let call = null;
        bindChartHover(wrap, samples(), [], PAD_CH, 300, 300, null, {
          markMode: true, ch: 200,
          onMark: (geo, idx, x, y) => { call = { idx, x, y }; },
        });
        area._fire('pointerdown', { clientX: 155, pointerId: 1 });
        area._fire('pointerup', { clientX: 157, clientY: 40, pointerId: 1 }); // 2px — a tap
        console.log(JSON.stringify({ call }));
        """
    )
    assert out["call"] is not None
    # x=157 on a 300px/95-minute plot resolves to ~49.7 min elapsed —
    # closest to sample 10 (50 min, 5-min cadence) than sample 9 (45 min).
    assert out["call"]["idx"] == 10


def test_mark_mode_never_starts_a_drag_even_with_on_range_select_defined():
    out = _js(
        _SETUP
        + _PAD_CH
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area, brush } = makeWrap();
        let rangeSelected = false;
        let marked = false;
        bindChartHover(wrap, samples(), [], PAD_CH, 300, 300, null, {
          markMode: true, ch: 200,
          onRangeSelect: () => { rangeSelected = true; },
          onMark: () => { marked = true; },
        });
        area._fire('pointerdown', { clientX: 10, pointerId: 1 });
        area._fire('pointermove', { clientX: 250 });
        area._fire('pointerup', { clientX: 250, clientY: 40, pointerId: 1 });
        console.log(JSON.stringify({
          rangeSelected, marked, brushTouched: 'display' in brush.style,
        }));
        """
    )
    assert out["rangeSelected"] is False, "marking must never fall through to a zoom"
    assert out["marked"] is False, "a drag past the tap threshold places no marker either"
    assert out["brushTouched"] is False, "no brush chrome paints while marking"


def test_mark_mode_ignores_a_tap_outside_the_plot_area():
    out = _js(
        _SETUP
        + _PAD_CH
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area } = makeWrap();
        let marked = false;
        bindChartHover(wrap, samples(), [], PAD_CH, 300, 300, null, {
          markMode: true, ch: 200,
          onMark: () => { marked = true; },
        });
        area._fire('pointerdown', { clientX: -50, pointerId: 1 });
        area._fire('pointerup', { clientX: -50, clientY: 40, pointerId: 1 });
        console.log(JSON.stringify({ marked }));
        """
    )
    assert out["marked"] is False


def test_mark_mode_without_ch_never_calls_on_mark():
    """`ch` (chart height) is only ever supplied by
    stats-chart/index.js's renderStatsChartInto — a caller that sets
    markMode without it (a bug, or a future caller that forgot) must
    fail closed, not throw or place a marker at a garbage y."""
    out = _js(
        _SETUP
        + _PAD_CH
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area } = makeWrap();
        let marked = false;
        bindChartHover(wrap, samples(), [], PAD_CH, 300, 300, null, {
          markMode: true, // no ch
          onMark: () => { marked = true; },
        });
        area._fire('pointerdown', { clientX: 150, pointerId: 1 });
        area._fire('pointerup', { clientX: 152, clientY: 40, pointerId: 1 });
        console.log(JSON.stringify({ marked }));
        """
    )
    assert out["marked"] is False


def test_without_mark_mode_a_tap_never_reaches_on_mark():
    """The plain hover/drag chart (every existing caller) must stay
    fully inert to `onMark` — mirrors the existing
    without-onRangeSelect regression test below for the same reason."""
    out = _js(
        _SETUP
        + _PAD_CH
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area } = makeWrap();
        let marked = false;
        bindChartHover(wrap, samples(), [], PAD_CH, 300, 300, null, {
          ch: 200, onMark: () => { marked = true; },
        });
        area._fire('pointerdown', { clientX: 150, pointerId: 1 });
        area._fire('pointerup', { clientX: 152, clientY: 40, pointerId: 1 });
        console.log(JSON.stringify({ marked }));
        """
    )
    assert out["marked"] is False


def test_without_on_range_select_a_drag_never_touches_the_brush():
    """The storm compare chart's own usage never sets onRangeSelect — a
    press+drag there must stay fully inert, matching day-one behaviour."""
    out = _js(
        _SETUP
        + """
        const { bindChartHover } = await import(JS + '/weather/stats-chart/_hover.js');
        const { wrap, area, brush } = makeWrap();
        bindChartHover(wrap, samples(), [], PAD, 300, 300, null, {});
        area._fire('pointerdown', { clientX: 10, pointerId: 1 });
        area._fire('pointermove', { clientX: 250 });
        area._fire('pointerup', { clientX: 250, pointerId: 1 });
        console.log(JSON.stringify({
          brushAttrs: brush._attrs,
          brushDisplayTouched: 'display' in brush.style,
        }));
        """
    )
    assert out["brushAttrs"] == {}
    assert out["brushDisplayTouched"] is False
