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


def test_range_select_does_not_reach_into_the_merged_grid():
    """Stage 6 (the Mediathek + Wetter-Ereignisse section merge) retired
    weather/sightings.js's own grid painter and window.renderWeatherSightings
    with it — the chart's drag-zoom now only redraws ITSELF
    (renderWeatherStats()); narrowing the merged library grid by the same
    range is explicitly a later stage (library/page.js's own header
    explains why). Pin that stats.js reaches for neither the retired
    bridge nor the merged grid's reload bridge, and stays import-cycle-
    free with respect to both sightings.js and library/page.js."""
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
    assert "window.renderWeatherSightings" not in src
    assert "window.reloadLibraryPage" not in src
    assert "from './sightings.js'" not in src
    assert "from '../library" not in src
