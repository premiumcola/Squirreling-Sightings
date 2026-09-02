"""``event["provenance"]`` — everything a re-simulation needs to know
about the moment an event was produced.

The three event writers (ffmpeg stub, OpenCV fallback, snapshot camera)
already store ``recording_settings`` — six knobs of the ~thirty that
decide what a clip becomes. This snapshot is the rest: the raw tuning
the operator saved, the EFFECTIVE values after ``build_detection_setup``
resolved presets and defaults, the zone/mask polygons, which model files
ran on which device, the pre/post roll and the analysed vs source frame
rate, and which build of the app did all that.

``build_provenance`` is pure — it takes plain values and returns a dict —
so it is tested without a camera thread. ``ProvenanceMixin`` is the one
method that gathers those values off the runtime.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime

from ...detectors._describe import describe_models
from ...mask_zones import signature as _poly_signature
from ...net_archive._tuning import TUNING_LABELS_DE
from ...thresholds._apply import camera_role
from .._consts import log
from ._preroll import resolve_pre_motion_seconds

PROVENANCE_SCHEMA = 1

# Camera-level keys beyond the twelve tuning spokes that the pipeline
# reads. Stored RAW (None when absent) — ``effective`` below carries what
# the resolver made of them.
_EXTRA_TUNING_KEYS = (
    "detection_min_score",
    "label_thresholds",
    "object_filter",
    "excluded_classes",
    "confirmation_window",
    "push_thresholds",
    "wildlife_min_score",
    "hybrid_mode",
    "label_veto",
    "bottom_crop_px",
    "pre_motion_seconds",
    # The net's two per-label layers (operator pin / learner proposal) —
    # ``label_thresholds`` above is what they resolve INTO.
    "net_pin",
    "net_adapted",
    "net_auto",
)

# Every camera-level key a snapshot captures, in one name. The replay
# feature projects the stored set, the current profile and any operator
# overrides onto exactly this list before comparing them — if it drifted
# from what `_tuning` writes, "replay with the stored settings" would
# silently run with a different constellation than the one on record.
PROVENANCE_TUNING_KEYS = tuple(TUNING_LABELS_DE) + _EXTRA_TUNING_KEYS


def _short_sig(polys) -> str | None:
    if not polys:
        return None
    return hashlib.sha1(_poly_signature(polys).encode("utf-8")).hexdigest()[:12]


def _polygons(cam_cfg: dict, key: str) -> dict:
    """Count, ids and the authored polygons of ``zones`` or ``masks``."""
    items = list(cam_cfg.get(key) or [])
    ids = [
        str(it.get("id") or it.get("name") or idx)
        for idx, it in enumerate(items)
        if isinstance(it, dict)
    ]
    return {
        "count": len(items),
        "ids": ids,
        "signature": _short_sig(items),
        "polygons": items,
    }


def _effective(setup, roi_mode: str, cam_cfg: dict) -> dict:
    if setup is None:
        return {"roi_mode": roi_mode}
    out = asdict(setup)
    out.pop("camera_id", None)
    out["object_filter"] = sorted(setup.object_filter)
    out["excluded_classes"] = sorted(setup.excluded_classes)
    out["roi_mode"] = roi_mode
    out["track_filter_ghosts"] = cam_cfg.get("track_filter_ghosts") is not False
    return out


def build_provenance(
    *,
    cam_id: str,
    cam_cfg: dict,
    global_cfg: dict,
    setup=None,
    roi_mode: str = "off",
    detector=None,
    bird=None,
    wildlife=None,
    build_info: dict | None = None,
    analysed_fps: float = 0.0,
    source_fps: float = 0.0,
    captured_at: datetime | None = None,
) -> dict:
    """The snapshot. Every argument is a plain value the caller already
    holds; nothing here touches disk except the cached model hash."""
    cam_cfg = cam_cfg or {}
    global_cfg = global_cfg or {}
    proc = global_cfg.get("processing") or {}
    now = captured_at or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    tuning = {k: cam_cfg.get(k) for k in TUNING_LABELS_DE}
    tuning.update({k: cam_cfg.get(k) for k in _EXTRA_TUNING_KEYS})
    interval_ms = float(
        cam_cfg.get("frame_interval_ms") or (proc.get("motion") or {}).get("frame_interval_ms", 150)
    )
    return {
        "schema": PROVENANCE_SCHEMA,
        "captured_at": now.isoformat(timespec="seconds"),
        "timezone": {"name": now.tzname(), "utc_offset": now.strftime("%z")},
        "build": dict(build_info or {}),
        "camera": {
            "id": cam_id,
            "name": cam_cfg.get("name") or cam_id,
            "role": camera_role(cam_cfg),
            "alarm_profile": cam_cfg.get("alarm_profile"),
            "detection_trigger": cam_cfg.get("detection_trigger"),
            "resolution": cam_cfg.get("resolution"),
        },
        "tuning": tuning,
        "effective": _effective(setup, roi_mode, cam_cfg),
        "zones": _polygons(cam_cfg, "zones"),
        "masks": _polygons(cam_cfg, "masks"),
        "models": describe_models(detector, bird, wildlife),
        "timing": {
            "pre_roll_s": resolve_pre_motion_seconds(cam_cfg, global_cfg),
            "post_roll_s": float(
                cam_cfg.get("post_motion_tail_s") or proc.get("post_motion_tail_s", 3.0)
            ),
            "analysis_interval_ms": interval_ms,
            "analysed_fps": round(float(analysed_fps or 0.0), 2),
            "source_fps": round(float(source_fps or 0.0), 2),
        },
    }


class ProvenanceMixin:
    """``_build_provenance_snapshot()`` for ``CameraRuntime``."""

    def _build_provenance_snapshot(self) -> dict | None:
        """Never lets an event write fail: a broken snapshot is logged
        and stored as None rather than costing the clip."""
        try:
            from ...lifecycle import _BUILD_INFO

            return build_provenance(
                cam_id=self.camera_id,
                cam_cfg=self.cfg,
                global_cfg=self.global_cfg,
                setup=getattr(self, "detect_setup", None),
                roi_mode=self._effective_roi_mode(),
                detector=getattr(self, "detector", None),
                bird=getattr(self, "bird_classifier", None),
                wildlife=getattr(self, "wildlife_classifier", None),
                build_info=_BUILD_INFO,
                analysed_fps=getattr(self, "_main_fps", 0.0),
                source_fps=getattr(self, "_source_fps", 0.0),
            )
        except Exception as exc:  # noqa: BLE001 — provenance is a sidecar, not the event
            log.warning("[%s] provenance snapshot failed: %s", self.camera_id, exc)
            return None
