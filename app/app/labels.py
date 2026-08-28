"""The one label vocabulary.

Three places used to keep their own list of "which labels are objects":
``media_index._visible.OBJECT_LABELS`` (six entries), the colour map
inside ``EventStore.stats_range`` (eleven, including fox / hedgehog /
marten) and ``first_since._BUILTIN_THRESHOLDS_HOURS`` (ten). A fox event
therefore had a threshold, a colour and a tile — but no badge: it fell
out of ``_primary_label`` and out of ``label_counts``, so the Mediathek
showed a chip row that did not add up to the archive it was describing.

Everything that has to answer "is this an object label" now imports from
here. The JS mirror is ``core/class-colors.js`` + ``core/icons.js``.
"""

from __future__ import annotations

#: Every label the detector cascade can put on an event. Coral classes
#: first (``detectors/_coral.py`` label space), then the wildlife
#: cascade's categories (``detectors/_wildlife_rules.py``).
OBJECT_LABELS: tuple[str, ...] = (
    "person",
    "cat",
    "bird",
    "car",
    "dog",
    "squirrel",
    "fox",
    "hedgehog",
    "marten",
    "deer",
)

#: The residual bucket. Every visible event lands under exactly one of
#: ``OBJECT_LABELS`` or this, which is what makes the chip row sum to the
#: archive size.
MOTION_LABEL = "motion"

#: Labels that may appear as a counted bucket.
COUNTED_LABELS: frozenset[str] = frozenset(OBJECT_LABELS) | {MOTION_LABEL}

#: Chart / chip colour per label. ``other`` is the fallback for anything
#: outside the vocabulary — a label from a model we do not know yet.
LABEL_COLORS: dict[str, str] = {
    MOTION_LABEL: "#36a2ff",
    "person": "#ff6b6b",
    "cat": "#9b8cff",
    "dog": "#7c2d12",
    "bird": "#62d26f",
    "squirrel": "#7c4a1f",
    "fox": "#ff7a1a",
    "hedgehog": "#a67c52",
    "marten": "#7c5cff",
    "deer": "#8a6a3f",
    "car": "#00c2ff",
    "timelapse": "#a855f7",
    "other": "#64748b",
}


def label_color(label: str) -> str:
    """Colour for ``label``, falling back to the neutral ``other`` grey."""
    return LABEL_COLORS.get(label, LABEL_COLORS["other"])


def primary_label(labels) -> str:
    """The single bucket an event is counted under.

    The first object label wins; everything else — an empty list, a bare
    ``["motion"]``, or a label this build has never heard of — falls back
    to ``motion``. That final fallback is load-bearing: without it a
    ``["fox"]`` event was counted under no bucket at all and vanished
    from every badge while still rendering a tile.
    """
    for label in labels or ():
        if label in OBJECT_LABELS:
            return label
    return MOTION_LABEL
