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
from ._character import classify_character
from ._consts import (
    EPISODE_FILE,
    KIND_DELETE,
    KIND_EPISODE,
    KIND_FOOTAGE,
    KIND_PATCH,
    PATCHABLE_FIELDS,
    log,
)
from ._preview import build_curve_preview


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
    counts: dict = {}
    heroes: dict = {}
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
        elif kind == KIND_FOOTAGE:
            try:
                counts[rid] = max(0, int(rec.get("count")))
            except (TypeError, ValueError):
                continue
            # `hero` rides the SAME record as `count` — both are stamped
            # from one scan (`_store.append_footage_count`) — so the
            # newest footage record wins for both together, never a mix
            # of an old hero with a new count or vice versa.
            hero = rec.get("hero")
            heroes[rid] = hero if isinstance(hero, dict) else None
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
        if rid in counts:
            rec["footage_count"] = counts[rid]
        # Absent, never `null` — the merged grid's card checks
        # `extra.footage_hero` truthy and falls back to the curve-only
        # layout; a stamped `null` (no playable candidate found on the
        # last scan) reads identically to "never scanned", which is
        # exactly the fallback both cases want.
        if heroes.get(rid) is not None:
            rec["footage_hero"] = heroes[rid]
        # A record archived before this feature existed carries no
        # `character` key. Classify it here, in memory, on every read —
        # never rewrite the ledger for it. `_build.build_record` stamps
        # the field going forward, so this branch only ever runs for
        # that shrinking set of pre-existing records.
        if "character" not in rec:
            rec["character"] = classify_character(
                rec.get("samples") or [],
                rec.get("peaks") or {},
                rec.get("totals"),
                rec.get("thresholds"),
            )
        out[rid] = rec
    return out


def _strip_samples(rec: dict) -> dict:
    """List view of a record — everything but the full curve slice.

    A 30-day archive of storms carries tens of thousands of samples; a
    list endpoint that shipped them would be megabytes per request.
    ``curve_preview`` — a single field's values, bounded to this ONE
    episode's own short window — rides along instead, so the grid card
    can still draw a sparkline without the list response growing with
    every year the (never rolling) archive accumulates. See
    ``_preview.build_curve_preview``.

    ``footage_count`` rides along when the fold found a stamped one. It
    is absent — never "0" — for an episode nobody has counted yet, so
    the row chip stays hidden instead of claiming there is no footage.

    ``footage_hero`` rides along the same way, for free — it is just
    another key on ``rec`` once ``_fold`` has stamped it, so no extra
    handling is needed here. The merged Library grid's episode card
    (``library._weather_readers.episode_candidates`` copies this WHOLE
    stripped record into its item's ``extra``) reads it straight from
    the list response instead of firing a per-card footage request.
    """
    preview = build_curve_preview(rec)
    out = {k: v for k, v in rec.items() if k != "samples"}
    out["sample_count"] = rec.get("sample_count", len(rec.get("samples") or []))
    if preview is not None:
        out["curve_preview"] = preview
    return out


def list_episodes(storage_root, *, include_samples: bool = False) -> list:
    """Every live episode, newest first. ISO timestamps sort lexically.

    Reads the ledger and NOTHING else. The footage chip's number comes
    from the fold (a stamped ``footage`` record), so opening the archive
    costs one append-only file read — not a walk of the motion tree.
    """
    records = list(_fold(storage_root).values())
    records.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    if include_samples:
        return records
    return [_strip_samples(r) for r in records]


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


def append_footage_count(
    storage_root, episode_id: str, count: int, hero: dict | None = None
) -> bool:
    """Stamp how many recordings overlap this episode's window, and
    (optionally) the single best-overlap PLAYABLE one — the merged
    grid's "hero footage" pointer (see ``_footage.episode_hero``).

    Both ride the SAME ledger record because both come from the SAME
    scan — stamping them separately would let a re-stamp update one
    without the other and leave a stale hero next to a fresh count.
    ``hero`` is always written, even as ``None`` (a re-scan that no
    longer finds a playable candidate has to be able to clear a stale
    one), so it is a real field on the ledger record — ``_fold`` is what
    turns a ``None`` hero into "no ``footage_hero`` key at all" for the
    read side.

    Written by whoever last scanned the media stores for that window —
    the sweep for a new or unstamped episode, the footage route for one
    the operator just opened. Re-stamping is an append like everything
    else here; the fold takes the newest.
    """
    return append_jsonl(
        episodes_path(storage_root),
        {
            "kind": KIND_FOOTAGE,
            "id": episode_id,
            "ts": round(time.time(), 1),
            "count": max(0, int(count)),
            "hero": hero if isinstance(hero, dict) else None,
        },
    )


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
