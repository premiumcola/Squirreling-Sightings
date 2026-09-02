"""Batch re-analysis of archived bird clips.

Answers one operator question: many of these clips were recorded under a
much less developed build — what does today's detection make of them?

The unit of work is `replay/`'s single-event replay, unchanged. This
package only adds selection (which clips), scheduling (off the request
thread, cancellable) and aggregation (one report instead of hundreds of
comparisons). See `_aggregate.py` for what the numbers do and do not
claim — in particular, a replay never classifies species, so this
package reports which clips COULD now be named, not that any were.
"""

from __future__ import annotations

from ._aggregate import count_birds, fold, movers_from, summarise_event
from ._consts import BATCH_SCHEMA, BIRD_LABELS, MAX_DETAIL_ROWS, MAX_MOVERS, REPORT_FILENAME
from ._persist import load_report, report_path, save_report
from ._run import run_batch, start_batch
from ._select import event_day, find_bird_events, in_range, is_bird_event
from ._state import request_cancel, reset_for_tests, snapshot

__all__ = [
    "BATCH_SCHEMA",
    "BIRD_LABELS",
    "MAX_DETAIL_ROWS",
    "MAX_MOVERS",
    "REPORT_FILENAME",
    "count_birds",
    "event_day",
    "find_bird_events",
    "fold",
    "in_range",
    "is_bird_event",
    "load_report",
    "movers_from",
    "report_path",
    "request_cancel",
    "reset_for_tests",
    "run_batch",
    "save_report",
    "snapshot",
    "start_batch",
    "summarise_event",
]
