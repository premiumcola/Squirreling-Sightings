"""C4 · append-only ledger of alerts and the user's verdicts on them.

Everything in the lower half of the tuning board — adaptive thresholds,
targeted follow-up questions, background learning, processing user
corrections — needs one thing that did not exist: a durable record
pairing *what the detector said* with *what the user said about it*.

Two record kinds are written, joined by ``event_id``:

  ``alert``   written when an alert is CONSIDERED, above the push
              gates, carrying the camera, the primary label, its score,
              the threshold it had to clear and every detection in the
              frame.
  ``verdict`` written when the user judges that event — right / wrong,
              and optionally what it really was.

A third kind, ``census``, is written by compaction alone: the running
count of alerts an automatic sweep threw away, per (camera, label). It
exists so the answer rate can be computed against the alerts that ever
happened rather than the ones still on disk.

Design constraints, and why:

* **Append-only JSONL.** No read-modify-write, so concurrent writers from
  the camera threads, the Telegram callback thread and HTTP handlers
  cannot corrupt each other or lose a record to a torn write.
* **Under ``storage/_diag/``, not in the event folders.** `cleanup_old`
  deletes events by age; a corpus living beside them would dissolve
  inside the retention window. This is the durable artefact.
* **Bounded, but representative.** Compaction may delete only an
  *unjudged alert*, and evicts per (camera, label) so a rare class
  survives a flood of a common one. Judged alerts, their verdicts,
  verdicts with no alert record and records of an unknown kind are never
  deleted by the sweep. See ``_retention``.
* **Best-effort.** Any failure is swallowed and logged. A diagnostic
  write must never break a capture loop or drop a real alert.

Read side: ``corpus_stats`` rolls the whole ledger up per camera and
label and answers, per downstream use, whether there is enough evidence
to act — see ``_stats`` and the bars in ``_consts``. ``scripts/
corpus_report.py`` is the operator-facing rendering of it.

Mirrors the conventions of ``motion_samples.py``, which does the same
job for the motion gate.
"""

from __future__ import annotations

# The three retention quotas are read back off THIS module at enforcement
# time (see `_io._policy`), so patching them here — `_MAX_BYTES` has been
# the knob since C4 — actually changes behaviour.
from ._consts import (
    KIND_ALERT,
    KIND_CENSUS,
    KIND_VERDICT,
    MAX_BYTES as _MAX_BYTES,  # noqa: F401 - runtime knob, not re-exported
    MAX_RETAINED_RECORDS,
    MAX_UNJUDGED_PER_STRATUM,
    MIN_AGREEING_CORRECTIONS,
    MIN_ANSWER_RATE,
    MIN_CLASSES_FOR_CENTROID,
    MIN_EXAMPLES_PER_CLASS,
    MIN_JUDGED_FOR_VETO,
    MIN_JUDGED_PER_CLASS,
    MIN_JUDGED_PER_STRATUM,
    MIN_VETO_WRONG_RATE_LOWER,
)
from ._io import archive_path, compact_ledger, iter_records, ledger_health, ledger_path
from ._retention import select_retained
from ._stats import (
    calibration_readiness,
    centroid_readiness,
    corpus_stats,
    judged_alerts,
    resolve_stratum,
    score_summary,
    veto_readiness,
)
from ._write import record_alert, record_verdict

__all__ = [
    "KIND_ALERT",
    "KIND_CENSUS",
    "KIND_VERDICT",
    "MAX_RETAINED_RECORDS",
    "MAX_UNJUDGED_PER_STRATUM",
    "MIN_AGREEING_CORRECTIONS",
    "MIN_ANSWER_RATE",
    "MIN_CLASSES_FOR_CENTROID",
    "MIN_EXAMPLES_PER_CLASS",
    "MIN_JUDGED_FOR_VETO",
    "MIN_JUDGED_PER_CLASS",
    "MIN_JUDGED_PER_STRATUM",
    "MIN_VETO_WRONG_RATE_LOWER",
    "archive_path",
    "calibration_readiness",
    "centroid_readiness",
    "compact_ledger",
    "corpus_stats",
    "iter_records",
    "judged_alerts",
    "ledger_health",
    "ledger_path",
    "record_alert",
    "record_verdict",
    "resolve_stratum",
    "score_summary",
    "select_retained",
    "veto_readiness",
]
