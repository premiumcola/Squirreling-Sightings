"""Reading, appending and compacting the ledger file itself.

Append-only JSONL: no read-modify-write, so concurrent writers from the
camera threads, the Telegram callback thread and HTTP handlers cannot
corrupt each other or lose a record to a torn write. The one exception is
compaction, which is a whole-file rewrite and therefore takes the same
lock the appends take.
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
from pathlib import Path

from ._retention import select_retained

log = logging.getLogger(__name__)

_LEDGER_NAME = "detection_feedback.jsonl"

# Serialises the size check + append. The append itself would be atomic
# for short lines on POSIX, but the compaction is a read-modify-write and
# needs the lock regardless.
_write_lock = threading.Lock()


def _pkg(name: str):
    """Look a name up on the package rather than in this module.

    ``app.detection_feedback._MAX_BYTES`` and
    ``app.detection_feedback.ledger_path`` have been the seams since C4
    and the existing suite still turns both. Splitting the module into a
    package would have frozen a private copy of each into this file at
    import time and silently broken them; resolving late keeps the
    package namespace authoritative for the code that enforces the
    quotas and picks the file.
    """
    return getattr(importlib.import_module(__package__), name)


def ledger_path(storage_root) -> Path:
    return Path(storage_root or "storage") / "_diag" / _LEDGER_NAME


def archive_path(path: Path) -> Path:
    """The compacted generation beside the live ledger."""
    return path.with_suffix(path.suffix + ".1")


def _read_file(path: Path):
    """Yield the parseable records of one file, skipping torn/garbage lines.

    A truncated final line (power loss mid-append) must not make the
    whole file unreadable — that would defeat the point of choosing an
    append-only format.
    """
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except Exception as e:
        log.warning("[storage] detection-feedback read failed (%s): %s", path.name, e)


def iter_records(storage_root):
    """Yield every record, oldest generation first. Skips unparseable lines."""
    path = _pkg("ledger_path")(storage_root)
    yield from _read_file(archive_path(path))
    yield from _read_file(path)


def _compact(path: Path) -> dict:
    """Fold both generations into one bounded, representative archive.

    Renaming live over the old archive — the behaviour this replaces —
    bounded the ledger by discarding whichever records happened to be
    oldest, judgements included.

    Write the new archive durably, *then* drop the live file. A crash
    between the two leaves the evicted records still present in live;
    the next pass folds the duplicate alerts away by ``event_id`` and
    re-counts the evictions, which inflates the census and therefore
    understates the answer rate. That errs towards "not enough data
    yet", which is the direction this system should fail in.
    """
    # Local import: CORP-3 is scheduled to make `storage` import this
    # package (for `has_verdict`), and a module-level import here would
    # close that loop into a cycle. Compaction runs once per 8 MB, so
    # the lookup cost is irrelevant.
    from ..storage import _atomic_write_text

    prev = archive_path(path)
    records = list(_read_file(prev)) + list(_read_file(path))
    if not records:
        # Nothing to fold. Writing an empty archive would only create a
        # file for `ledger_health` to report as "compacted".
        path.unlink(missing_ok=True)
        return {"read": 0, "retained": 0}
    kept = select_retained(
        records,
        max_records=_pkg("MAX_RETAINED_RECORDS"),
        max_unjudged_per_stratum=_pkg("MAX_UNJUDGED_PER_STRATUM"),
    )
    _atomic_write_text(prev, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept))
    path.unlink(missing_ok=True)
    log.info(
        "[storage] detection-feedback compacted: %d record(s) in, %d retained",
        len(records),
        len(kept),
    )
    return {"read": len(records), "retained": len(kept)}


def compact_ledger(storage_root) -> dict:
    """Force a compaction now. Normally triggered by the size cap.

    Exposed so an operator (or a test) can run the sweep on demand
    without waiting for 8 MB of alerts to accumulate.
    """
    with _write_lock:
        return _compact(_pkg("ledger_path")(storage_root))


def append(storage_root, record: dict) -> bool:
    """Append one record. Returns True on success; never raises."""
    try:
        path = _pkg("ledger_path")(storage_root)
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _pkg("_MAX_BYTES"):
                _compact(path)
            # If the previous append was cut short (power loss, full
            # disk) the file does not end in a newline, and writing
            # straight on would fuse the torn fragment with this record
            # and destroy BOTH. Start a fresh line first; the fragment
            # is then dropped by _read_file on its own.
            needs_newline = False
            if path.exists() and path.stat().st_size:
                with open(path, "rb") as probe:
                    probe.seek(-1, 2)
                    needs_newline = probe.read(1) != b"\n"
            with open(path, "a", encoding="utf-8") as fh:
                if needs_newline:
                    fh.write("\n")
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log.warning("[storage] detection-feedback write failed: %s", e)
        return False


def ledger_health(storage_root) -> dict:
    """Where the ledger stands against its own quotas — from ``stat`` only.

    Bounded storage is half of durability; the other half is seeing how
    close to the bound you are BEFORE a compaction silently happens.
    """
    path = _pkg("ledger_path")(storage_root)
    prev = archive_path(path)
    live = path.stat().st_size if path.exists() else 0
    archive = prev.stat().st_size if prev.exists() else 0
    max_bytes = _pkg("_MAX_BYTES")
    return {
        "live_bytes": live,
        "archive_bytes": archive,
        "total_bytes": live + archive,
        "rotate_at_bytes": max_bytes,
        "live_fill": round(live / max_bytes, 6) if max_bytes else 0.0,
        "max_retained_records": _pkg("MAX_RETAINED_RECORDS"),
        "max_unjudged_per_stratum": _pkg("MAX_UNJUDGED_PER_STRATUM"),
        "compacted": archive > 0,
    }
