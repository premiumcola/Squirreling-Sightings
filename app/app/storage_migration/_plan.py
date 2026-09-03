"""Pass 1: work out what each camera needs, touching no disk state."""

from __future__ import annotations

from pathlib import Path

from ..camera_id import _sanitise, build_camera_id
from ._consts import _AREAS
from ._naming import _extract_host, _folder_matches, _ip_dashes, _ip_last_octet


def _plan_camera(cam: dict, storage_root: Path) -> dict:
    """Pure analysis pass — returns the planned actions for one camera
    without touching disk. The caller decides whether to execute.

    Returned dict::

        {
          "old_id":    str,
          "new_id":    str,
          "id_changed": bool,
          "areas": {
            "motion_detection": [Path, ...],
            "timelapse_frames": [...], ...
          }
        }

    A camera is "in canonical form" when ``id_changed=False`` AND every
    ``areas[*]`` list either is empty or only contains the target dir."""
    old_id = cam.get("id", "")
    name = cam.get("name", old_id)
    host = _extract_host(cam.get("rtsp_url", ""))
    ip_octet = _ip_last_octet(host)
    ip_dashes = _ip_dashes(host)
    name_slug = _sanitise(name)
    new_id = build_camera_id(
        cam.get("manufacturer", ""),
        cam.get("model", ""),
        name,
        host,
    )
    out = {
        "old_id": old_id,
        "new_id": new_id,
        "id_changed": new_id != old_id,
        "ip_dashes": ip_dashes,
        "areas": {a: [] for a in _AREAS},
    }
    for area in _AREAS:
        area_root = storage_root / area
        if not area_root.exists():
            continue
        for child in area_root.iterdir():
            if not child.is_dir():
                continue
            if child.name == new_id:
                continue  # already at the canonical target
            if _folder_matches(
                child.name,
                current_id=old_id,
                ip_dashes=ip_dashes,
                ip_octet=ip_octet,
                name_slug=name_slug,
            ):
                out["areas"][area].append(child)
    return out
