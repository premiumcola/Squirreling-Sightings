"""The single comparable number behind "wie krass war welches Gewitter".

Formula
-------
Each measured axis is normalised against a reference value — the level
at which that axis alone is as bad as this scale goes::

    a_i = clamp(peak_i / ref_i, 0, 1)

Reference values (an axis reaching this alone scores intensity 1.0):

    lightning_potential   3000 J/kg    icon-d2 extreme convective energy
    precipitation           20 mm/h    cloudburst
    snowfall                 5 cm/h    heavy snowfall
    wind_gusts_10m         120 km/h    Beaufort 12 (hurricane force, 118)
    precipitation_mm        40 mm      episode total, not a peak

The first three are the scales the LIVE detectors already use for their
severity output (``_detection.py``: ``lp / 3000.0``, ``scale=20.0``,
``scale=5.0``), so the archive and the alert path agree on what "bad"
means. Wind and the episode total have no detector counterpart; their
references come from the Beaufort scale and from what a single-cell
storm can realistically dump on one location.

The axes combine as *dominant axis, partially corroborated*::

    top       = max(a_i)
    rest      = the remaining axes with data
    intensity = top + 0.5 * (1 - top) * mean(rest)

Read it as: a storm is at least as intense as its worst single aspect,
and being bad on several axes at once closes half the remaining distance
to 1.0, in proportion to how bad the other axes were. Properties that
make it usable as a sort key:

* bounded in [0, 1] without clamping — ``mean(rest) <= 1`` gives at most
  ``top + 0.5 * (1 - top)``;
* monotone in every axis, so more lightning never lowers the score;
* a single maxed-out axis still reaches 1.0, so a pure-lightning storm
  is not penalised for having brought no rain;
* an axis with no data is skipped rather than counted as zero — a
  missing wind reading must not make a storm look milder.

Deliberately arithmetic and not a learned model: the scale has to stay
explainable years later, when comparing a 2026 storm against a 2031 one
is the whole point of the archive.
"""

from __future__ import annotations

from ._consts import INTENSITY_REFERENCE, INTENSITY_TOTAL_REFERENCE


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def axis_scores(peaks: dict, totals: dict | None = None) -> dict:
    """Per-axis normalised scores in 0..1, skipping axes with no data."""
    out: dict = {}
    for field, ref in INTENSITY_REFERENCE.items():
        val = (peaks or {}).get(field)
        if not isinstance(val, (int, float)) or not ref:
            continue
        out[field] = round(_clamp01(float(val) / float(ref)), 6)
    for field, ref in INTENSITY_TOTAL_REFERENCE.items():
        val = (totals or {}).get(field)
        if not isinstance(val, (int, float)) or not ref:
            continue
        out[field] = round(_clamp01(float(val) / float(ref)), 6)
    return out


def intensity_score(peaks: dict, totals: dict | None = None) -> float:
    """Combine the axis scores into one comparable 0..1 number.

    See the module docstring for the formula and its reference values.
    Returns 0.0 when no axis carried usable data.
    """
    scores = sorted(axis_scores(peaks, totals).values(), reverse=True)
    if not scores:
        return 0.0
    top = scores[0]
    rest = scores[1:]
    if not rest:
        return round(top, 3)
    mean_rest = sum(rest) / len(rest)
    return round(top + 0.5 * (1.0 - top) * mean_rest, 3)


def normalised(field: str, value) -> float:
    """One axis on its own, 0..1. Used to pick the peak sample."""
    ref = INTENSITY_REFERENCE.get(field)
    if not ref or not isinstance(value, (int, float)):
        return 0.0
    return _clamp01(float(value) / float(ref))
