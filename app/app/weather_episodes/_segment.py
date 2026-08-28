"""Cut the rolling weather history into discrete storm episodes.

Three stages, in this order:

1. **Runs** — consecutive samples on the alarm side of any configured
   threshold. A run stays open while the metrics keep crossing, and is
   closed once ``settle_min`` has passed with nothing above the line.
   That settle window is what stops a pulsing storm from fragmenting
   into six episodes.
2. **Merge** — two runs whose stored margins would overlap are one
   episode. Margins are ``pre_min`` before onset and ``post_min`` after
   the end, so the merge condition is a gap of at most
   ``pre_min + post_min`` minutes.
3. **Finalise** — a segment may only be archived once no later sample
   can still change it. Because the merge horizon is
   ``pre_min + post_min`` wide, the history has to extend at least
   ``max(settle_min, pre_min + post_min)`` minutes past the segment's
   end before the record is stable. Until then the segment is reported
   as *pending* and nothing is written; the next sweep re-derives it
   from scratch. That is what makes re-running detection over the same
   history idempotent instead of duplicating or truncating episodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..weather_service._consts import _safe_dt
from ._consts import EVENT_PRIORITY
from ._thresholds import crossed


@dataclass
class Sample:
    """One parsed history row: its timestamp and its numeric values."""

    ts: datetime
    iso: str
    values: dict


@dataclass
class Segment:
    """A contiguous storm, in indices into the parsed sample list."""

    start_i: int
    end_i: int
    events: list = field(default_factory=list)


def parse_samples(rows) -> list:
    """Parse + sort the raw history rows, dropping anything unusable.

    The history deque is already chronological, but a restart that
    reloaded a hand-edited file is not worth trusting: one row out of
    order would otherwise split a storm in half.
    """
    out: list = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        iso = row.get("ts")
        values = row.get("values")
        if not isinstance(iso, str) or not isinstance(values, dict):
            continue
        ts = _safe_dt(iso)
        if ts is None:
            continue
        out.append(Sample(ts=ts, iso=iso, values=values))
    out.sort(key=lambda s: s.ts)
    return out


def active_events(values: dict, thresholds: dict) -> list:
    """Event types crossing their threshold in this one sample."""
    hits = []
    for fld, spec in thresholds.items():
        if crossed(values.get(fld), spec):
            evt = spec.get("event")
            if evt and evt not in hits:
                hits.append(evt)
    return hits


def sample_strength(values: dict, thresholds: dict) -> float:
    """How far past its own trigger line the worst metric is, as a ratio.

    Threshold-relative rather than absolute so it stays comparable
    across events with wildly different units, and defined for the
    inverted fog axis too (where a LOW visibility is the alarm).
    """
    best = 0.0
    for fld, spec in thresholds.items():
        val = values.get(fld)
        if not crossed(val, spec):
            continue
        thr = float(spec["threshold"])
        val = float(val)
        if spec.get("direction") == "below":
            ratio = thr / val if val > 0 else float(len(thresholds) + 1)
        else:
            ratio = val / thr if thr > 0 else 1.0
        best = max(best, ratio)
    return best


def build_runs(samples: list, thresholds: dict, settle_min: float) -> list:
    """Stage 1 — consecutive above-threshold samples, settle-terminated."""
    runs: list = []
    settle = timedelta(minutes=max(0.0, float(settle_min)))
    start_i = None
    last_active_i = None
    events: list = []
    for i, s in enumerate(samples):
        hits = active_events(s.values, thresholds)
        if hits:
            if start_i is None:
                start_i = i
                events = []
            last_active_i = i
            for evt in hits:
                if evt not in events:
                    events.append(evt)
            continue
        if start_i is None:
            continue
        if s.ts - samples[last_active_i].ts > settle:
            runs.append(Segment(start_i=start_i, end_i=last_active_i, events=list(events)))
            start_i = None
            last_active_i = None
            events = []
    if start_i is not None:
        runs.append(Segment(start_i=start_i, end_i=last_active_i, events=list(events)))
    return runs


def merge_runs(samples: list, runs: list, pre_min: float, post_min: float) -> list:
    """Stage 2 — fold runs whose pre/post margins overlap into one."""
    if not runs:
        return []
    horizon = timedelta(minutes=max(0.0, float(pre_min)) + max(0.0, float(post_min)))
    merged = [runs[0]]
    for run in runs[1:]:
        prev = merged[-1]
        gap = samples[run.start_i].ts - samples[prev.end_i].ts
        if gap <= horizon:
            prev.end_i = run.end_i
            for evt in run.events:
                if evt not in prev.events:
                    prev.events.append(evt)
        else:
            merged.append(run)
    return merged


def quiet_window_min(settle_min: float, pre_min: float, post_min: float) -> float:
    """Minutes of history that must follow a segment before it is stable."""
    return max(float(settle_min), float(pre_min) + float(post_min))


def segment_history(rows, thresholds: dict, *, pre_min, post_min, settle_min) -> tuple:
    """Full pipeline. Returns ``(samples, finalised, pending)``.

    ``pending`` is the trailing segment the history cannot yet close —
    at most one, since only the last segment can touch the tail.
    """
    samples = parse_samples(rows)
    if not samples or not thresholds:
        return samples, [], None
    runs = build_runs(samples, thresholds, settle_min)
    segments = merge_runs(samples, runs, pre_min, post_min)
    if not segments:
        return samples, [], None
    quiet = timedelta(minutes=quiet_window_min(settle_min, pre_min, post_min))
    last_ts = samples[-1].ts
    final: list = []
    pending = None
    for seg in segments:
        if last_ts - samples[seg.end_i].ts >= quiet:
            final.append(seg)
        else:
            pending = seg
    return samples, final, pending


def dominant_event(events: list) -> str:
    """auto_class for a segment — fixed priority, never a magnitude race."""
    for evt in EVENT_PRIORITY:
        if evt in events:
            return evt
    return events[0] if events else "unknown"
