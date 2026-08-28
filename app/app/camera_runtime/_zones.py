from __future__ import annotations

# ruff: noqa: F401
# Comprehensive import block — some symbols are unused in this mixin
# but kept for parity so methods can be moved between mixins without
# import bookkeeping. Trim later if a mixin grows enough to warrant it.
import json as _json_mod
import logging
import shutil as _shutil
import subprocess as _subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests

from .. import mask_zones
from ..detection_confirmer import DetectionConfirmer
from ..detectors import (
    BirdSpeciesClassifier,
    CoralObjectDetector,
    Detection,
    WildlifeClassifier,
    draw_detections,
)
from ..event_logic import (
    choose_alarm_level,
    compute_severity_from_matrix,
    is_schedule_window_active,
    schedule_action_active,
)
from ._consts import (
    _FFMPEG_AVAILABLE,
    _PROFILE_PERIOD_DEFAULTS,
    _PROFILES,
    _SPECIES_TO_ACH_ID,
    _WILDLIFE_BBOX_DONORS,
    _bbox_iou,
    _refine_wildlife_bbox,
    _suppress_overlap,
    log,
    log_cam,
    log_tl,
)

_flatten_poly_points = mask_zones.flatten_poly_points


class ZonesMixin:
    """Inclusion/exclusion polygon helpers and detection filters.

    Mixin for CameraRuntime. The geometry itself lives in
    :mod:`app.mask_zones`; what stays here is the runtime's OWN compiled
    raster cache and the config plumbing around it. The split is not
    cosmetic: the Simulieren panel used to call these bound methods on the
    LIVE runtime, so a diagnostic tick rebuilt the alarm loop's mask cache
    underneath it. The panel now owns a separate
    :class:`~app.mask_zones.MaskZoneCache` and cannot reach any field the
    loop reads.

    ``self._mask_image`` / ``self._zone_image`` stay as attributes because
    the motion gate (``_motion.py``) reads them directly; they are now
    views onto ``self._mask_zones`` and are published image-first,
    signature-last.
    """

    @property
    def _mask_zones(self) -> mask_zones.MaskZoneCache:
        """This runtime's raster cache, created on first use.

        A property rather than an ``__init__`` assignment so a stub runtime
        in the tests (and the two mixin users that predate the cache) get
        one without having to know about it.
        """
        cache = getattr(self, "_mask_zone_cache", None)
        if cache is None:
            cache = mask_zones.MaskZoneCache()
            self._mask_zone_cache = cache
        return cache

    def _ensure_mask_image(self, log_summary: bool = False):
        """Build / refresh the binary exclusion-mask image from the camera's
        polygon list. White (255) = active detection area, black (0) = masked
        out. The image is sized 720×1280 — each frame gets resized to match
        at filter time so any frame resolution works. Rebuilds only when the
        mask config signature changes, so the per-frame filter path stays
        cheap."""
        cam_masks = self.cfg.get("masks", []) or []
        if not self._mask_zones.refresh_mask(cam_masks):
            return  # no change
        # Mirror onto the attributes the motion gate reads. Image first,
        # signature last — see mask_zones.MaskZoneCache.refresh_mask.
        self._mask_image = self._mask_zones.mask_image
        self._mask_sig = self._mask_zones.mask_sig
        if not log_summary:
            return
        if not cam_masks:
            log.info("[cam:%s] exclusion masks: none", self.camera_id)
            return
        log.info(
            "[cam:%s] Loaded %d exclusion masks (%d total vertices)",
            self.camera_id,
            len(cam_masks),
            mask_zones.authored_vertex_count(cam_masks),
        )

    def _polys_for_label(self, polys_field: str, label: str | None) -> list:
        """Return the polygons (raw [{x,y},…] lists) that apply to a label.

        A polygon applies when:
          - it has no `labels` array (or empty) → global, applies to every
            label (legacy behaviour), or
          - its `labels` array contains the given label.

        Pure-list legacy polygons ([[{x,y},…], …]) are treated as global.
        """
        cfg_list = self.cfg.get(polys_field) or []
        out: list = []
        for poly in cfg_list:
            pts = mask_zones.flatten_poly_points(poly)
            if not isinstance(pts, list) or len(pts) < 3:
                continue
            labels = (poly.get("labels") if isinstance(poly, dict) else None) or []
            if not labels or (label and label in labels):
                out.append(pts)
        return out

    @staticmethod
    def _point_in_poly(
        cx: int,
        cy: int,
        points: list,
        frame_w: int,
        frame_h: int,
        source_w: int = mask_zones.CANVAS_W,
        source_h: int = mask_zones.CANVAS_H,
    ) -> bool:
        """Thin alias onto :func:`app.mask_zones.point_in_poly`."""
        return mask_zones.point_in_poly(cx, cy, points, frame_w, frame_h, source_w, source_h)

    def _filter_masked_detections(self, frame, detections: list) -> list:
        """Drop detections whose bbox-centre lands inside a masked region."""
        if not detections:
            return detections
        cam_masks = self.cfg.get("masks") or []
        self._ensure_mask_image()
        return mask_zones.filter_masked(
            detections, frame, cam_masks, self._mask_image, self.camera_id
        )

    def _ensure_zone_image(self, log_summary: bool = False):
        """Build / refresh the inclusion-zone image. Inverse logic vs. mask:
        the canvas starts BLACK and each zone polygon is filled with WHITE,
        so a pixel inside any zone is active (detect here). When no GLOBAL
        zones are configured, _zone_image stays None and the whole frame is
        active for the motion path, which has no label context. Rebuilds
        only when the zones config signature changes."""
        cam_zones = self.cfg.get("zones", []) or []
        if not self._mask_zones.refresh_zone(cam_zones):
            return
        self._zone_image = self._mask_zones.zone_image
        self._zone_sig = self._mask_zones.zone_sig
        if not log_summary:
            return
        if self._zone_image is None:
            if cam_zones:
                log.info(
                    "[cam:%s] inclusion zones: %d label-scoped (motion path unrestricted)",
                    self.camera_id,
                    len(cam_zones),
                )
            else:
                log.info("[cam:%s] inclusion zones: none (entire frame active)", self.camera_id)
            return
        log.info(
            "[cam:%s] Loaded %d inclusion zones (%d total vertices) — outside zones = ignored",
            self.camera_id,
            len(cam_zones),
            mask_zones.authored_vertex_count(cam_zones),
        )

    def _filter_zoned_detections(self, frame, detections: list) -> list:
        """Keep only detections whose bbox-centre lands inside an applicable
        inclusion zone."""
        if not detections:
            return detections
        cam_zones = self.cfg.get("zones") or []
        if not cam_zones:
            return detections  # no zones at all → unrestricted
        self._ensure_zone_image()
        return mask_zones.filter_zoned(
            detections, frame, cam_zones, self._zone_image, self.camera_id
        )
