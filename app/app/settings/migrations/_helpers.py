"""Shared helpers used by more than one migration."""

from __future__ import annotations

import logging

log = logging.getLogger("app.settings.migrations")


def _deep_merge_defaults(target: dict, defaults: dict) -> None:
    """Recursively fill missing keys in `target` from `defaults`.

    Existing user values are NEVER overwritten — only absent keys (and
    nested absent keys inside dicts) are added. Values whose existing
    type is not dict are left as-is even when the default is a dict;
    this protects against stomping on hand-edited overrides.
    """
    if not isinstance(target, dict):
        return
    for key, default_val in defaults.items():
        if isinstance(default_val, dict):
            sub = target.setdefault(key, {})
            if isinstance(sub, dict):
                _deep_merge_defaults(sub, default_val)
        else:
            target.setdefault(key, default_val)
