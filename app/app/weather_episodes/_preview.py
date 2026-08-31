"""The card-sized sparkline's own field-picker and curve slice.

A five-line-tall card has no room for every PEAK_FIELDS axis at once, so
the sparkline draws exactly ONE — the axis this episode most exceeds ITS
OWN configured threshold by. That is the same "Leitwert" definition
``storms/_helpers.js::leadPeak`` already uses to pick the compare view's
default metric, mirrored here (Python and JS cannot share a function) so
the card's tiny curve and the rest of the archive UI agree on what "the"
metric of a storm is.

Kept separate from ``_character.py`` on purpose: which axis a card
PREVIEWS and which vocabulary entry an episode is CLASSIFIED as are
independent questions — a `mixed` storm still has a most-exceeded axis
worth drawing, and coupling the two would mean every future character
needs its own preview-field rule too.
"""

from __future__ import annotations

from ._consts import FIELD_DIRECTION, PEAK_FIELDS


def lead_field(peaks: dict, thresholds: dict | None) -> str | None:
    """The PEAK_FIELDS axis furthest past its own trigger line, or None.

    Falls back to the first axis that has ANY peak value, in
    PEAK_FIELDS order, when no threshold is available at all (a legacy
    record, or one whose triggering event carries no stamped level) —
    mirroring the frontend's own ``firstMetricWithData`` fallback so a
    card is never blank just because the thresholds were not stamped.
    """
    thr = thresholds or {}
    best_field: str | None = None
    best_ratio = -1.0
    for field in PEAK_FIELDS:
        val = (peaks or {}).get(field)
        t = thr.get(field)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0:
            continue
        if FIELD_DIRECTION.get(field) == "below":
            if val <= 0:
                continue
            ratio = t / val
        else:
            ratio = val / t
        if ratio > best_ratio:
            best_ratio, best_field = ratio, field
    if best_field:
        return best_field
    for field in PEAK_FIELDS:
        if isinstance((peaks or {}).get(field), (int, float)) and not isinstance(
            (peaks or {}).get(field), bool
        ):
            return field
    return None


def build_curve_preview(rec: dict) -> dict | None:
    """A single-field, timestamp-free curve slice sized for a card.

    ``None`` when the record has no samples to draw from, or no usable
    peak at all — a card then renders no sparkline rather than a flat
    empty line. Shaped as ``{field, values}`` — plain numbers, no
    per-sample dict — so the payload stays tiny even summed across an
    archive that never rolls; the frontend wraps each value back into
    ``{values: {field: v}}`` before handing it to ``buildLinePath``.
    """
    samples = rec.get("samples")
    if not samples:
        return None
    field = lead_field(rec.get("peaks") or {}, rec.get("thresholds") or {})
    if not field:
        return None
    values = [(s.get("values") or {}).get(field) if isinstance(s, dict) else None for s in samples]
    if not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return None
    return {"field": field, "values": values}
