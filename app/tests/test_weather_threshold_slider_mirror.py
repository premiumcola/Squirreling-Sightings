"""HYG · the Ereignistypen sliders must be able to reach their own defaults.

`weather/stats.js` · WEATHER_THRESHOLD_HINTS gives each weather event its
slider bounds. It is a hand-maintained mirror of the backend's
`WEATHER_DEFAULTS["events"]`, and nothing checked the two agreed.

The thunder row is what that cost. `51db1fe0` moved the thunder trigger
off the CAPE scale onto LPI (default 1000.0 → 0.2 J/kg) and shipped a
migration that overwrites stored values — but it touched seven files and
none of them was JS, so the slider kept `min:0 max:3000 step:50`. The
row therefore rendered `value="0.2"` into a `step="50"` input: the thumb
snaps to 0 while the number beside it reads 0.2, and the smallest
non-zero value a drag can produce is 50 J/kg — about 60× the top of the
published thunderstorm band (0.2–0.8). One touch of that slider disables
lightning detection.

The self-heal migration cannot rescue it either. `migrate_thunder_lpi_
scale` deliberately only rewrites values at or above
`_LPI_WRONG_SCALE_MIN = 100.0` so hand-tuned LPI numbers survive — and
50 is below 100. The damage is permanent and silent.

The same drift hid a second row: `bc935af0` added the `storm` event
(wind gusts, 60 km/h) backend-only, so it has no hint at all; and
`sunset` still had a hint long after `64a74443` removed the event.

Runs the real module under node (tests/_node_js.py) and compares it to
the Python defaults, so the next backend-only change fails here instead
of on a slider.
"""

from __future__ import annotations

import pytest

from app.settings._consts import WEATHER_DEFAULTS

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON, run_js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

EVENTS = WEATHER_DEFAULTS["events"]


def _hints() -> dict[str, dict]:
    return run_js(
        """
        const { WEATHER_THRESHOLD_HINTS } = await import(JS + '/weather/stats.js');
        console.log(JSON.stringify(WEATHER_THRESHOLD_HINTS));
        """
    )


def _representable(value: float, lo: float, hi: float, step: float) -> bool:
    """Can a slider with these bounds actually land on `value`?

    Float-safe: a step of 0.05 cannot be checked with `%`.
    """
    if not (lo <= value <= hi):
        return False
    steps = (value - lo) / step
    return abs(steps - round(steps)) < 1e-9


def test_every_hint_names_an_event_that_still_exists():
    """`sunset` outlived its event by three commits."""
    stale = sorted(set(_hints()) - set(EVENTS))
    assert not stale, f"hints for events the backend no longer has: {stale}"


def test_every_hint_points_at_the_key_the_backend_actually_stores():
    """fog stores `vis_max_m`, not `threshold`. A hint naming the wrong
    key writes a value the detector never reads."""
    for evt, hint in _hints().items():
        assert hint["key"] in EVENTS[evt], (
            f"{evt}: slider writes '{hint['key']}' but the backend default "
            f"has {sorted(EVENTS[evt])}"
        )


def test_every_slider_can_reach_its_own_shipped_default():
    """The bug in one line: thunder's default is 0.2 and its step was 50."""
    for evt, hint in _hints().items():
        default = float(EVENTS[evt][hint["key"]])
        assert _representable(default, hint["min"], hint["max"], hint["step"]), (
            f"{evt}: default {default} is not reachable on a slider with "
            f"min={hint['min']} max={hint['max']} step={hint['step']} — "
            f"dragging it rewrites the value to something the detector "
            f"cannot fire on"
        )


def test_the_thunder_slider_stays_inside_the_lpi_index_range():
    """LPI is not CAPE. Observed thunderstorms run 0.2–0.8 J/kg and the
    episode code treats 2.0 as full intensity
    (weather_episodes/_consts.py · INTENSITY_REFERENCE). A slider whose
    top end is in the thousands is the CAPE scale wearing an LPI label.

    The upper bound also has to stay under the migration's
    `_LPI_WRONG_SCALE_MIN` (100.0): anything a drag can produce at or
    above that would be silently rewritten back to the default on the
    next boot, which is its own kind of broken."""
    from app.settings.migrations import _LPI_WRONG_SCALE_MIN

    thunder = _hints()["thunder"]
    assert thunder["unit"] == "J/kg"
    assert thunder["max"] < _LPI_WRONG_SCALE_MIN, (
        f"a drag can reach {thunder['max']}, at or above the "
        f"{_LPI_WRONG_SCALE_MIN} the migration rewrites"
    )
    # The published band must be fully selectable, ends included.
    for v in (0.2, 0.5, 0.8):
        assert _representable(v, thunder["min"], thunder["max"], thunder["step"]), v


def test_every_configurable_event_has_a_slider_row():
    """The mirror must be complete in this direction too — `storm`
    shipped backend-only and had no hint at all."""
    missing = sorted(set(EVENTS) - set(_hints()))
    assert not missing, f"backend events with no slider hint: {missing}"
