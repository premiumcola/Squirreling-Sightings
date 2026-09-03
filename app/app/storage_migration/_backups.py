"""The timestamped settings backup this migration takes for itself.

Separate from the 2-deep ``.bak`` / ``.bak2`` rotation that
``SettingsStore.save`` owns — those files belong to a different
lifecycle and must never be touched here.

The backup is taken as a ``.partial`` and only promoted to the visible
``.bak.<ts>`` name once the migration has actually mutated something and
``save()`` did not crash, so idle boots stop leaving a permanent file
behind while crash safety survives.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from datetime import datetime
from pathlib import Path

from ._consts import _DEFAULT_BACKUP_KEEP, _TIMESTAMPED_BAK_RE, log


def _backup_settings_partial(settings_store) -> tuple[Path | None, Path | None]:
    """Drop a timestamped backup next to settings.json BEFORE any
    write, but under a ``.partial`` suffix so the boot can decide
    whether to keep it.

    Returns ``(final_path, partial_path)`` where ``final_path`` is the
    eventual ``settings.json.bak.<ts>`` location and ``partial_path``
    is the on-disk file that currently holds the copy. If creation
    failed both are ``None``.

    The two-step "create partial → promote on real change" dance is
    the whole point of this refactor: idle reboots no longer leave a
    permanent file behind, but crash safety during the rewrite
    survives because the partial is on disk for the duration of
    Pass 2."""
    src = settings_store.path
    if not src.exists():
        return None, None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    final = src.with_suffix(src.suffix + f".bak.{ts}")
    partial = final.with_suffix(final.suffix + ".partial")
    try:
        shutil.copy2(str(src), str(partial))
        return final, partial
    except Exception as e:
        log.warning("[migration] settings backup failed: %s", e)
        return None, None


def _promote_or_discard_partial(
    final: Path | None, partial: Path | None, actually_changed: bool
) -> Path | None:
    """Finalise the partial backup. Promote to ``.bak.<ts>`` when the
    migration mutated state, discard otherwise. Returns the path of
    the retained backup, or ``None`` when discarded / never created.

    ``actually_changed`` is computed by the caller from the migration
    summary so callers and tests share the exact same trigger
    condition."""
    if not partial:
        return None
    if not partial.exists():
        return None
    if actually_changed and final is not None:
        try:
            os.replace(str(partial), str(final))
            return final
        except Exception as e:
            log.warning(
                "[migration] could not promote partial backup %s → %s: %s", partial, final, e
            )
            # Best-effort cleanup of the orphaned partial — leaving it
            # behind would defeat the whole point of the refactor.
            with contextlib.suppress(Exception):
                partial.unlink()
            return None
    # No mutations OR no `final` path → discard the partial.
    try:
        partial.unlink()
    except Exception as e:
        log.debug("[migration] could not unlink partial %s: %s", partial, e)
    return None


def _prune_old_settings_backups(settings_store, keep: int = _DEFAULT_BACKUP_KEEP) -> int:
    """Delete timestamped migration backups beyond the ``keep`` most
    recent. Returns the number of files actually pruned. The bare
    ``settings.json.bak`` / ``settings.json.bak2`` rotation files
    SettingsStore.save() maintains are explicitly excluded — only
    paths matching ``_TIMESTAMPED_BAK_RE`` are candidates.

    ``keep`` is clamped to [1, 100] so a malformed
    ``settings.server.settings_backup_keep`` config value can never
    wipe history."""
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        keep = _DEFAULT_BACKUP_KEEP
    keep = max(1, min(100, keep))
    parent = settings_store.path.parent
    stem = settings_store.path.name
    if not parent.exists():
        return 0
    candidates = list(parent.glob(f"{stem}.bak.*"))
    timestamped = [p for p in candidates if _TIMESTAMPED_BAK_RE.match(p.name)]
    if not timestamped:
        return 0
    # Newest first by mtime; everything past `keep` index gets pruned.
    timestamped.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    pruned = 0
    for old in timestamped[keep:]:
        try:
            old.unlink()
            pruned += 1
            log.info("[migration] pruned old backup: %s", old.name)
        except Exception as e:
            log.debug("[migration] prune failed for %s: %s", old.name, e)
    return pruned


def _resolve_backup_keep(settings_store) -> int:
    """Read the user-configurable cap from settings.json (server block)
    or fall back to the default. Out-of-range or non-int values fall
    back silently — power-user override, not a UI surface."""
    try:
        cfg = settings_store.data.get("server", {}) or {}
        raw = cfg.get("settings_backup_keep")
    except Exception:
        raw = None
    if raw is None:
        return _DEFAULT_BACKUP_KEEP
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_BACKUP_KEEP
    if n < 1 or n > 100:
        return _DEFAULT_BACKUP_KEEP
    return n
