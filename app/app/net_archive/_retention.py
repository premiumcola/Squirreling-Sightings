"""What survives an archive sweep — the ledger's policy shape, applied here.

Same invariant as ``detection_feedback._retention``, deliberately mirrored
rather than reinvented:

    **A sweep may delete an UNJUDGED record before a judged one.**

A judged record is a picture a person looked at and a button they
tapped, plus the exact threshold state that was in force at that moment.
It cannot be regenerated at any price. An unjudged record is reproducible
by waiting for the next similar detection.

Two quotas, whichever bites first: :data:`MAX_RECORDS` and
:data:`MAX_AGE_DAYS`. Both are generous — 400 records at ~60 kB of image
is ~25 MB, and 24 months is longer than any threshold in the system has
existed.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from ._consts import MAX_AGE_DAYS, MAX_RECORDS
from ._io import delete_record, iter_record_paths, read_record

log = logging.getLogger(__name__)


def _age_days(rec: dict) -> float:
    try:
        return (time.time() - datetime.fromisoformat(rec["ts"]).timestamp()) / 86400.0
    except Exception:
        # An unparsable timestamp is not evidence of age. Treat it as
        # brand new so a broken field can never trigger a deletion.
        return 0.0


def select_evictable(records: list) -> list:
    """Event ids to delete, given ``[(event_id, record)]`` newest first.

    Order of decisions, and each one matters:

    1. Anything past the age cap goes, judged or not — 24 months is the
       point at which the threshold state on the record describes a
       system that no longer exists.
    2. Over the count cap, unjudged records go first, oldest first.
    3. Only if unjudged records alone cannot get under the cap do judged
       ones go, again oldest first. That branch is reachable only on an
       archive of 400 answered questions, which is a corpus worth
       having and a good problem.
    """
    too_old = [eid for eid, rec in records if _age_days(rec) > MAX_AGE_DAYS]
    keep = [(eid, rec) for eid, rec in records if eid not in set(too_old)]
    over = len(keep) - MAX_RECORDS
    if over <= 0:
        return too_old
    unjudged = [eid for eid, rec in keep if not rec.get("verdict")]
    judged = [eid for eid, rec in keep if rec.get("verdict")]
    # `records` arrives newest-first, so the tail of each list is oldest.
    evict = list(reversed(unjudged))[:over]
    if len(evict) < over:
        evict += list(reversed(judged))[: over - len(evict)]
    return too_old + evict


def enforce(storage_root) -> int:
    """Apply both quotas. Returns the number of records removed."""
    records = []
    for path in iter_record_paths(storage_root):
        rec = read_record(path)
        if rec is None:
            continue
        records.append((rec.get("event_id") or path.stem, rec))
    evict = select_evictable(records)
    for eid in evict:
        delete_record(storage_root, eid)
    if evict:
        log.info("[storage] net_archive: %d Datensätze verworfen", len(evict))
    return len(evict)
