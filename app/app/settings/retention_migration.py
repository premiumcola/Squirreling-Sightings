"""Additive backfill for the retention keys the Mediathek-Verwaltung
panel configures.

A sibling of ``migrations.py`` rather than another function inside it:
that file is 651 lines against a 500-line ceiling, and the one thing
this migration must not be is buried.

Modelled on ``migrate_weather_defaults`` — ``setdefault`` only, so a
value the install already carries (set by hand, or by a later version)
is never clobbered back to the shipped default, and re-running is a
no-op.

**Why ``storage.retention_days`` is NOT backfilled here.** It is the one
retention key that already exists in ``config.yaml``, and the resolution
order is settings.json first, config.yaml second
(``maintenance.resolve_retention_days``). Seeding it would therefore
freeze whatever config.yaml says today into settings.json and make every
later config.yaml edit inert — the exact reasoning
``settings/defaults.py`` states for leaving it out of the fresh-install
seed. The panel does not need it seeded either: it renders through
``retention_catalog.resolve_days``, which walks the same two layers and
falls back to the shipped default, so an install with the key in neither
layer still shows and saves the right number. The widening guard's
baseline stays ``maintenance.config_retention_days()``, i.e. config.yaml
only, unchanged.
"""

from __future__ import annotations

import logging

from ._consts import STORAGE_RETENTION_DEFAULTS, TRASH_DEFAULTS

log = logging.getLogger(__name__)


def _backfill(data: dict, section: str, defaults: dict) -> list[str]:
    block = data.setdefault(section, {})
    if not isinstance(block, dict):
        block = {}
        data[section] = block
    added = [key for key in defaults if key not in block]
    for key in added:
        block[key] = defaults[key]
    return added


def migrate_retention_defaults(data: dict) -> None:
    """Backfill the per-category retention keys the panel writes.

    * ``storage.retention_camera_timelapses_days`` — 0 (= nie löschen),
      so an upgrading install keeps the behaviour it has always had:
      camera timelapses swept by nothing.
    * ``trash.grace_days`` — 7, the number ``trash._grace_days`` has
      always defaulted to. Seeding it only makes the panel's value
      explicit; it changes no sweep.

    The weather categories are backfilled by ``migrate_weather_defaults``
    and are deliberately not repeated here.
    """
    added = _backfill(data, "storage", STORAGE_RETENTION_DEFAULTS)
    added += _backfill(data, "trash", TRASH_DEFAULTS)
    if added:
        log.info("[migration] Aufbewahrung: %s ergänzt", ", ".join(sorted(added)))
