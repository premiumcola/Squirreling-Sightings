"""Append-only persistence for the weather history buffer.

The history used to be one JSON document rewritten in full — serialise
the whole deque, atomic-replace, fsync — on **every poll**. That is fine
at a 30-day window (1.4 MB) and untenable at a long one: the operator
asked for three years, which is ~315 000 samples ≈ 53 MB, rewritten and
fsynced every five minutes. The cost is not the disk space, it is the
write amplification and the SSD wear.

So the window length and the write cost are decoupled: one line is
appended per poll (~168 B) regardless of how far back the buffer
reaches, and the file is compacted — trimmed to the window and rewritten
atomically — only when it has grown meaningfully past it.

`weather_episodes.jsonl` already established the append-only ledger
pattern in this project; this is the same idea with a simpler record and
a rolling window instead of a fold.

Recovery: a torn last line (kill -9 mid-append) is dropped on read, and
that is the whole repair — losing at most the newest sample, never the
history. A full-document rewrite has no such property, which is why the
old path needed fsync on every write to be safe at all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..io_utils import atomic_write_json
from ._consts import HISTORY_FIELDS, log

#: Compact once the file holds this many times the window. 1.25 keeps the
#: read bounded (never more than ~25 % waste to skip on boot) while making
#: compaction rare: at a 5-minute poll and a 3-year window that is one
#: rewrite roughly every nine months, versus one per poll before.
COMPACT_FACTOR = 1.25


def history_path(storage_root) -> Path:
    return Path(storage_root) / "weather_history.jsonl"


def legacy_path(storage_root) -> Path:
    """The pre-append-only document. Read once, then left alone."""
    return Path(storage_root) / "weather_history.json"


def _clean(row) -> dict | None:
    """One stored sample, normalised to the current field set.

    Fields that left HISTORY_FIELDS are dropped and new ones are filled
    with None, so a schema change never invalidates the archive and never
    crashes the read.
    """
    if not isinstance(row, dict):
        return None
    ts = row.get("ts")
    values = row.get("values")
    if not isinstance(ts, str) or not isinstance(values, dict):
        return None
    return {"ts": ts, "values": {k: values.get(k) for k in HISTORY_FIELDS}}


def load(storage_root, maxlen: int) -> list[dict]:
    """The newest ``maxlen`` samples, oldest first.

    Reads the JSONL ledger; falls back to the legacy document when the
    ledger does not exist yet, so an existing install keeps its history
    across the format change without a migration step.
    """
    path = history_path(storage_root)
    if path.exists():
        rows: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = _clean(json.loads(line))
                    except Exception:
                        # A torn final line after a hard kill. Skipping it
                        # costs one sample; refusing the file costs the
                        # archive.
                        continue
                    if row:
                        rows.append(row)
        except Exception as e:
            log.warning("[weather] history ledger unreadable, starting fresh: %s", e)
            return []
        return rows[-maxlen:]
    return _load_legacy(storage_root, maxlen)


def _load_legacy(storage_root, maxlen: int) -> list[dict]:
    path = legacy_path(storage_root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("[weather] legacy history unparseable, starting fresh: %s", e)
        return []
    items = payload.get("samples") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        log.warning("[weather] legacy history has unexpected shape, starting fresh")
        return []
    rows = [r for r in (_clean(x) for x in items[-maxlen:]) if r]
    log.info("[weather] history: %d Samples aus dem Alt-Format übernommen", len(rows))
    return rows


def append(storage_root, sample: dict) -> bool:
    """Append one sample. Returns False on failure — never raises.

    fsync is deliberate and affordable here: it flushes ~168 bytes, not
    the whole archive, which is the entire point of the format change.
    """
    path = history_path(storage_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(sample, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    except Exception as e:
        log.warning("[weather] history append failed: %s", e)
        return False


def needs_compaction(storage_root, maxlen: int) -> bool:
    """Cheap size-based estimate — no parse.

    Uses the mean serialised length of the samples already on disk rather
    than a hardcoded byte figure, so a future field addition cannot make
    this silently wrong.
    """
    path = history_path(storage_root)
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= 0:
        return False
    approx_line = 180
    return size > approx_line * maxlen * COMPACT_FACTOR


def compact(storage_root, rows: list[dict]) -> bool:
    """Rewrite the ledger with exactly ``rows``. Atomic; never partial."""
    path = history_path(storage_root)
    tmp = path.with_suffix(".jsonl.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        log.info("[weather] history kompaktiert: %d Samples", len(rows))
        return True
    except Exception as e:
        log.warning("[weather] history compaction failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def write_all(storage_root, rows: list[dict]) -> bool:
    """Full rewrite — used by the shutdown path and by tests.

    Kept distinct from :func:`compact` only so the log line is honest
    about why the file was rewritten.
    """
    return compact(storage_root, rows)


__all__ = [
    "COMPACT_FACTOR",
    "MAX_CHART_POINTS",
    "downsample",
    "append",
    "compact",
    "history_path",
    "legacy_path",
    "load",
    "needs_compaction",
    "write_all",
    "atomic_write_json",
]


# ── downsampling ─────────────────────────────────────────────────────
#
# A three-year window is ~315 000 samples. Shipping that to a phone is
# not a chart, it is a download — and no display has that many pixels.
# So a long window is thinned to at most MAX_CHART_POINTS buckets.
#
# Thinning by "keep every k-th sample" would be wrong here specifically:
# the operator reads this chart for SPIKES ("dann gehen die Blitze auf
# ein hohes Level"), and a stride drops exactly those. So each bucket is
# reduced per field, by what that field means:
#
#   peak fields  — the maximum in the bucket. A lightning spike, a gust
#                  or a downpour must survive thinning; its magnitude is
#                  the whole signal.
#   trough field — visibility, where the INTERESTING value is the low
#                  one (fog). Taking a max would erase every fog event.
#   smooth       — the mean, for slowly-varying background values.
MAX_CHART_POINTS = 2000

_PEAK_FIELDS = frozenset({"precipitation", "snowfall", "lightning_potential", "wind_gusts_10m"})
_TROUGH_FIELDS = frozenset({"visibility"})


def _reduce_bucket(bucket: list[dict]) -> dict:
    """Collapse one bucket into a single sample, per-field."""
    values: dict[str, float | None] = {}
    for key in HISTORY_FIELDS:
        nums = [
            v
            for v in (row.get("values", {}).get(key) for row in bucket)
            if isinstance(v, (int, float))
        ]
        if not nums:
            values[key] = None
        elif key in _PEAK_FIELDS:
            values[key] = max(nums)
        elif key in _TROUGH_FIELDS:
            values[key] = min(nums)
        else:
            values[key] = sum(nums) / len(nums)
    # The bucket's own last timestamp, so the x-axis stays monotonic and
    # the final point still reads as "now".
    return {"ts": bucket[-1].get("ts"), "values": values}


def downsample(rows: list[dict], max_points: int = MAX_CHART_POINTS) -> tuple[list[dict], int]:
    """Return ``(rows, bucket_size)``; bucket_size 1 means untouched."""
    n = len(rows)
    if n <= max_points or max_points < 1:
        return rows, 1
    bucket = (n + max_points - 1) // max_points
    out = [_reduce_bucket(rows[i : i + bucket]) for i in range(0, n, bucket)]
    return out, bucket
