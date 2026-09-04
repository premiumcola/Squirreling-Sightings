"""Upload payload construction plus the single outbound API call it feeds.

Split out of `_outbound/__init__.py` (which is far past the file budget)
next to `_retry.py`, because C6 turned this into a re-entrant path:
send_alert now runs it once per attempt, so building the payload and
firing the request have to sit behind one entry point. Rebuilding per
attempt is the point — a BytesIO or file handle drained by the failed
request would upload zero bytes on the retry.

The two helpers moved along with it: nothing outside this call path
used them.

Rebuilding per attempt also means the stream has to be *released* per
attempt — see `_attach`.
"""

from __future__ import annotations

import contextlib
from io import BytesIO
from pathlib import Path

from ...video_meta import video_dimensions
from .._consts import _PHOTO_LIMIT_BYTES, _VIDEO_LIMIT_BYTES, log


def _video_hints(video) -> dict:
    """``width`` / ``height`` / ``duration`` for a video we send from disk.

    Telegram guesses these when they are absent, and its guess put the
    daily timelapse on the phone in a box that was nothing like the
    camera's own shape — „Format vom gesendetem timelapse strange 😬".
    The encoder's output is correct (timelapse.py pads to the right box
    and writes setsar=1), so the fix is to stop leaving the shape to be
    inferred.

    Only for a path: an in-memory clip has no file for ffprobe to read,
    and every failure returns {} so the send proceeds exactly as before.
    ``supports_streaming`` rides along because a timelapse is played
    where it lands, not downloaded first.
    """
    if not isinstance(video, (str, Path)):
        return {}
    dims = video_dimensions(video)
    if not dims:
        return {}
    w, h, duration = dims
    hints = {"width": w, "height": h, "supports_streaming": True}
    if duration > 0:
        hints["duration"] = duration
    return hints


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


def _attach(stack: contextlib.ExitStack, src, default_name: str):
    """prepare_input plus ownership bookkeeping.

    Every stream this module *creates* — the BytesIO for raw bytes, the
    file handle for a path — is registered for close on the way out of
    dispatch_send. A value prepare_input passes through untouched still
    belongs to the caller and is left alone.

    Without this a path input leaked its handle on every attempt, and
    send_with_retry makes up to three.
    """
    stream = prepare_input(src, default_name)
    if stream is not src:
        stack.callback(stream.close)
    return stream


async def dispatch_send(bot, *, text, photo, video, caption, common):
    """One outbound Telegram call — video, photo, or plain message,
    falling back to sendDocument past Telegram's size limits.

    The upload stream lives exactly as long as the request: the stack
    unwinds once the awaited call has returned, on the failure path too,
    so a retried send never stacks handles on the same file.
    """
    if video is None and photo is None:
        return await bot.send_message(text=text or "", **common)
    with contextlib.ExitStack() as stack:
        if video is not None:
            size = src_size_bytes(video)
            src = _attach(stack, video, "video.mp4")
            if size and size > _VIDEO_LIMIT_BYTES:
                log.info("[tg] video > 50MB, falling back to sendDocument")
                return await bot.send_document(document=src, caption=caption, **common)
            # Probed BEFORE the handle is attached, from the path — the
            # stream is positioned at 0 for the upload and ffprobe reads
            # the file independently either way.
            return await bot.send_video(video=src, caption=caption, **_video_hints(video), **common)
        size = src_size_bytes(photo)
        src = _attach(stack, photo, "photo.jpg")
        if size and size > _PHOTO_LIMIT_BYTES:
            log.info("[tg] photo > 10MB, falling back to sendDocument")
            return await bot.send_document(document=src, caption=caption, **common)
        return await bot.send_photo(photo=src, caption=caption, **common)
