"""Constants for the batch replay run.

Kept in their own module so `_aggregate.py` stays importable without
dragging in the job state or the filesystem — the aggregation is the
part with the tests, and a test should not need a storage root to
import the thing it is testing.
"""

from __future__ import annotations

#: Shape of the persisted report document. Bumped when a key changes
#: meaning, so a report written by an older build is recognisable as
#: such rather than silently mis-read — mirrors replay/_consts.py::
#: REPLAY_SCHEMA, which exists for the same reason on the per-event
#: `replays` entries.
BATCH_SCHEMA = 2

#: Filename under the storage root. One slot, overwritten by each run:
#: the operator's question is "what does today's detection make of the
#: archive", and a second answer to that question supersedes the first
#: rather than accumulating beside it.
REPORT_FILENAME = "replay_batch_report.json"

#: How many per-event rows the persisted report keeps. The aggregate
#: counters are computed over EVERY examined event; this only caps the
#: detail list, so a 900-clip archive still answers "how many changed"
#: exactly while the document stays a size the dashboard can fetch.
MAX_DETAIL_ROWS = 200

#: How many "biggest confidence mover" rows the report carries. The
#: operator wants the headline movers, not a ranked list of everything.
MAX_MOVERS = 20

#: How many newly-named species the report ranks. The German name map
#: the classifier gates on carries ~80 binomials, so a full archive
#: sweep cannot produce many more distinct names than this; the cap is
#: a guard against a pathological run, not a routine truncation.
MAX_SPECIES_ROWS = 25

#: Labels that count as a bird for selection purposes. A single-element
#: tuple today; kept as a tuple because the detector's label set is data
#: (`_label_loader.py`), not a constant, and a future model that emits
#: e.g. "songbird" should be added here rather than in four predicates.
BIRD_LABELS = ("bird",)
