"""What survives an automatic compaction — and the invariant behind it.

The ledger has to stay bounded, and the obvious ways to bound it are all
wrong in the same way: they throw away whatever is oldest, or whatever is
least numerous, and both of those are correlated with *value*. A rare
class has few records by definition; a judgement someone made in March is
older than a thousand alerts from June.

So the rule here is not "keep the newest N". It is:

    **An automatic sweep may delete only an unjudged alert.**

Everything else is outside the budget entirely:

* a **judged alert and its verdict** — a person looked at a picture and
  tapped a button. That cannot be regenerated at any price.
* a **verdict with no alert record** — not a corner case. ``record_alert``
  is written inside the Telegram gate chain, *below* the mute and
  push-flag gates, so a muted camera or a label with ``push: false``
  produces no alert record at all; and if Telegram is off there are no
  alert records anywhere. Meanwhile the web surfaces (``routes/events.py``
  confirm / label-correction / delete, FB-1) write a verdict for any
  event the user touches. Those verdicts carry ``cam`` and
  ``corrected_label``, which is precisely what a per-camera label veto is
  built from. The previous implementation deleted every one of them.
* a **record of a kind this version does not know**. Dropping data
  because it was written by newer code is how a corpus quietly loses the
  thing that mattered.

An unjudged alert is reproducible by waiting, so it is the one thing that
may go. Eviction is round-robin per (camera, label) rather than global
newest-first: cutting a time-sorted corpus at a budget deletes a rare
class outright the first time a common one has a busy week.

And every eviction is *counted*. A ``census`` record per stratum carries
the running total of alerts thrown away, so ``corpus_stats`` can compute
the answer rate against the number of alerts that ever happened rather
than the number still on disk. Without it the rate rises with every
compaction — retention keeps judged records and drops unjudged ones — and
the "have we got enough data?" gate can never honestly say no.
"""

from __future__ import annotations

import logging
from collections import Counter

from ._consts import (
    KIND_ALERT,
    KIND_CENSUS,
    KIND_VERDICT,
    MAX_RETAINED_RECORDS,
    MAX_UNJUDGED_PER_STRATUM,
)

log = logging.getLogger(__name__)

# Sort rank within one timestamp: an alert before its verdict, the
# census summary last because it describes the whole file.
_KIND_RANK = {KIND_ALERT: 0, KIND_VERDICT: 1, KIND_CENSUS: 3}
_UNKNOWN_RANK = 2


class LedgerIndex:
    """A record stream folded into the shapes every reader here wants.

    The one place the join is defined: last write wins (a later verdict
    supersedes an earlier one), and duplicates left behind by an
    interrupted compaction collapse for free.
    """

    __slots__ = ("alerts", "verdicts", "census", "passthrough", "unjoinable")

    def __init__(self):
        self.alerts = {}  # event_id -> alert record
        self.verdicts = {}  # event_id -> final verdict record
        self.census = Counter()  # (cam, label) -> alerts evicted so far
        self.passthrough = []  # records of a kind this version cannot read
        self.unjoinable = 0  # alert/verdict records carrying no event_id

    def orphan_verdicts(self):
        """Verdicts whose alert record does not exist. Kept, never evicted."""
        return [v for eid, v in self.verdicts.items() if eid not in self.alerts]


def stratum(record) -> tuple:
    """The (camera, label) cell a record belongs to."""
    return (record.get("cam") or "?", record.get("label") or "?")


def index_records(records) -> LedgerIndex:
    """Fold a record stream into a :class:`LedgerIndex`."""
    idx = LedgerIndex()
    for rec in records:
        kind = rec.get("kind")
        if kind == KIND_CENSUS:
            idx.census[stratum(rec)] += int(rec.get("evicted_alerts") or 0)
            continue
        if kind not in (KIND_ALERT, KIND_VERDICT):
            # Unknown kind: preserved verbatim, position and all.
            idx.passthrough.append(rec)
            continue
        eid = rec.get("event_id")
        if not eid:
            # A known kind that can never be joined to its counterpart.
            # Counted so `corpus_stats` can surface it instead of losing
            # it silently, but not retained: an alert with no event_id
            # cannot become a corpus sample however long it is kept.
            idx.unjoinable += 1
            continue
        (idx.alerts if kind == KIND_ALERT else idx.verdicts)[eid] = rec
    return idx


def _split_alerts(idx: LedgerIndex):
    """Bucket alert ids per stratum, judged and unjudged apart.

    Each bucket is ordered oldest-first so eviction can walk it from the
    newest end.
    """
    judged: dict = {}
    unjudged: dict = {}
    for eid, alert in idx.alerts.items():
        bucket = judged if eid in idx.verdicts else unjudged
        bucket.setdefault(stratum(alert), []).append(eid)
    for buckets in (judged, unjudged):
        for ids in buckets.values():
            ids.sort(key=lambda e: idx.alerts[e].get("ts") or 0)
    return judged, unjudged


def _take_newest(buckets, *, budget: int, per_stratum: int):
    """Take newest-first from every stratum in turn until the budget runs out.

    Round-robin, not "newest globally first". One per stratum per pass
    means a stratum holding three records keeps all three however loud
    its neighbours are.

    Returns ``(taken_event_ids, dropped_counter_by_stratum)``.
    """
    keys = sorted(buckets)
    # Cursor = index of the next record to take, walking backwards.
    cursors = {key: len(buckets[key]) for key in keys}
    taken: list = []
    while budget > 0:
        progressed = False
        for key in keys:
            ids = buckets[key]
            i = cursors[key]
            if i <= 0 or (len(ids) - i) >= per_stratum:
                continue
            if budget <= 0:
                break
            cursors[key] = i - 1
            taken.append(ids[i - 1])
            budget -= 1
            progressed = True
        if not progressed:
            break
    dropped = Counter({key: cursors[key] for key in keys if cursors[key]})
    return taken, dropped


def _census_records(idx: LedgerIndex, dropped, ts: float):
    """Fold the running eviction counts and this pass's drops into one
    record per stratum.

    Folding is lossless (they are pure counters) and keeps the census
    from growing by one record per stratum per compaction forever.
    """
    total = Counter(idx.census)
    total.update(dropped)
    return [
        {
            "kind": KIND_CENSUS,
            "ts": ts,
            "cam": cam,
            "label": label,
            "evicted_alerts": n,
        }
        for (cam, label), n in sorted(total.items())
        if n > 0
    ]


def _chrono(record):
    return (
        record.get("ts") or 0,
        _KIND_RANK.get(record.get("kind"), _UNKNOWN_RANK),
    )


def select_retained(
    records,
    *,
    max_records: int = MAX_RETAINED_RECORDS,
    max_unjudged_per_stratum: int = MAX_UNJUDGED_PER_STRATUM,
) -> list:
    """Choose what survives a compaction: bounded, but still representative.

    ``max_records`` is a budget over the evictable pool only — see the
    module docstring for why judged records, orphan verdicts and unknown
    kinds sit outside it. A corpus with more judgements than the budget
    therefore exceeds it rather than losing them; ``corpus_stats``
    reports that overflow.
    """
    records = list(records)
    idx = index_records(records)
    judged, unjudged = _split_alerts(idx)

    protected = [eid for ids in judged.values() for eid in ids]
    orphans = idx.orphan_verdicts()
    # A judged event costs two records, its alert and its verdict.
    spent = len(protected) * 2 + len(orphans) + len(idx.passthrough)
    taken, dropped = _take_newest(
        unjudged,
        budget=max(max_records - spent, 0),
        per_stratum=max_unjudged_per_stratum,
    )

    kept_ids = protected + taken
    out = [idx.alerts[eid] for eid in kept_ids]
    out += [idx.verdicts[eid] for eid in protected]
    out += orphans
    out += idx.passthrough
    ts = max((r.get("ts") or 0 for r in records), default=0)
    out += _census_records(idx, dropped, ts)
    out.sort(key=_chrono)
    if idx.passthrough:
        log.info(
            "[storage] detection-feedback carried %d record(s) of an unknown kind through "
            "compaction: %s",
            len(idx.passthrough),
            sorted({str(r.get("kind")) for r in idx.passthrough}),
        )
    return out
