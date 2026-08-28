"""One source of truth for what the media library contains.

Public surface only — every implementation detail lives in the
underscore modules:

``_types``      the single media-existence test (:func:`media_state`)
``_scan``       one O(N) walk per camera, classified once
``_visible``    the event list the badge AND the grid both count
``_timelapse``  registers timelapse mp4s so the two trees reconcile
``_integrity``  the read-only "Integrität prüfen" report
"""

from ._integrity import build_camera_report, build_report, probe_container
from ._scan import (
    COUNTED_TREES,
    MEDIA_TREES,
    CameraIndex,
    camera_dirs_on_disk,
    scan_camera,
    tree_size_bytes,
)
from ._timelapse import register_camera_timelapses, register_timelapse_events
from ._types import (
    MIN_VIDEO_BYTES,
    STATE_LABEL_DE,
    VISIBLE_STATES,
    has_real_media,
    is_timelapse_event,
    media_state,
    size_lookup_fs,
)
from ._visible import ALL_EVENTS, OBJECT_LABELS, camera_stats, visible_media_events

__all__ = [
    "ALL_EVENTS",
    "COUNTED_TREES",
    "MEDIA_TREES",
    "MIN_VIDEO_BYTES",
    "OBJECT_LABELS",
    "STATE_LABEL_DE",
    "VISIBLE_STATES",
    "CameraIndex",
    "build_camera_report",
    "build_report",
    "camera_dirs_on_disk",
    "camera_stats",
    "has_real_media",
    "is_timelapse_event",
    "media_state",
    "probe_container",
    "register_camera_timelapses",
    "register_timelapse_events",
    "scan_camera",
    "size_lookup_fs",
    "tree_size_bytes",
    "visible_media_events",
]
