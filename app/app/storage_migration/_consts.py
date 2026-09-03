"""Constants and the logger shared across the migration package."""

from __future__ import annotations

import logging
import re

# The logger name is pinned to the module name this package replaced so
# the [migration] tag convention and existing log filters keep matching.
log = logging.getLogger("app.storage_migration")

# Regex used by the prune helper to tell timestamped migration backups
# apart from the .bak / .bak2 rotation files SettingsStore.save() owns.
# A timestamped backup looks like ``settings.json.bak.20260508_235553`` —
# 8 digits, underscore, 6 digits. The bare ``.bak`` / ``.bak2`` rotation
# files MUST NEVER be touched here; they belong to a different lifecycle.
_TIMESTAMPED_BAK_RE = re.compile(r".+\.bak\.\d{8}_\d{6}$")
_DEFAULT_BACKUP_KEEP = 10


_AREAS = ("motion_detection", "timelapse_frames", "timelapse", "weather")
