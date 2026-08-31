"""Backward-compatible re-export.

The date-bounded motion reader moved to ``app.library._motion_reader``
during the Mediathek + Wetter-Ereignisse merge (Stage 3): the unified
library feed (``library._feed.list_library_items``) needed the exact
same day-folder pruning that lived here, and CLAUDE.md forbids a second
copy. Existing imports of ``motion_events_between`` from this module —
including ``tests/test_weather_episode_footage.py``, which pins the
pruning behaviour by name — keep working unchanged. New code should
import from ``app.library._motion_reader`` directly.
"""

from __future__ import annotations

from ..library._motion_reader import motion_events_between

__all__ = ["motion_events_between"]
