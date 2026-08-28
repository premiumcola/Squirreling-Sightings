"""Append-only persistence for the episode archive.

Same discipline as ``app/app/detection_feedback``: nothing on disk is
ever rewritten. A base ``episode`` record is written once; a user edit
appends a ``patch``; a delete appends a tombstone. The read side folds
patches over bases in file order, so the newest patch for a field wins
and the raw detector output stays recoverable forever.

That matters more here than it does for a diagnostic ledger: the whole
point of the archive is that a storm from 2026 is still comparable in
2031, and a read-modify-write over a multi-megabyte file is exactly the
operation a power cut turns into an empty one.
"""

from __future__ import annotations

import time
from pathlib import Path

from ..io_utils import append_jsonl, iter_jsonl
from ._consts import (
    EPISODE_FILE,
    KIND_DELETE,
    KIND_EPISODE,
    KIND_PATCH,
    PATCHABLE_FIELDS,
    log,
)


def episodes_path(storage_root) -> Path:
    return Path(storage_root or "storage") / EPISODE_FILE


def _fold(storage_root) -> dict:
    """Base records with their patches applied, keyed by id.

    Tombstoned ids are dropped entirely. Unknown record kinds are
    ignored rather than fatal — a future writer may add one.
    """
    bases: dict = {}
    order: list = []
    patches: dict = {}
    deleted: set = set()
    for rec in iter_jsonl(episodes_path(storage_root)):
        kind = rec.get("kind")
        rid = rec.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        if kind == KIND_EPISODE:
            if rid not in bases:
                order.append(rid)
            bases[rid] = rec
        elif kind == KIND_PATCH:
            fields = rec.get("fields")
            if isinstance(fields, dict):
                patches.setdefault(rid, []).append(fields)
        elif kind == KIND_DELETE:
            deleted.add(rid)
    out: dict = {}
    for rid in order:
        if rid in deleted:
            continue
        rec = dict(bases[rid])
        rec.pop("kind", None)
        for fields in patches.get(rid, []):
            for key in PATCHABLE_FIELDS:
                if key in fields:
                    rec[key] = fields[key]
        out[rid] = rec
    return out


def _strip_samples(rec: dict, footage_counts: dict | None = None) -> dict:
    """List view of a record — everything but the curve slice.

    A 30-day archive of storms carries tens of thousands of samples; a
    list endpoint that shipped them would be megabytes per request.

    ``footage_counts`` maps episode id → number of recordings overlapping
    its window. Present only when the caller could compute it; the row
    chip in the UI is absent rather than "0" when it is missing, so an
    unavailable weather service costs a chip, not an error.
    """
    out = {k: v for k, v in rec.items() if k != "samples"}
    out["sample_count"] = rec.get("sample_count", len(rec.get("samples") or []))
    if footage_counts is not None:
        out["footage_count"] = int(footage_counts.get(rec.get("id"), 0))
    return out


def list_episodes(storage_root, *, include_samples: bool = False, footage_counts=None) -> list:
    """Every live episode, newest first. ISO timestamps sort lexically.

    ``footage_counts`` is either a mapping id → count or a callable that
    takes the folded record list and returns one. The callable form
    exists because the ids are only known after the fold, and counting
    footage needs them.
    """
    records = list(_fold(storage_root).values())
    records.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    if include_samples:
        return records
    counts = footage_counts
    if callable(counts):
        try:
            counts = counts(records)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("[weather] footage counts unavailable: %s", e)
            counts = None
    if counts is not None and not isinstance(counts, dict):
        counts = None
    return [_strip_samples(r, counts) for r in records]


def get_episode(storage_root, episode_id: str):
    return _fold(storage_root).get(episode_id)


def existing_ids(storage_root) -> set:
    """Ids already written, tombstones included.

    A deleted episode must NOT be re-created by the next sweep — the
    user removed it on purpose and the history it came from is still in
    the rolling window for another few weeks.
    """
    ids: set = set()
    for rec in iter_jsonl(episodes_path(storage_root)):
        rid = rec.get("id")
        if isinstance(rid, str) and rec.get("kind") in (KIND_EPISODE, KIND_DELETE):
            ids.add(rid)
    return ids


def append_episode(storage_root, record: dict) -> bool:
    payload = dict(record)
    payload["kind"] = KIND_EPISODE
    payload["archived_at"] = round(time.time(), 1)
    return append_jsonl(episodes_path(storage_root), payload)


def patch_episode(storage_root, episode_id: str, fields: dict):
    """Append a patch record. Returns the folded episode, or None."""
    current = _fold(storage_root)
    if episode_id not in current:
        return None
    clean = {k: v for k, v in (fields or {}).items() if k in PATCHABLE_FIELDS}
    if not clean:
        return _strip_samples(current[episode_id])
    ok = append_jsonl(
        episodes_path(storage_root),
        {
            "kind": KIND_PATCH,
            "id": episode_id,
            "ts": round(time.time(), 1),
            "fields": clean,
        },
    )
    if not ok:
        return None
    log.info("[weather] episode %s patched: %s", episode_id, sorted(clean))
    merged = dict(current[episode_id])
    merged.update(clean)
    return _strip_samples(merged)


def delete_episode(storage_root, episode_id: str) -> bool:
    """Append a tombstone. The base record stays on disk."""
    if episode_id not in _fold(storage_root):
        return False
    ok = append_jsonl(
        episodes_path(storage_root),
        {"kind": KIND_DELETE, "id": episode_id, "ts": round(time.time(), 1)},
    )
    if ok:
        log.info("[weather] episode %s tombstoned", episode_id)
    return ok
