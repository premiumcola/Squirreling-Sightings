"""Shared model-input preparation for every detector tier.

Lives in its own module because more than one stage needs it: the COCO
detector letterboxes today, and the second-stage classifiers are meant to
follow. Two copies of this transform would be a parallel implementation —
and a silently divergent one, since the inverse transform in the caller
has to match the forward transform exactly.
"""

from __future__ import annotations

import cv2
import numpy as np

# Neutral grey used by the YOLO / COCO training pipelines for padding.
# Black bars would read as real image content at the border and pull
# edge-sensitive filters; 114 is what the models saw during training.
_PAD_VALUE = 114


def letterbox(
    img: np.ndarray,
    dst_w: int,
    dst_h: int,
) -> tuple[np.ndarray, float, int, int]:
    """Fit `img` into a `dst_w x dst_h` canvas without distorting aspect.

    A plain ``cv2.resize(img, (dst_w, dst_h))`` stretches a 16:9 frame
    into a square model input — bodies get horizontally compressed and
    the SSD confidence collapses (a clearly-visible person scored
    0.28-0.44 in a live test). Letterboxing scales by
    ``scale = min(dst_w/w, dst_h/h)`` so neither axis is squashed, then
    pads the unused edges with the neutral grey 114.

    Returns ``(canvas, scale, pad_x, pad_y)``; callers invert the
    transform back to frame-space pixel coordinates with:

        x_frame = (x_model_px - pad_x) / scale
        y_frame = (y_model_px - pad_y) / scale
    """
    h, w = img.shape[:2]
    scale = min(dst_w / float(w), dst_h / float(h))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_x = (dst_w - new_w) // 2
    pad_y = (dst_h - new_h) // 2
    canvas = np.full((dst_h, dst_w, 3), _PAD_VALUE, dtype=resized.dtype)
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y
