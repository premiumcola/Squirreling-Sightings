"""Detect over the whole history, archive what is new, report what is open.

There is no separate "backfill" mode. Every sweep segments the ENTIRE
history buffer — 30 days at the default 5-minute poll — and appends only
the episodes whose id is not on disk yet. The first sweep after a fresh
deploy therefore backfills the whole rolling window, and every sweep
after that is a no-op for everything it already wrote. One code path,
idempotent by construction, and nothing to forget to run once.

Cost: ~8600 samples x 4 thresholds per sweep, once per poll. Microseconds.
"""

from __future__ import annotations

from datetime import timedelta

from ._build import build_record
from ._consts import EPISODE_DEFAULTS, FOOTAGE_BACKFILL_PER_SWEEP, log
from ._segment import quiet_window_min, segment_history
from ._store import append_episode, append_footage_count, existing_ids, list_episodes
from ._thresholds import resolve_thresholds


def _clamp_min(value, fallback: int) -> float:
    """Minutes, coerced and bounded to 0..1440. A negative margin would
    invert the slice bounds; a 3-day margin would swallow the buffer."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return max(0.0, min(1440.0, out))


def resolve_episode_cfg(cfg: dict | None) -> dict:
    """Merge the user's ``weather.episodes`` block over the defaults."""
    block = cfg if isinstance(cfg, dict) else {}
    return {
        "enabled": bool(block.get("enabled", EPISODE_DEFAULTS["enabled"])),
        "pre_min": _clamp_min(block.get("pre_min"), EPISODE_DEFAULTS["pre_min"]),
        "post_min": _clamp_min(block.get("post_min"), EPISODE_DEFAULTS["post_min"]),
        "settle_min": _clamp_min(block.get("settle_min"), EPISODE_DEFAULTS["settle_min"]),
    }


def detect_episodes(rows, *, events_cfg=None, episode_cfg=None) -> tuple:
    """Segment a history buffer. Returns ``(finalised_records, pending)``.

    Pure — touches no disk. ``pending`` is the trailing storm the
    history cannot close yet (see ``_segment`` for why), carried without
    its samples plus a ``finalizes_at`` hint.
    """
    ep = resolve_episode_cfg(episode_cfg)
    thresholds = resolve_thresholds(events_cfg)
    if not ep["enabled"] or not thresholds:
        return [], None
    samples, finalised, pending_seg = segment_history(
        rows,
        thresholds,
        pre_min=ep["pre_min"],
        post_min=ep["post_min"],
        settle_min=ep["settle_min"],
    )
    records = [
        build_record(samples, seg, thresholds, pre_min=ep["pre_min"], post_min=ep["post_min"])
        for seg in finalised
    ]
    pending = None
    if pending_seg is not None:
        pending = build_record(
            samples, pending_seg, thresholds, pre_min=ep["pre_min"], post_min=ep["post_min"]
        )
        pending.pop("samples", None)
        quiet = quiet_window_min(ep["settle_min"], ep["pre_min"], ep["post_min"])
        pending["finalizes_at"] = (
            samples[pending_seg.end_i].ts + timedelta(minutes=quiet)
        ).isoformat(timespec="seconds")
    return records, pending


def _stamp_footage(storage_root, counter) -> int:
    """Count the recordings around episodes that carry no count yet.

    This is where the archive list's footage chip gets its number. It
    runs HERE — on the poll thread, once per episode, ever — rather than
    on the list route, which used to re-walk the whole motion tree on
    every request for a number that cannot change once the window is
    closed. Budgeted per sweep (see FOOTAGE_BACKFILL_PER_SWEEP).

    A counter that fails or declines (returns ``None``) ends the batch:
    the media stores are unavailable right now and the next sweep is
    five minutes away.
    """
    stamped = 0
    for rec in list_episodes(storage_root):
        if stamped >= FOOTAGE_BACKFILL_PER_SWEEP:
            break
        if rec.get("footage_count") is not None:
            continue
        try:
            count = counter(rec)
        except Exception as e:
            log.warning("[weather] footage count failed for %s: %s", rec.get("id"), e)
            break
        if count is None:
            break
        if append_footage_count(storage_root, rec["id"], count):
            stamped += 1
            log.info("[weather] episode %s: %d recording(s) in window", rec["id"], count)
    return stamped


def sweep(storage_root, rows, *, events_cfg=None, episode_cfg=None, footage_counter=None) -> dict:
    """Detect + archive in one pass. Safe to call on every poll.

    ``footage_counter`` is an optional ``record -> int | None`` that
    scans the media stores for ONE episode's window. Injected rather
    than imported so this package never reaches into app_state.
    """
    records, pending = detect_episodes(rows, events_cfg=events_cfg, episode_cfg=episode_cfg)
    known = existing_ids(storage_root)
    archived = 0
    for rec in records:
        if rec["id"] in known:
            continue
        if append_episode(storage_root, rec):
            archived += 1
            log.info(
                "[weather] episode archived: %s · %d min · intensity %.2f",
                rec["id"],
                rec["duration_min"],
                rec["intensity"],
            )
    return {
        "archived": archived,
        "detected": len(records),
        "known": len(known),
        "stamped": _stamp_footage(storage_root, footage_counter) if footage_counter else 0,
        "pending": pending,
    }
