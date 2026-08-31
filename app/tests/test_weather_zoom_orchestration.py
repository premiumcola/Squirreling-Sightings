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


def test_range_select_reaches_the_merged_grid_via_the_reload_bridge_not_a_direct_import():
    """Stage 6 (the Mediathek + Wetter-Ereignisse section merge) retired
    weather/sightings.js's own grid painter and window.renderWeatherSightings
    with it. Stage 7 wires the chart's drag-zoom into the merged library
    grid (library/page.js) — but through window.reloadLibraryPage, the
    SAME global-name bridge every other mutation in the merged section
    already uses (delete, restore, rescan, manual-event save), never a
    direct import of library/ or the retired sightings.js — that would
    reopen the cross-import cycle weather/_zoom.js's own header exists to
    avoid. Supersedes this file's Stage-6-era pin, which predated the
    bridge call this asserts is now present."""
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
    assert "window.reloadLibraryPage" in src
    assert "from './sightings.js'" not in src
    assert "from '../library" not in src


# ── Stage 7: the reload bridge itself fires, exactly once per transition ──


def test_range_select_triggers_exactly_one_grid_reload():
    out = _js(
        """
        const stats = await import(JS + '/weather/stats.js');
        let calls = 0;
        window.reloadLibraryPage = () => { calls += 1; };
        stats.onWeatherChartRangeSelect('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        console.log(JSON.stringify({ calls }));
        """
    )
    assert out["calls"] == 1


def test_reset_triggers_exactly_one_grid_reload():
    out = _js(
        """
        const stats = await import(JS + '/weather/stats.js');
        stats.onWeatherChartRangeSelect('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        let calls = 0;
        window.reloadLibraryPage = () => { calls += 1; };
        stats.resetWeatherChartZoom();
        console.log(JSON.stringify({ calls }));
        """
    )
    assert out["calls"] == 1


def test_reload_bridge_is_a_no_op_when_the_grid_is_not_mounted():
    """`window.reloadLibraryPage` is only defined once library/page.js has
    run (it is `undefined` on any other page rendering the chart) — the
    optional-call must not throw."""
    out = _js(
        """
        const stats = await import(JS + '/weather/stats.js');
        stats.onWeatherChartRangeSelect('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        stats.resetWeatherChartZoom();
        console.log(JSON.stringify({ ok: true }));
        """
    )
    assert out["ok"] is True
