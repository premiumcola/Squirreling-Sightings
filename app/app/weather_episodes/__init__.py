"""Storm-episode archive — the weather history's long-term memory.

``weather_history.json`` is a ROLLING 30-day window: a storm older than
that is gone permanently, and comparing this year's thunderstorms
against last year's is impossible from it. This package segments that
window into discrete EPISODES and copies each one — its curve slice,
its peaks and a comparable intensity score — into an append-only
archive that never rolls.

What an episode is:

* it STARTS when a metric crosses the threshold its event is already
  configured with (``settings.weather.events`` — the same numbers the
  live alert path fires on, never a parallel set);
* it ENDS once every metric has stayed below for ``settle_min``
  (default 30 min), so a storm that pulses stays one episode;
* it CARRIES ``pre_min`` / ``post_min`` (default 90 each) of samples
  around itself, because the build-up is the part worth studying;
* two episodes whose margins overlap are ONE episode.

Public surface::

    sweep(storage_root, rows, events_cfg=..., episode_cfg=...)
    detect_episodes(rows, events_cfg=..., episode_cfg=...)
    list_episodes(storage_root, include_samples=False)
    get_episode(storage_root, episode_id)
    patch_episode(storage_root, episode_id, fields)
    delete_episode(storage_root, episode_id)

``sweep`` is idempotent: it re-derives every episode from the full
history each call and appends only ids that are not on disk yet, so the
first call after a deploy backfills the entire window and later calls
cost nothing. See ``_archive`` for why there is no separate backfill
mode and ``_intensity`` for the score and its reference values.
"""

from __future__ import annotations

from ._archive import detect_episodes, resolve_episode_cfg, sweep
from ._consts import (
    EPISODE_DEFAULTS,
    KIND_DELETE,
    KIND_EPISODE,
    KIND_PATCH,
    PATCHABLE_FIELDS,
    USER_CLASSES,
    USER_NAME_MAX,
    USER_NOTE_MAX,
)
from ._intensity import axis_scores, intensity_score
from ._store import (
    delete_episode,
    episodes_path,
    existing_ids,
    get_episode,
    list_episodes,
    patch_episode,
)

__all__ = [
    "EPISODE_DEFAULTS",
    "KIND_DELETE",
    "KIND_EPISODE",
    "KIND_PATCH",
    "PATCHABLE_FIELDS",
    "USER_CLASSES",
    "USER_NAME_MAX",
    "USER_NOTE_MAX",
    "axis_scores",
    "delete_episode",
    "detect_episodes",
    "episodes_path",
    "existing_ids",
    "get_episode",
    "intensity_score",
    "list_episodes",
    "patch_episode",
    "resolve_episode_cfg",
    "sweep",
]
