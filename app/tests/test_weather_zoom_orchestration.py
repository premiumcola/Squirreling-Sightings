"""weather/stats.js's zoom orchestration — onWeatherChartRangeSelect /
resetWeatherChartZoom actually flip the shared weather/_zoom.js state
they're supposed to drive.

Runs the real modules under node (see _node_js.py); the generic DOM
stub tolerates the render side-effects (proven already by
test_weather_stats_selection.py) without actually exercising them —
what this file pins is the STATE change, which the stub can't fake.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


def test_range_select_activates_the_shared_zoom_state():
    out = _js(
        """
        const stats = await import(JS + '/weather/stats.js');
        const zoom = await import(JS + '/weather/_zoom.js');
        stats.onWeatherChartRangeSelect('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        console.log(JSON.stringify({
          active: zoom.isZoomActive(),
          range: zoom.getZoomRange(),
        }));
        """
    )
    assert out["active"] is True
    assert out["range"] == {"start": "2026-08-29T14:00:00", "end": "2026-08-29T18:00:00"}


def test_reset_clears_the_shared_zoom_state():
    out = _js(
        """
        const stats = await import(JS + '/weather/stats.js');
        const zoom = await import(JS + '/weather/_zoom.js');
        stats.onWeatherChartRangeSelect('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        stats.resetWeatherChartZoom();
        console.log(JSON.stringify({ active: zoom.isZoomActive() }));
        """
    )
    assert out["active"] is False


def test_range_select_reaches_for_the_window_bridge_not_an_import():
    """sightings.js imports openManualEventView (etc.) which pulls in
    stats-chart/index.js, which already imports FROM stats.js — an
    import from stats.js back to sightings.js would close that into a
    cycle. Pin that the grid refresh instead goes through
    window.renderWeatherSightings, per the module's own docstring."""
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[2]
        / "app"
        / "web"
        / "static"
        / "js"
        / "weather"
        / "stats.js"
    ).read_text(encoding="utf-8")
    assert "window.renderWeatherSightings" in src
    assert "from './sightings.js'" not in src
