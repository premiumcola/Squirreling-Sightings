"""The transport itself: one message out, and the two ways in.

Split out of `_outbound/__init__.py` (far past the 500-line file budget).
Everything above this layer — event alerts, scheduled jobs, quest and
timelapse notices — ends up calling `send()`, and nothing in here knows
what an event is. `dispatch_send` (`_payload.py`) builds the payload,
`send_with_retry` (`_retry.py`) bounds the attempts; this module owns the
markup, the caption and the dispatch onto the send loop.
"""

from __future__ import annotations

import asyncio
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ...telegram_helpers import truncate_caption
from .._consts import PERSISTENT_KEYBOARD, log
from ._payload import dispatch_send
from ._retry import send_with_retry


class SendMixin:
    """Low-level send for TelegramService. Mixin — reads shared state via
    `self.*` (bot, chat_id, enabled, _loop), which lives on the concrete
    class."""

    def send(self, text: str, **kwargs):
        """Sync entry point — schedules send_alert on the dedicated loop.

        Returns the concurrent.futures.Future so callers can wait if they
        care; most fire-and-forget code ignores it."""
        if not self.enabled or not self._loop:
            log.debug("[tg] send skipped (enabled=%s, loop=%s)", self.enabled, bool(self._loop))
            return None
        try:
            return asyncio.run_coroutine_threadsafe(self.send_alert(text, **kwargs), self._loop)
        except Exception as e:
            log.error("[tg] send dispatch failed: %s", e)
            return None

    def _build_markup(self, buttons) -> InlineKeyboardMarkup | None:
        """Buttons spec: list[list[(label, data_or_url)]] → InlineKeyboardMarkup.

        URLs are detected by 'http://' / 'https://' prefix on the second
        tuple element; everything else becomes callback_data."""
        if not buttons:
            return None
        rows = []
        for row in buttons:
            built_row = []
            for entry in row:
                if not entry or len(entry) < 2:
                    continue
                label, payload = entry[0], entry[1]
                if isinstance(payload, str) and (
                    payload.startswith("http://") or payload.startswith("https://")
                ):
                    built_row.append(InlineKeyboardButton(label, url=payload))
                else:
                    # Telegram callback_data hard limit: 64 bytes.
                    cb = str(payload)[:64]
                    built_row.append(InlineKeyboardButton(label, callback_data=cb))
            if built_row:
                rows.append(built_row)
        return InlineKeyboardMarkup(rows) if rows else None

    async def send_alert(
        self,
        text: str = "",
        *,
        photo=None,
        video=None,
        buttons=None,
        parse_mode: str = "HTML",
        silent: bool = False,
        dark: bool = False,
        reply_to: int | None = None,
    ):
        """Unified send. `photo`/`video` accept bytes or a filesystem path.
        Auto-falls-back to sendDocument when limits are exceeded.

        Transient failures — flood control (429) and network drops — get
        exactly one retry each via send_with_retry. Anything else is
        logged and dropped: callers discard the Future, so there is
        nobody upstream to raise to. Dropping it silently was the
        remaining half of that problem — the failure is now counted and
        the traceback kept, so `get_polling_status()` can say that sends
        are failing while polling looks perfectly healthy."""
        if not self.enabled or not self.bot:
            log.info(
                "[tg] send_alert skipped (enabled=%s, bot=%s)", self.enabled, self.bot is not None
            )
            return
        if dark:
            log.info("[tg] dark/night alert")
        # Inline buttons win — Telegram only allows one reply_markup per
        # message, so when an alert carries Gültig/Falsch/Stumm we send those
        # and the persistent reply keyboard stays visible from the previous
        # message. When no inline buttons are present, reattach the
        # persistent keyboard so it always appears under the input field.
        markup = self._build_markup(buttons)
        if markup is None:
            markup = PERSISTENT_KEYBOARD
        common = dict(chat_id=self.chat_id, reply_markup=markup, disable_notification=bool(silent))
        if parse_mode:
            common["parse_mode"] = parse_mode
        if reply_to:
            common["reply_to_message_id"] = reply_to
        caption = truncate_caption(text or "")
        try:
            msg = await send_with_retry(
                lambda: dispatch_send(
                    self.bot,
                    text=text,
                    photo=photo,
                    video=video,
                    caption=caption,
                    common=common,
                )
            )
        except Exception as e:
            # getattr defaults rather than __init__ state: the counter has
            # to survive on service instances that predate it, and every
            # test builds its state by hand.
            self._send_failures = getattr(self, "_send_failures", 0) + 1
            self._last_send_error = f"{type(e).__name__}: {e}"
            log.error(
                "[tg] send_alert failed (%d since start): %s",
                self._send_failures,
                e,
                exc_info=True,
            )
            return None
        # Stash timestamp of the most recent successful push so the
        # /api/system/telegram health endpoint can surface "letzte
        # Push vor X Min" without scraping the polling state.
        self._last_push_ts = time.time()
        log.info("[tg] send_alert ok (chat=%s silent=%s)", self.chat_id, silent)
        return msg

    # Legacy sync wrapper (kept for the achievement push and the test endpoint).
    # Footer buttons used to include "24 h Zeitraffer" and "Last detections"
    # but those are reachable via /menu and only added clutter to event
    # bubbles. Callback strings now match the cam:<id>:* dispatcher so the
    # buttons actually route — the old "snapshot:<id>" / "clip:<id>" prefixes
    # were never registered and silently no-op'd on click.
    def send_alert_sync(
        self,
        caption: str,
        jpeg_bytes: bytes | None = None,
        snapshot_url: str | None = None,
        dashboard_url: str | None = None,
        camera_id: str | None = None,
    ):
        if not self.enabled:
            return
        buttons = []
        if camera_id:
            buttons.append(
                [
                    ("📷 Livebild", f"cam:{camera_id}:livebild"[:64]),
                    ("🎬 5 s Clip", f"cam:{camera_id}:clip:5"[:64]),
                ]
            )
        if dashboard_url:
            buttons.append([("🖥 Dashboard", dashboard_url)])
        self.send(caption, photo=jpeg_bytes, buttons=buttons, parse_mode=None)
