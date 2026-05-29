"""SIM-only thin layer over the shared tiling helpers (detection_tiling).

The reusable tiling / NMS / motion-ROI core now lives in
``app/app/detection_tiling.py`` so the production pipeline (D2) and this sim
endpoint share one implementation. This module re-exports those names for the
existing sim callsite (routes/coral_test_detection.py) and adds the only
sim-specific bit: the human-readable SAHI decision-trace line.
"""

from __future__ import annotations

from ..detection_tiling import (
    VALID_MODES,
    motion_bbox,
    nms_merge,
    prep_gray,
    tile_regions,
    tiled_detect,
)

__all__ = [
    "VALID_MODES",
    "motion_bbox",
    "nms_merge",
    "prep_gray",
    "sahi_trace_line",
    "tile_regions",
    "tiled_detect",
]


def sahi_trace_line(diag: dict) -> str | None:
    """Render the M4 SAHI diag line for the decision-trace block, or None
    when tiling is off (nothing extra to report)."""
    mode = diag.get("mode", "off")
    if mode == "off":
        return None
    label = {"2x2": "2×2", "3x3": "3×3", "roi": "ROI"}.get(mode, mode)
    return (
        f"[sahi] {label} +full · roh {diag.get('raw', 0)} → "
        f"nach NMS {diag.get('merged', 0)} · Kachel-Treffer {diag.get('tile_hits', [])}"
    )
