"""Shared SAHI-style tiling / motion-ROI detection helpers.

Extracted from routes/_sim_tiling.py (C3) so BOTH the live-detect simulator
(routes/coral_test_detection.py) and the PRODUCTION pipeline
(camera_runtime/_main_loop.py, D2) import the same tiling + NMS code — no
duplicate implementation.

Rationale (B-experiment, storage/_diag/substream_test_*.md): full-frame
inference letterboxes the whole HD frame to the model's ~300 px input and is
blind to small/distant subjects (dog 0.00); a 2×2 / 3×3 tile pass — or a crop
of the motion ROI — feeds each region to the model at a much higher effective
resolution and recovers them (dog 0.76). Tiling is expensive, so production
runs it only on the escalated wildlife-low + coherent-motion case (D1/D2).
"""

from __future__ import annotations

import cv2
import numpy as np

from .bbox_utils import iou

VALID_MODES = ("off", "roi", "2x2", "3x3")


def tile_regions(w: int, h: int, gx: int, gy: int, overlap: float = 0.15):
    """Split a W×H frame into gx·gy overlapping tile rectangles."""
    tw, th = w / gx, h / gy
    ox, oy = int(tw * overlap), int(th * overlap)
    regions = []
    for iy in range(gy):
        for ix in range(gx):
            x1 = max(0, int(ix * tw) - ox)
            y1 = max(0, int(iy * th) - oy)
            x2 = min(w, int((ix + 1) * tw) + ox)
            y2 = min(h, int((iy + 1) * th) + oy)
            regions.append((x1, y1, x2, y2))
    return regions


def detect_region(detector, frame, region, threshold):
    """Run the detector on one cropped region; map boxes back to frame coords.
    detect_frame_raw upscales the crop to the model input internally, so a
    small subject occupies more model-input pixels than in the full frame."""
    x1, y1, x2, y2 = region
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return []
    out = []
    for d in detector.detect_frame_raw(crop, threshold=threshold):
        bx1, by1, bx2, by2 = d.bbox
        d.bbox = (bx1 + x1, by1 + y1, bx2 + x1, by2 + y1)
        out.append(d)
    return out


def nms_merge(dets, iou_thresh: float = 0.45):
    """Greedy per-label NMS — keeps the highest-scoring box of each cluster
    so a subject straddling a tile seam isn't double-counted."""
    kept = []
    for d in sorted(dets, key=lambda x: x.score, reverse=True):
        if any(d.label == k.label and iou(d.bbox, k.bbox) >= iou_thresh for k in kept):
            continue
        kept.append(d)
    return kept


def prep_gray(frame):
    """Grayscale + blur, matching the motion gate's preprocessing."""
    return cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (15, 15), 0)


def motion_bbox(prev_gray, gray, frame_area: float, min_area_frac: float = 0.0008):
    """Frame-diff motion bbox (mirrors camera_runtime/_motion.py's
    absdiff→threshold→dilate→contour recipe, at a low area floor so small
    subjects survive). Returns (x, y, w, h) or None."""
    if prev_gray is None or gray is None or prev_gray.shape != gray.shape:
        return None
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    floor = max(1.0, frame_area * min_area_frac)
    big = [c for c in contours if cv2.contourArea(c) >= floor]
    if not big:
        return None
    return tuple(int(v) for v in cv2.boundingRect(np.concatenate(big)))


def tiled_detect(detector, frame, mode: str, threshold: float = 0.20, motion_box=None):
    """Hybrid full-frame + tiling/ROI detection.

    Returns (merged_detections, diag) where diag carries the SAHI counters.
    mode: 'off' (full only) | '2x2' | '3x3' | 'roi' (motion bbox crop).
    A full-frame pass always runs and is NMS-merged with the tile/ROI hits.
    """
    h, w = frame.shape[:2]
    full = detector.detect_frame_raw(frame, threshold=threshold)
    if mode not in ("2x2", "3x3", "roi"):
        return list(full), {
            "mode": "off",
            "tiles": 0,
            "raw": len(full),
            "merged": len(full),
            "tile_hits": [],
        }

    if mode == "2x2":
        regions = tile_regions(w, h, 2, 2)
    elif mode == "3x3":
        regions = tile_regions(w, h, 3, 3)
    else:  # roi
        regions = []
        if motion_box:
            mx, my, mw, mh = motion_box
            pad = int(0.25 * max(mw, mh)) + 8
            rx1, ry1 = max(0, mx - pad), max(0, my - pad)
            rx2, ry2 = min(w, mx + mw + pad), min(h, my + mh + pad)
            if rx2 > rx1 and ry2 > ry1:
                regions = [(rx1, ry1, rx2, ry2)]

    tile_hits = []
    tiled = []
    for r in regions:
        rd = detect_region(detector, frame, r, threshold)
        tile_hits.append(len(rd))
        tiled.extend(rd)
    raw_all = list(full) + tiled
    merged = nms_merge(raw_all)
    diag = {
        "mode": mode,
        "tiles": len(regions),
        "raw": len(raw_all),
        "merged": len(merged),
        "tile_hits": tile_hits,
    }
    return merged, diag
