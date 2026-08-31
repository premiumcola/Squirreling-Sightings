"""Turn one detected segment into the archive record.

The record is deliberately self-contained: peaks, totals, the score and
the full curve slice all live inside it, so a comparison across years
never has to re-read a history window that has long since rolled out of
the 30-day buffer.
"""

from __future__ import annotations

from datetime import timedelta

from ._character import classify_character
from ._consts import FIELD_DIRECTION, MAX_INTEGRATION_GAP_MIN, PEAK_FIELDS
from ._intensity import intensity_score
from ._segment import dominant_event, sample_strength


def _slice_bounds(samples: list, seg, pre_min: float, post_min: float) -> tuple:
    """Index range covering the episode plus its pre/post margins."""
    first_ts = samples[seg.start_i].ts - timedelta(minutes=max(0.0, float(pre_min)))
    last_ts = samples[seg.end_i].ts + timedelta(minutes=max(0.0, float(post_min)))
    lo = seg.start_i
    while lo > 0 and samples[lo - 1].ts >= first_ts:
        lo -= 1
    hi = seg.end_i
    while hi + 1 < len(samples) and samples[hi + 1].ts <= last_ts:
        hi += 1
    return lo, hi


def worse(field: str, value: float, current: float) -> bool:
    """True when ``value`` sits further on the alarm side than ``current``.

    Every peak metric but one is "higher is worse". ``visibility`` is
    inverted — fog is configured as a ceiling (``vis_max_m``) and a LOW
    reading is the alarm — so its peak is the episode's MINIMUM.
    """
    if FIELD_DIRECTION.get(field) == "below":
        return value < current
    return value > current


def _peaks(samples: list, seg) -> dict:
    """Worst reading per peak metric over the episode (margins excluded)."""
    out: dict = {}
    for i in range(seg.start_i, seg.end_i + 1):
        for fld in PEAK_FIELDS:
            val = samples[i].values.get(fld)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            val = float(val)
            if fld not in out or worse(fld, val, out[fld]):
                out[fld] = val
    return {k: round(v, 3) for k, v in out.items()}


def threshold_snapshot(thresholds: dict) -> dict:
    """The trigger lines this episode was measured against, flattened.

    Stamped onto the record because the archive outlives the settings
    that produced it: a storm compared in 2031 has to be readable
    against the thresholds that were configured when it happened, not
    whatever they are by then. Shape is the flat ``{field: level}`` map
    the weather chart already speaks (``/api/weather/history``), so the
    detail chart can pass it straight through — and unlike that payload
    it carries ``visibility``, whose trigger is configured as
    ``vis_max_m`` rather than ``threshold``.
    """
    out: dict = {}
    for fld, spec in (thresholds or {}).items():
        if not isinstance(spec, dict):
            continue
        try:
            out[fld] = float(spec["threshold"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _precipitation_total(samples: list, seg) -> float:
    """Integrate mm/h over the episode into mm.

    Each sample carries the interval since the previous one, capped at
    ``MAX_INTEGRATION_GAP_MIN`` so a poll outage contributes its cap
    instead of inventing hours of rain it never measured.
    """
    total = 0.0
    for i in range(seg.start_i, seg.end_i + 1):
        rate = samples[i].values.get("precipitation")
        if not isinstance(rate, (int, float)) or rate <= 0:
            continue
        if i > 0:
            gap_min = (samples[i].ts - samples[i - 1].ts).total_seconds() / 60.0
        elif len(samples) > 1:
            gap_min = (samples[1].ts - samples[0].ts).total_seconds() / 60.0
        else:
            gap_min = 0.0
        gap_min = max(0.0, min(gap_min, MAX_INTEGRATION_GAP_MIN))
        total += float(rate) * (gap_min / 60.0)
    return round(total, 3)


def _peak_index(samples: list, seg, thresholds: dict) -> int:
    """Sample where the worst metric was furthest past its trigger line."""
    best_i = seg.start_i
    best = -1.0
    for i in range(seg.start_i, seg.end_i + 1):
        strength = sample_strength(samples[i].values, thresholds)
        if strength > best:
            best = strength
            best_i = i
    return best_i


def build_record(samples: list, seg, thresholds: dict, *, pre_min, post_min) -> dict:
    """Assemble the full episode record for one segment."""
    started = samples[seg.start_i]
    ended = samples[seg.end_i]
    auto_class = dominant_event(seg.events)
    peaks = _peaks(samples, seg)
    totals = {"precipitation_mm": _precipitation_total(samples, seg)}
    lo, hi = _slice_bounds(samples, seg, pre_min, post_min)
    duration_min = int(round((ended.ts - started.ts).total_seconds() / 60.0))
    thr_snapshot = threshold_snapshot(thresholds)
    slice_samples = [
        {"ts": samples[i].iso, "values": dict(samples[i].values)} for i in range(lo, hi + 1)
    ]
    return {
        "id": "{}_{}".format(started.iso, auto_class),
        "started_at": started.iso,
        "peak_at": samples[_peak_index(samples, seg, thresholds)].iso,
        "ended_at": ended.iso,
        "duration_min": duration_min,
        "auto_class": auto_class,
        "auto_events": list(seg.events),
        "user_class": None,
        "user_name": None,
        "user_note": None,
        "peaks": peaks,
        "totals": totals,
        "thresholds": thr_snapshot,
        "intensity": intensity_score(peaks, totals),
        # The curve's own SHAPE — composition + sequence, alongside
        # (never instead of) auto_class. See _character.py.
        "character": classify_character(slice_samples, peaks, totals, thr_snapshot),
        "pre_min": int(pre_min),
        "post_min": int(post_min),
        "sample_count": hi - lo + 1,
        "samples": slice_samples,
    }
