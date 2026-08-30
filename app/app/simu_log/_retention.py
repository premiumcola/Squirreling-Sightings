"""What survives a SIMU-log sweep.

Same two-quota shape as ``net_archive._retention`` — count and age,
whichever bites first — but deliberately WITHOUT its judged/unjudged
ordering. That rule exists because a judged archive record contains a
human decision that cannot be regenerated at any price. A debug run
contains no decision: every one of them is reproducible by tapping
"Debug kopieren" again while the camera is in the same state. So the
policy here is the simple one the data actually justifies, oldest first,
and the difference is written down rather than left for a reader to
wonder about.

Enforced on every write. A sweep that only runs on a schedule is a sweep
that has never run on a box the operator rebooted this morning.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ._consts import MAX_AGE_DAYS, MAX_RUNS_PER_CAMERA
from ._io import delete_run, iter_runs

log = logging.getLogger(__name__)


def _age_days(path: Path, now: float) -> float:
    """Age from the file NAME, which is the capture timestamp.

    An unparsable name is treated as brand new — a broken file name must
    never be the thing that triggers a deletion.
    """
    stem = path.stem
    try:
        ts = time.mktime(time.strptime(stem[:15], "%Y%m%d-%H%M%S"))
    except (ValueError, OverflowError):
        return 0.0
    return (now - ts) / 86400.0


def select_evictable(paths: list, now: float | None = None) -> list:
    """Paths to delete, given every run for one camera NEWEST first.

    1. anything past the age cap goes — its threshold numbers describe a
       configuration that no longer exists;
    2. then the oldest go until the count cap is met.
    """
    now = time.time() if now is None else now
    too_old = [p for p in paths if _age_days(p, now) > MAX_AGE_DAYS]
    keep = [p for p in paths if p not in set(too_old)]
    over = len(keep) - MAX_RUNS_PER_CAMERA
    # `paths` arrives newest-first, so the tail is oldest.
    evict = list(reversed(keep))[:over] if over > 0 else []
    return too_old + evict


def enforce(storage_root, cam_id: str) -> int:
    """Apply both quotas for one camera. Returns the number removed."""
    evict = select_evictable(list(iter_runs(storage_root, cam_id)))
    for path in evict:
        delete_run(path)
    if evict:
        log.info("[storage] simu_log: %d Läufe verworfen (%s)", len(evict), cam_id)
    return len(evict)
