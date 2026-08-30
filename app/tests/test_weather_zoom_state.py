"""weather/_zoom.js — the Wetterdaten-chart's drag-to-zoom shared state.

Runs the real module under node (see _node_js.py) because every defect
here is either a wrong FILTER (a sample that should/shouldn't survive
zoomedSamples/withinZoom) or an inverted range (start > end), which only
executing the function actually catches.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


def test_no_zoom_is_the_default_state():
    out = _js(
        """
        const z = await import(JS + '/weather/_zoom.js');
        console.log(JSON.stringify({
          active: z.isZoomActive(),
          range: z.getZoomRange(),
          within: z.withinZoom('2026-08-29T12:00:00'),
        }));
        """
    )
    assert out["active"] is False
    assert out["range"] is None
    assert out["within"] is True


def test_set_zoom_range_normalises_a_reversed_drag():
    """A drag from right to left must still store start <= end — the
    operator dragged backwards, the range itself did not invert."""
    out = _js(
        """
        const z = await import(JS + '/weather/_zoom.js');
        z.setZoomRange('2026-08-29T18:00:00', '2026-08-29T14:00:00');
        console.log(JSON.stringify(z.getZoomRange()));
        """
    )
    assert out == {"start": "2026-08-29T14:00:00", "end": "2026-08-29T18:00:00"}


def test_within_zoom_is_inclusive_of_both_edges():
    out = _js(
        """
        const z = await import(JS + '/weather/_zoom.js');
        z.setZoomRange('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        console.log(JSON.stringify({
          before: z.withinZoom('2026-08-29T13:59:59'),
          atStart: z.withinZoom('2026-08-29T14:00:00'),
          inside: z.withinZoom('2026-08-29T16:00:00'),
          atEnd: z.withinZoom('2026-08-29T18:00:00'),
          after: z.withinZoom('2026-08-29T18:00:01'),
        }));
        """
    )
    assert out == {
        "before": False,
        "atStart": True,
        "inside": True,
        "atEnd": True,
        "after": False,
    }


def test_within_zoom_rejects_a_missing_timestamp_while_zoomed():
    """A feed entry with no timestamp (e.g. a malformed record) must not
    survive a zoom filter just because the check short-circuited."""
    out = _js(
        """
        const z = await import(JS + '/weather/_zoom.js');
        z.setZoomRange('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        console.log(JSON.stringify({ within: z.withinZoom('') }));
        """
    )
    assert out["within"] is False


def test_zoomed_samples_filters_to_the_active_range():
    out = _js(
        """
        const z = await import(JS + '/weather/_zoom.js');
        z.setZoomRange('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        const samples = [
          { ts: '2026-08-29T12:00:00', values: {} },
          { ts: '2026-08-29T15:00:00', values: {} },
          { ts: '2026-08-29T20:00:00', values: {} },
        ];
        console.log(JSON.stringify(z.zoomedSamples(samples).map((s) => s.ts)));
        """
    )
    assert out == ["2026-08-29T15:00:00"]


def test_zoomed_samples_is_a_passthrough_without_an_active_zoom():
    out = _js(
        """
        const z = await import(JS + '/weather/_zoom.js');
        const samples = [{ ts: '2026-08-29T12:00:00', values: {} }];
        console.log(JSON.stringify(z.zoomedSamples(samples).map((s) => s.ts)));
        """
    )
    assert out == ["2026-08-29T12:00:00"]


def test_clear_zoom_range_restores_the_passthrough():
    out = _js(
        """
        const z = await import(JS + '/weather/_zoom.js');
        z.setZoomRange('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        z.clearZoomRange();
        console.log(JSON.stringify({
          active: z.isZoomActive(),
          within: z.withinZoom('2026-08-01T00:00:00'),
        }));
        """
    )
    assert out["active"] is False
    assert out["within"] is True
