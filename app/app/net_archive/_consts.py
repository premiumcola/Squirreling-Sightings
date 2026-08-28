"""Layout, retention quotas and the vocabulary of an archive record.

The record is written AT ASK TIME. That is the whole point of the
module: the threshold state in force when a question went out cannot be
reconstructed afterwards, because the learner will have moved on.
Capturing it when the answer arrives would record the wrong numbers and
nobody would ever notice.
"""

from __future__ import annotations

#: Directory under ``storage/`` — deliberately NOT inside
#: ``motion_detection/``. ``cleanup_old`` deletes by age inside the event
#: tree, so an archive living there would dissolve at 14 days, exactly
#: when it becomes historically interesting. Same reasoning that put
#: ``detection_feedback`` in ``storage/_diag/``.
ARCHIVE_DIRNAME = "net_archive"

#: Record kinds.
KIND_FRAGE = "frage"  # spawn <= score < push — the quiet question
KIND_ALARM = "alarm"  # score >= push — the existing event alert
KIND_NETZ = "netz_aenderung"  # a manual drag; no image

#: Consequence states. The `state` field IS the answer to "war meine
#: Einstufung eine Optimierung?" — every card carries one, never silence.
STATE_CHANGED = "changed"
STATE_CONFIRMED = "confirmed"
STATE_OUTVOTED = "outvoted"
STATE_PENDING = "pending"
STATE_PINNED = "pinned"

#: One glyph per state, for the list row's badge.
STATE_BADGE = {
    STATE_CHANGED: "↕",
    STATE_CONFIRMED: "✓",
    STATE_PENDING: "⏳",
    STATE_OUTVOTED: "⊘",
    STATE_PINNED: "🔒",
}

#: Verdict values, German because they are read by a German operator and
#: the archive is the surface that prints them.
VERDICT_RIGHT = "richtig"
VERDICT_WRONG = "falsch"
VERDICT_OTHER = "anders"

#: Provenance of an axis at ask time.
SCOPE_STRATUM = "stratum"
SCOPE_POOLED = "pooled"

# ── retention ─────────────────────────────────────────────────────────
#
# 400 records or 24 months, whichever bites first, evicting UNJUDGED
# records before judged ones — the same policy shape
# ``detection_feedback._retention.select_retained`` applies to the
# ledger. Two retention rules that disagree produce an archive that
# looks complete and is not.
MAX_RECORDS = 400
MAX_AGE_DAYS = 730

#: Long edge of the archived frame. ~60 kB at this size; 400 x 60 kB is
#: about 25 MB for the whole archive, which is the budget that makes
#: "the archive outlives the event" affordable.
FRAME_MAX_EDGE = 640
FRAME_JPEG_QUALITY = 82

#: Page size for the browse API.
PAGE_SIZE = 40
