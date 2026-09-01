"""Cross-store read model for the unified Mediathek + Wetter-Ereignisse feed.

Stage 3 of the section merge: the Mediathek (motion-detection clip
library) and the Wetter-Ereignisse (weather sightings/recaps/manual
events/storm episodes) are becoming ONE library, default view
"everything mixed", newest first. Two later stages build the unified
card renderer and do the actual frontend section merge; this package
only has to make the backend capable of serving one merged, paginated,
filtered feed — see ``routes/library.py`` for the route.

Every reader here returns the same normalised candidate shape
``weather_episodes._footage_sources`` already established for its three
sources: ``{kind, cam_id, cam_name, start, end, video_url, thumb_url,
missing_media, extra}``. ``list_library_items`` merges across all six
kinds (motion, sighting, recap, manual, episode, timelapse) — motion and
sighting/timelapse come from ``._motion_reader`` and
``weather_episodes._footage_sources`` respectively, recap/manual/
episode from ``._weather_readers`` — sorts newest-first, and paginates
with a cursor that survives cross-source timestamp ties.

Public surface::

    list_library_items(...)
    count_library_facets(...)
    motion_events_between(...)
    motion_candidates(...)
    recap_candidates(...)
    manual_event_candidates(...)
    episode_candidates(...)
"""

from __future__ import annotations

from ._facets import count_library_facets
from ._feed import KINDS, list_library_items
from ._motion_reader import motion_candidates, motion_events_between
from ._weather_readers import episode_candidates, manual_event_candidates, recap_candidates

__all__ = [
    "KINDS",
    "count_library_facets",
    "episode_candidates",
    "list_library_items",
    "manual_event_candidates",
    "motion_candidates",
    "motion_events_between",
    "recap_candidates",
]
