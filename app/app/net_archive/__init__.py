"""NETZ · the durable record of what the net looked like when it asked.

The threshold state in force at the moment a question went out cannot be
reconstructed afterwards: the nightly learner will have moved on, and
the operator may have dragged the axis since. So it is captured
synchronously, in the same call that sends the question — and for every
alarm too, so the archive covers both bands of the net.

    storage/net_archive/<YYYY-MM>/<event_id>.json
    storage/net_archive/<YYYY-MM>/<event_id>.jpg

Under ``storage/``, OUTSIDE ``motion_detection/``. ``cleanup_old``
deletes by age inside the event tree; an archive living there would
dissolve at 14 days, exactly when it becomes historically interesting.
The archive keeps its own copy of the frame for the same reason: when
retention has swept the event, its snapshot and its clip, the archive
entry and its picture must still be there.

The record's ``net_state`` carries, per axis, the value AND the ladder
layer that produced it — straight off ``EffectiveThresholds.source``.
That makes this the second conforming consumer of
``thresholds.resolve_effective``, and it is the reason the archive can
be trusted: the numbers in it are the numbers the pipeline used, by
construction, not a second reading of the same config.

Layout:

    _consts.py     — paths, quotas, the state/badge vocabulary
    _io.py         — atomic JSON round-trip + the frame re-encode
    _write.py      — the three writes, and the five German sentences
    _read.py       — the browse page and the durable event-context lookup
    _retention.py  — 400 records / 24 months, unjudged evicted first
"""

from __future__ import annotations

from ._consts import (
    KIND_ALARM,
    KIND_FRAGE,
    KIND_NETZ,
    MAX_AGE_DAYS,
    MAX_RECORDS,
    PAGE_SIZE,
    SCOPE_POOLED,
    SCOPE_STRATUM,
    STATE_BADGE,
    STATE_CHANGED,
    STATE_CONFIRMED,
    STATE_PENDING,
    STATE_PINNED,
    VERDICT_OTHER,
    VERDICT_RIGHT,
    VERDICT_WRONG,
)
from ._io import frame_path, load_record
from ._read import find_event_context, get_record, list_records
from ._retention import enforce, select_evictable
from ._write import (
    append_consequence,
    append_verdict,
    build_net_state,
    capture,
    record_net_change,
    sentence_changed,
    sentence_confirmed,
    sentence_pending,
    sentence_pinned,
)

__all__ = [
    "KIND_ALARM",
    "KIND_FRAGE",
    "KIND_NETZ",
    "MAX_AGE_DAYS",
    "MAX_RECORDS",
    "PAGE_SIZE",
    "SCOPE_POOLED",
    "SCOPE_STRATUM",
    "STATE_BADGE",
    "STATE_CHANGED",
    "STATE_CONFIRMED",
    "STATE_PENDING",
    "STATE_PINNED",
    "VERDICT_OTHER",
    "VERDICT_RIGHT",
    "VERDICT_WRONG",
    "append_consequence",
    "append_verdict",
    "build_net_state",
    "capture",
    "enforce",
    "find_event_context",
    "frame_path",
    "get_record",
    "list_records",
    "load_record",
    "record_net_change",
    "select_evictable",
    "sentence_changed",
    "sentence_confirmed",
    "sentence_pending",
    "sentence_pinned",
]
