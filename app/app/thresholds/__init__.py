"""THR-1/THR-2 · the ONE place where the threshold ladder is resolved,
and the only place that proposes a change to it.

Four independent gates decide whether a sighting ever reaches the user,
and until THR-1 every one of them was read at its own call site with its
own fallback chain:

    detect  — raw model floor the detector is asked for
              (``tracker_core._consts.TRACK_FLOOR_SCORE``, 0.20)
    spawn   — minimum confidence to START a track / feed the
              confirmation window (``label_thresholds``, 0.45-0.55)
    confirm — N-of-M sliding window (``confirmation_window``)
    push    — minimum confidence for a Telegram push
              (``telegram.push.labels[*].threshold``, 0.80-0.90)

Reading them separately is how the shipped config ended up with a dead
zone: ``person`` confirms at 0.45 but pushes at 0.85, so every sighting
between the two is recorded and silently never sent. ``resolve_effective``
puts all four side by side for one camera and one label, and reports for
each value WHERE it came from — so a diagnostic (DIAG-2) or the UI can
show the ladder without re-implementing the lookup order.

Precedence — highest wins, and it is the same for every field:

    camera  > adapted > global > default

* ``camera``  — the operator set this by hand on THIS camera.
* ``adapted`` — the value the nightly learner last applied. It sits
  BELOW the manual layer on purpose: an automatic adaptation must never
  be able to silently overwrite a number the operator set by hand, and
  that is exactly the precedence the net's "a drag pins the axis" rule
  needs. It is passed in per call — ``_apply.adapted_layer`` builds it
  from ``cam["net_adapted"][label]`` — and ``recommend_push``
  deliberately never writes it.
* ``global``  — the system-wide setting in ``telegram.push``.
* ``default`` — the shipped constant.

``_calibration`` adds the advisory half: given the verdict corpus from
``detection_feedback``, propose a push threshold that separates the
alerts the user confirmed from the ones they rejected — or say, in
words, that there is not enough evidence yet. It recommends; it never
applies.

Layout:

    _ladder.py       — the four-gate resolution and its precedence
    _calibration.py  — THR-2 advisory recommendation over the corpus
    _apply.py        — NETZ · the E ↔ Schwelle mapping and its rails
    _learner.py      — the nightly run that applies a recommendation

Pure functions, no I/O, no app state. Consumers pass in the camera dict,
the ``telegram.push`` dict and the ledger rows they already hold.
"""

from __future__ import annotations

from ._calibration import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MODERATE,
    CONFIDENCE_NONE,
    MIN_TRUE_RECALL,
    PUSH_CEILING,
    PUSH_FLOOR,
    SEPARATION_CLEAN,
    SEPARATION_OVERLAP,
    SEVERITY_ALARM,
    VERDICT_HOLD,
    VERDICT_INSUFFICIENT,
    VERDICT_LOWER,
    VERDICT_RAISE,
    PushRecommendation,
    recommend_push,
)
from ._ladder import (
    CONFIRM_N_FALLBACK,
    CONFIRM_SECONDS_FALLBACK,
    SOURCE_ADAPTED,
    SOURCE_CAMERA,
    SOURCE_DEFAULT,
    SOURCE_GLOBAL,
    SOURCE_PRECEDENCE,
    EffectiveThresholds,
    resolve_effective,
)

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MODERATE",
    "CONFIDENCE_NONE",
    "CONFIRM_N_FALLBACK",
    "CONFIRM_SECONDS_FALLBACK",
    "MIN_TRUE_RECALL",
    "PUSH_CEILING",
    "PUSH_FLOOR",
    "SEPARATION_CLEAN",
    "SEPARATION_OVERLAP",
    "SEVERITY_ALARM",
    "SOURCE_ADAPTED",
    "SOURCE_CAMERA",
    "SOURCE_DEFAULT",
    "SOURCE_GLOBAL",
    "SOURCE_PRECEDENCE",
    "VERDICT_HOLD",
    "VERDICT_INSUFFICIENT",
    "VERDICT_LOWER",
    "VERDICT_RAISE",
    "EffectiveThresholds",
    "PushRecommendation",
    "recommend_push",
    "resolve_effective",
]
