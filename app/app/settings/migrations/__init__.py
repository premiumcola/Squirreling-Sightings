"""Boot-time migrations applied to settings.json.

Each function takes the raw ``data`` dict and mutates it in place.

The authoritative call sequence is the explicit block in
``SettingsStore.load`` — there is no registry here that gets iterated.
Adding a function to this package is NOT enough to make it run: it has
to be imported and called in ``store.load()`` as well, in a position
that respects its dependencies (``migrate_class_severity`` reads the
``alarm_profile`` that ``migrate_camera_defaults`` backfills;
``migrate_timelapse_intervals`` needs the blocks
``migrate_weather_defaults`` seeds). ``test_settings_migration_wiring``
fails if a migration defined here never gets called.

  _helpers.py    — shared merge helper
  _camera.py     — per-camera key backfills, severity, thresholds, RTSP
  _schedules.py  — the unified schedule shape
  _zones.py      — zone polygon source space
  _weather.py    — weather block + thunder LPI rescale
  _timelapse.py  — timelapse profiles + interval clamping
  _app.py        — telegram push, server location, runtime
"""

from __future__ import annotations

from ._app import (
    migrate_runtime_defaults,
    migrate_server_location_defaults,
    migrate_telegram_push_defaults,
)
from ._camera import (
    migrate_camera_defaults,
    migrate_class_severity,
    migrate_label_thresholds,
    migrate_rtsp_password_encoding,
    migrate_threshold_keys,
)
from ._schedules import migrate_alerting_schedules, migrate_schedules
from ._timelapse import migrate_timelapse_intervals, migrate_timelapse_profiles
from ._weather import migrate_thunder_lpi_scale, migrate_weather_defaults
from ._zones import _infer_zone_canvas, migrate_zone_source_space

__all__ = [
    # Private, but re-exported because test_zone_source_space drives the
    # canvas inference directly — it is the half of the migration worth
    # testing on its own.
    "_infer_zone_canvas",
    "migrate_alerting_schedules",
    "migrate_camera_defaults",
    "migrate_class_severity",
    "migrate_label_thresholds",
    "migrate_rtsp_password_encoding",
    "migrate_runtime_defaults",
    "migrate_schedules",
    "migrate_server_location_defaults",
    "migrate_telegram_push_defaults",
    "migrate_threshold_keys",
    "migrate_thunder_lpi_scale",
    "migrate_timelapse_intervals",
    "migrate_timelapse_profiles",
    "migrate_weather_defaults",
    "migrate_zone_source_space",
]
