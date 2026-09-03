"""Output-box geometry, shared by both encoders.

Both the ffmpeg path and the OpenCV fallback have to agree on the output
box and on what happens to a frame that does not match it, or the same
window would come out differently depending on which encoder ran.
"""

from __future__ import annotations

import cv2
import numpy as np

# Maximum output width for timelapse videos. 4K source frames are downscaled to this
# width to keep file sizes manageable for mobile/web playback.
_MAX_OUTPUT_WIDTH = 1920


def scale_dims(w: int, h: int, max_w: int = _MAX_OUTPUT_WIDTH) -> tuple[int, int]:
    """Return output (w, h) capped at max_w, height always divisible by 2 (H.264 req)."""
    if w <= max_w:
        # Still ensure even dimensions
        return (w // 2 * 2, h // 2 * 2)
    scale = max_w / w
    return (max_w, int(h * scale) // 2 * 2)


def fit_into_box(img, out_w: int, out_h: int):
    """Scale ``img`` into ``out_w x out_h`` without distorting its aspect.

    The pixel-exact twin of the ffmpeg filter the other encoder uses,
    ``scale=W:H:force_original_aspect_ratio=decrease`` followed by
    ``pad=W:H:(ow-iw)/2:(oh-ih)/2:black``: scale by the smaller of the
    two ratios, then centre the result on a black canvas.

    Deliberately not ``detectors._preprocess.letterbox``. That one pads
    with the neutral grey 114 the detector models were trained on and
    also returns the inverse-transform metadata a box-coordinate mapper
    needs. A video frame has to match the ffmpeg path's BLACK bars, or
    the same timelapse would gain grey bars on a host without ffmpeg and
    black ones everywhere else.
    """
    h, w = img.shape[:2]
    scale = min(out_w / float(w), out_h / float(h))
    new_w = max(1, min(out_w, int(round(w * scale))))
    new_h = max(1, min(out_h, int(round(h * scale))))
    resized = cv2.resize(img, (new_w, new_h))
    if (new_w, new_h) == (out_w, out_h):
        return resized
    canvas = np.zeros((out_h, out_w, 3), dtype=resized.dtype)
    pad_x = (out_w - new_w) // 2
    pad_y = (out_h - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas
