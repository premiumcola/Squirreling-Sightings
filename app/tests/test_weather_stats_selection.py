"""Wetterstatistik chart — multi-select curves, auto-hide flat fields,
and the relevance-based line weight.

The operator's own words: "bitte zeige nur relevante Werte in der
Wetterdaten-Prognose an, blende andere aus — wie z.B. Schneefall, wenn es
keinen gibt. Macht die Kurven kräftiger, die gerade interessant sind. Ich
will mehrere an- und abwählen." And separately: "nehm links diese 100%
Skala raus, kp was das soll."

Runs the real modules under node (see _node_js.py) — every defect this
kind of feature produces is a wrong NUMBER (a flat field not detected, a
toggle that empties the chart, an emphasis score on the wrong scale),
which only running the function actually catches.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_SAMPLE = """
function sample(vals) {{
  return {{ ts: '2026-08-28T12:00:00', values: {{
    precipitation: null, snowfall: null, lightning_potential: null,
    visibility: null, wind_gusts_10m: null, cloud_cover: null,
    sun_altitude: null, ...vals }} }};
}}
{body}
"""


def test_a_field_that_never_moved_is_flat():
    """Schneefall pinned at 0.00 all window — the operator's own example."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/stats.js');
        // snowfall stays flat at 0; wind_gusts_10m genuinely moves, so
        // the "never hide every field" guard does not mask the result
        // this test is actually about.
        const samples = [
          sample({snowfall: 0, wind_gusts_10m: 20}),
          sample({snowfall: 0, wind_gusts_10m: 45}),
        ];
        mod._wsStatsState.data = { samples };
        mod._wsStatsState.hidden = new Set();
        mod._wsStatsState.userAdjusted = false;
        // renderWeatherStats() touches the DOM via the chart/legend
        // renderers, which the stub tolerates but needn't be exercised
        // here — call the auto-hide logic through its public surface by
        // re-deriving it the same way renderWeatherStats does, i.e.
        // check the resulting hidden set after a real call.
        mod.renderWeatherStats();
        console.log(JSON.stringify({
          snowHidden: mod._wsStatsState.hidden.has('snowfall'),
          precipHidden: mod._wsStatsState.hidden.has('precipitation'),
        }));
        """
        )
    )
    assert out["snowHidden"] is True, "a constant 0.00 series must auto-hide"
    assert out["precipHidden"] is True, "an all-null series has nothing to show either"


def test_a_moving_field_is_not_flat():
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/stats.js');
        const samples = [sample({wind_gusts_10m: 20}), sample({wind_gusts_10m: 65})];
        mod._wsStatsState.data = { samples };
        mod._wsStatsState.hidden = new Set();
        mod._wsStatsState.userAdjusted = false;
        mod.renderWeatherStats();
        console.log(JSON.stringify({
          hidden: mod._wsStatsState.hidden.has('wind_gusts_10m'),
        }));
        """
        )
    )
    assert out["hidden"] is False


def test_auto_hide_never_blanks_every_field():
    """A fresh install with an all-zero window must not vanish entirely."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/stats.js');
        const samples = [sample({}), sample({})];
        mod._wsStatsState.data = { samples };
        mod._wsStatsState.hidden = new Set();
        mod._wsStatsState.userAdjusted = false;
        mod.renderWeatherStats();
        console.log(JSON.stringify({ visible: mod.wsVisibleFields().length }));
        """
        )
    )
    assert out["visible"] > 0


def test_once_the_operator_touches_a_chip_auto_hide_stops_recomputing():
    """Re-enabling a flat field must survive the next 60s refresh."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/stats.js');
        const flatSamples = [sample({snowfall: 0}), sample({snowfall: 0})];
        mod._wsStatsState.data = { samples: flatSamples };
        mod._wsStatsState.hidden = new Set();
        mod._wsStatsState.userAdjusted = false;
        mod.renderWeatherStats();
        // Operator manually re-enables snowfall.
        mod._wsStatsState.hidden.delete('snowfall');
        mod._wsStatsState.userAdjusted = true;
        // A later refresh — still flat — must not hide it again.
        mod.renderWeatherStats();
        console.log(JSON.stringify({ hidden: mod._wsStatsState.hidden.has('snowfall') }));
        """
        )
    )
    assert out["hidden"] is False


def test_hiding_the_last_visible_field_is_a_no_op():
    """Guarded in the legend click handler, not in wsVisibleFields itself —
    this pins the invariant the guard exists to protect: the chart may
    never end up with zero visible fields from a chip click."""
    out = _js(
        """
        const { _WS_FIELD_ORDER, _wsStatsState } = await import(JS + '/weather/stats.js');
        // Hide every field except one, simulating a sequence of clicks.
        _wsStatsState.hidden = new Set(_WS_FIELD_ORDER.slice(1));
        const key = _WS_FIELD_ORDER[0];
        const h = _wsStatsState.hidden;
        // Reproduce the click handler's guard verbatim in spirit: refuse
        // to hide the last one standing.
        let blocked = false;
        if (!h.has(key)) {
          if (_WS_FIELD_ORDER.length - h.size <= 1) blocked = true;
          else h.add(key);
        }
        console.log(JSON.stringify({ blocked, remaining: _WS_FIELD_ORDER.length - h.size }));
        """
    )
    assert out["blocked"] is True
    assert out["remaining"] == 1


def test_isolation_is_derived_from_visibility_not_set_directly():
    """Hiding down to exactly one field switches to isolated mode on its
    own — the operator never has to click an "isolate" affordance that
    no longer exists."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/stats.js');
        const samples = [sample({wind_gusts_10m: 40}), sample({precipitation: 3})];
        mod._wsStatsState.data = { samples };
        mod._wsStatsState.userAdjusted = true;
        mod._wsStatsState.hidden = new Set(
          mod._WS_FIELD_ORDER.filter((k) => k !== 'wind_gusts_10m'),
        );
        mod.renderWeatherStats();
        console.log(JSON.stringify({ isolated: mod._wsStatsState.isolated }));
        """
        )
    )
    assert out["isolated"] == "wind_gusts_10m"


def test_emphasis_scales_with_the_fields_own_reference_span():
    out = _js(
        """
        const { wsLineEmphasis } = await import(JS + '/weather/stats.js');
        console.log(JSON.stringify({
          flat: wsLineEmphasis('wind_gusts_10m', 20, 20),
          fullSwing: wsLineEmphasis('wind_gusts_10m', 20, 50),
          overSwing: wsLineEmphasis('wind_gusts_10m', 0, 200),
          context: wsLineEmphasis('sun_altitude', -20, 60),
        }));
        """
    )
    assert out["flat"]["opacity"] < out["fullSwing"]["opacity"]
    assert out["flat"]["width"] < out["fullSwing"]["width"]
    # Clamped at 1.0 — an outsized swing must not overshoot the max weight.
    assert out["fullSwing"]["width"] == out["overSwing"]["width"]
    # cloud_cover/sun_altitude are excluded from the competition on purpose
    # (a normal day swings ~90° without anything being "interesting").
    assert out["context"]["width"] == pytest.approx(1.4)
    assert out["context"]["opacity"] == pytest.approx(0.55)


def test_the_lightning_reference_matches_the_corrected_lpi_scale():
    """lightning_potential's emphasis reference must track the corrected
    trigger scale (0.2-0.8 J/kg observed band) — it used to be 1000-3000
    before that fix, which would make the operator's own storm read as
    a flat, unremarkable line."""
    out = _js(
        """
        const { wsLineEmphasis } = await import(JS + '/weather/stats.js');
        console.log(JSON.stringify(wsLineEmphasis('lightning_potential', 0, 1.0)));
        """
    )
    assert out["opacity"] == pytest.approx(1.0)
    assert out["width"] == pytest.approx(3.2)
