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
from ._consts import EPISODE_DEFAULTS, log
from ._segment import quiet_window_min, segment_history
from ._store import append_episode, existing_ids
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


def sweep(storage_root, rows, *, events_cfg=None, episode_cfg=None) -> dict:
    """Detect + archive in one pass. Safe to call on every poll."""
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
        "pending": pending,
    }
