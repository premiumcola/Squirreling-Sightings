"""The filmstrip behind the player's scrub preview.

One JPEG per clip holding N evenly-spaced frames in a grid, plus the
geometry needed to address them. The player shows a tile by shifting a
background-position — no video decoding, no second request per frame.

WHY A SPRITE SHEET AND NOT LIVE FRAMES. The obvious implementation is a
hidden second ``<video>`` that the browser seeks and paints to a canvas
while the operator drags. It works on a desktop and it does not work on
iOS: Safari limits how many videos decode at once, seeking is slow enough
to feel broken under a finger, and a video that has not played inline
cannot reliably be drawn to a canvas at all. A sprite sheet is an
``<img>``. It behaves identically on a phone and on a desktop because
there is nothing video about it.

WHY IT LIVES BESIDE THE CLIP AND NOT IN A SIDECAR FILE. The geometry
(grid, count, interval) goes on the EVENT JSON, which the library already
sends with every item. A separate ``<id>.scrub.json`` would be a second
request per open for four numbers, and a second thing to keep in step
with the picture it describes.

COST. One sequential pass over the finished mp4 with cv2, reading every
Nth frame — the same library and the same kind of work as the existing
single-frame thumbnail, one step further. It runs inside the re-encode
thread that is already running, after the clip is playable, so it can
never delay the moment the operator can watch it.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path, PurePosixPath

import cv2
import numpy as np

log = logging.getLogger("app.camera_runtime")

#: Frames per second of clip. Two is what a short motion clip wants: the
#: question being answered while dragging is "is the animal on this one",
#: and half-second granularity answers it without a sheet nobody needs.
DEFAULT_FPS = 2.0

#: Width of one tile. 240 px is legible on a phone at roughly half the
#: screen and still only a few KB per frame.
TILE_W = 240

#: Hard ceiling on tiles per sheet. A 120 s clip at 2/s would be 240
#: tiles; past this the interval widens instead, so the sheet's pixel
#: size and decode cost stay bounded no matter how long the clip is.
MAX_TILES = 120

#: JPEG quality. These are 240 px wide and only ever seen in motion under
#: a finger, so quality buys nothing above this and costs bytes.
JPEG_Q = 70


#: Sub-folder the sheets live in, one per day directory.
SPRITE_DIR = "scrub"


def sprite_path_for(video_path: Path) -> Path:
    """``<day>/<id>.mp4`` → ``<day>/scrub/<id>.jpg``.

    IN ITS OWN FOLDER, not beside the clip as ``<id>.scrub.jpg``. That is
    where it started, and it was wrong: several readers in this tree pick
    "the first ``*.jpg`` in the event's directory" as a preview when the
    manifest has no explicit one, and a sprite sheet answering that
    question puts a grid of forty postage stamps on a media card. The
    operator saw exactly that, across the whole Mediathek, the moment the
    backfill ran.

    Excluding the name at each of those readers would be a list to keep
    in step for ever; a directory they do not walk cannot be got wrong.
    The stem still matches the clip, so everything belonging to one event
    is still findable as a unit.
    """
    return video_path.parent / SPRITE_DIR / f"{video_path.stem}.jpg"


def sprite_relpath_for(video_relpath: str) -> str:
    """The same mapping, on the RELATIVE path the event JSON stores.

    ``motion_detection/<cam>/<day>/<id>.mp4``
      → ``motion_detection/<cam>/<day>/scrub/<id>.jpg``

    The layout lives in this module and nowhere else. The player needs a
    URL for the filmstrip, and the two obvious places to put one were
    both worse: writing it onto the event at build time leaves every clip
    recorded before that commit without a preview for ever, and deriving
    it in JavaScript copies the storage layout into the browser, where
    the next change to it would silently stop matching.

    Derived on read instead, from a path the event already has — so an
    archive of existing clips gains previews the moment their sheets are
    backfilled, with no migration.

    Returns "" for anything that is not a clip path.
    """
    if not video_relpath:
        return ""
    p = PurePosixPath(str(video_relpath))
    if not p.name or not p.suffix:
        return ""
    return str(p.parent / SPRITE_DIR / f"{p.stem}.jpg")


def legacy_sprite_path_for(video_path: Path) -> Path:
    """Where the sheets were written before they moved.

    Kept only so the backfill can clean them up — see
    ``migrations.generate_missing_scrub_sprites``.
    """
    return video_path.with_suffix("").with_suffix(".scrub.jpg")


def _plan(total_frames: int, src_fps: float, fps: float) -> tuple[int, int]:
    """``(stride, count)`` — how many frames to take and how far apart.

    Widens the stride rather than dropping the tail when a clip is long
    enough to exceed MAX_TILES: a filmstrip that silently stops halfway
    through the clip is worse than a coarser one that covers all of it.
    """
    if total_frames <= 0 or src_fps <= 0:
        return 0, 0
    stride = max(1, int(round(src_fps / max(0.1, fps))))
    count = max(1, math.ceil(total_frames / stride))
    if count > MAX_TILES:
        stride = math.ceil(total_frames / MAX_TILES)
        count = max(1, math.ceil(total_frames / stride))
    return stride, count


def _read_tiles(cap, stride: int, count: int, tile_w: int) -> tuple[list, int]:
    """Sequential read, keeping every ``stride``-th frame, downscaled.

    Sequential and not seek-per-tile on purpose: seeking an inter-coded
    stream costs a keyframe search per call, and reading straight through
    a 20 s clip is faster than 40 seeks into it.
    """
    tiles: list = []
    tile_h = 0
    idx = 0
    while len(tiles) < count:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if idx % stride == 0:
            h, w = frame.shape[:2]
            if w > 0 and h > 0:
                tile_h = max(1, int(round(tile_w * h / w)))
                tiles.append(cv2.resize(frame, (tile_w, tile_h)))
        idx += 1
    return tiles, tile_h


def build_scrub_sprite(
    video_path: Path,
    *,
    fps: float = DEFAULT_FPS,
    tile_w: int = TILE_W,
) -> dict | None:
    """Build the sheet for ``video_path`` and return its geometry.

    :returns: ``{"cols", "rows", "count", "interval_s", "tile_w",
        "tile_h"}`` — everything the player needs to address a tile — or
        ``None`` when the clip could not be read. Never raises: a missing
        filmstrip degrades the scrub preview and must not be able to fail
        a recording that is otherwise complete.
    """
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        stride, count = _plan(total, src_fps, fps)
        if count <= 0:
            cap.release()
            return None
        tiles, tile_h = _read_tiles(cap, stride, count, tile_w)
        cap.release()
        if not tiles:
            return None

        cols = max(1, math.ceil(math.sqrt(len(tiles))))
        rows = max(1, math.ceil(len(tiles) / cols))
        sheet = np.zeros((rows * tile_h, cols * tile_w, 3), dtype=np.uint8)
        for i, tile in enumerate(tiles):
            r, c = divmod(i, cols)
            sheet[r * tile_h : (r + 1) * tile_h, c * tile_w : (c + 1) * tile_w] = tile

        out = sprite_path_for(video_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(out), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q]):
            return None
        return {
            "cols": cols,
            "rows": rows,
            "count": len(tiles),
            # Seconds of clip per tile — what turns a drag position into a
            # tile index without the player knowing the source frame rate.
            "interval_s": round(stride / src_fps, 3) if src_fps > 0 else None,
            "tile_w": tile_w,
            "tile_h": tile_h,
        }
    except Exception as e:  # pragma: no cover - defensive, see docstring
        log.debug("[scrub] sprite for %s failed: %s", video_path.name, e)
        return None
