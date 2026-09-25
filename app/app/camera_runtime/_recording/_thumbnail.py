"""Das Vorschaubild eines fertigen Clips.

Aus `_finalize.py` herausgelöst, als die Datei die 500-Zeilen-Grenze
erreichte — es ist ein eigener, abgeschlossener Schritt: ein Bild aus
einer Datei holen, verkleinern, ablegen. Nichts darin braucht den
Zustand der Kamera außer ihrem Namen für das Log.
"""

from __future__ import annotations

from pathlib import Path

import cv2

from .._consts import log


def extract_motion_thumbnail(
    camera_id: str,
    thumb_source: Path | None,
    day_dir: Path,
    event_id: str,
    storage_root: Path,
    public_base: str,
) -> tuple[str | None, str | None]:
    """Grab a representative frame (~1/3 into whichever file is
    present) and downscale to max 640px wide. Returns
    ``(thumb_relpath, thumb_url)``, both None on any failure."""
    if thumb_source is None:
        return None, None
    thumb_path = day_dir / f"{event_id}.jpg"
    try:
        cap = cv2.VideoCapture(str(thumb_source))
        total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_f > 3:
            cap.set(cv2.CAP_PROP_POS_FRAMES, total_f // 3)
        ok_th, frame_th = cap.read()
        cap.release()
        if ok_th and frame_th is not None:
            tw = frame_th.shape[1]
            if tw > 640:
                scale = 640 / tw
                frame_th = cv2.resize(frame_th, (640, int(frame_th.shape[0] * scale)))
            if cv2.imwrite(str(thumb_path), frame_th, [int(cv2.IMWRITE_JPEG_QUALITY), 75]):
                thumb_rel = thumb_path.relative_to(storage_root).as_posix()
                thumb_url = (
                    f"{public_base}/media/{thumb_rel}" if public_base else f"/media/{thumb_rel}"
                )
                return thumb_rel, thumb_url
    except Exception as _te:
        log.debug("[%s] motion thumb (post-encode) failed: %s", camera_id, _te)
    return None, None
