"""weather/_manual-event-save.js's default-category guess.

The operator explicitly asked for their OWN input here, not automatic
pattern recognition (see the German refinement this feature was built
from) — this heuristic only picks a starting point among the four
fields with an unambiguous 1:1 category mapping (precipitation,
snowfall, lightning_potential, visibility); the operator can always
override it. Runs the real module under node because a wrong pick here
silently mis-categorises a save the operator never reviewed.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_SAMPLE = """
function sample(vals) {{
  return {{ ts: '2026-08-29T12:00:00', values: {{
    precipitation: null, snowfall: null, lightning_potential: null,
    visibility: null, wind_gusts_10m: null, cloud_cover: null,
    sun_altitude: null, ...vals }} }};
}}
{body}
"""


def test_a_precipitation_swing_defaults_to_heavy_rain():
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [sample({ precipitation: 0 }), sample({ precipitation: 12 })];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] == "heavy_rain"


def test_a_lightning_swing_defaults_to_thunder():
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [
          sample({ lightning_potential: 0, precipitation: 0.5 }),
          sample({ lightning_potential: 1.2, precipitation: 0.6 }),
        ];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] == "thunder"


def test_the_biggest_relative_swing_wins_not_the_biggest_absolute_number():
    """visibility swings from 8000 to 3000 (5000 m, exactly its own
    reference span — a full swing); precipitation swings 0→1 mm/h (a
    fifth of its 5 mm/h span) — visibility must win despite the smaller
    raw sample values."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [
          sample({ visibility: 8000, precipitation: 0 }),
          sample({ visibility: 3000, precipitation: 1 }),
        ];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] == "fog"


def test_only_unmapped_fields_moving_yields_no_default():
    """wind_gusts_10m and cloud_cover have no 1:1 category — the operator
    must pick one themselves rather than get a guess that isn't real."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [
          sample({ wind_gusts_10m: 10, cloud_cover: 20 }),
          sample({ wind_gusts_10m: 60, cloud_cover: 90 }),
        ];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] is None


def test_an_empty_range_yields_no_default():
    out = _js(
        """
        const mod = await import(JS + '/weather/_manual-event-save.js');
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory([]) }));
        """
    )
    assert out["category"] is None
