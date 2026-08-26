"""Upload payload construction plus the single outbound API call it feeds.

Split out of `_outbound/__init__.py` (which is far past the file budget)
next to `_retry.py`, because C6 turned this into a re-entrant path:
send_alert now runs it once per attempt, so building the payload and
firing the request have to sit behind one entry point. Rebuilding per
attempt is the point — a BytesIO or file handle drained by the failed
request would upload zero bytes on the retry.

The two helpers moved along with it: nothing outside this call path
used them.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from .._consts import _PHOTO_LIMIT_BYTES, _VIDEO_LIMIT_BYTES, log


def prepare_input(src, default_name: str):
    """Accept bytes OR a filesystem path; return something send_photo /
    send_video / send_document can swallow. Hands out a fresh stream on
    every call — see the module docstring."""
    if isinstance(src, (bytes, bytearray)):
        bio = BytesIO(bytes(src))
        bio.name = default_name
        return bio
    if isinstance(src, (str, Path)):
        return open(str(src), "rb")
    return src


def src_size_bytes(src) -> int:
    if isinstance(src, (bytes, bytearray)):
        return len(src)
    if isinstance(src, (str, Path)):
        try:
            return Path(str(src)).stat().st_size
        except Exception:
            return 0
    return 0


async def dispatch_send(bot, *, text, photo, video, caption, common):
    """One outbound Telegram call — video, photo, or plain message,
    falling back to sendDocument past Telegram's size limits."""
    if video is not None:
        size = src_size_bytes(video)
        src = prepare_input(video, "video.mp4")
        if size and size > _VIDEO_LIMIT_BYTES:
            log.info("[tg] video > 50MB, falling back to sendDocument")
            return await bot.send_document(document=src, caption=caption, **common)
        return await bot.send_video(video=src, caption=caption, **common)
    if photo is not None:
        size = src_size_bytes(photo)
        src = prepare_input(photo, "photo.jpg")
        if size and size > _PHOTO_LIMIT_BYTES:
            log.info("[tg] photo > 10MB, falling back to sendDocument")
            return await bot.send_document(document=src, caption=caption, **common)
        return await bot.send_photo(photo=src, caption=caption, **common)
    return await bot.send_message(text=text or "", **common)
