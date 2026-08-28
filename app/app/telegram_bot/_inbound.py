from __future__ import annotations

# ruff: noqa: F401
# Comprehensive per-mixin import block — kept identical across mixins so
# methods can move between them without import bookkeeping. See
# service.py for the canonical import list.
import asyncio
import contextlib
import logging
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Lock, Thread

from telegram import (
    Bot,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..telegram_helpers import (
    DULL_BIRDS,
    LABEL_DE,
    LABEL_WEIGHT,
    OBJECT_LABELS,
    is_night,
    is_quiet_now,
    most_specific_label,
    truncate_caption,
)
from ._consts import (
    _MUTE_DEFAULT_S,
    _MUTE_EXTEND_S,
    _NOTIFY_COOLDOWN_DEFAULTS,
    _PHOTO_LIMIT_BYTES,
    _VIDEO_LIMIT_BYTES,
    ACTION_CAMS,
    ACTION_CLIP,
    ACTION_LIVE,
    ACTION_MENU,
    ACTION_MUTE,
    ACTION_STATUS,
    ANCHOR_KEY,
    BOT_COMMANDS,
    PERSISTENT_KB_KEY,
    PERSISTENT_KEYBOARD,
    _parse_hhmm,
    log,
)


class InboundMixin:
    """Slash-command dispatchers + callback_query handlers + per-action helpers.

    Mixin for TelegramService. Methods access shared state via `self.*`
    (cfg, bot, store, runtimes, scheduler, etc.) which live on the
    concrete class.
    """

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Open or refresh the anchor bubble. /start, /menu, and the
        '🏠 Menü' reply-keyboard text all flow through here. No textual
        follow-up — the persistent keyboard sticks server-side once the
        first anchor has been sent with it attached."""
        self.log_action("menu_open")
        chat_id = update.effective_chat.id if update.effective_chat else self.chat_id
        try:
            await self._anchor_send_or_edit(context.bot, chat_id, self._root_view())
        except Exception as e:
            log.warning("[tg] anchor open failed: %s", e)
            text, markup = self._root_view()
            await update.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode="HTML",
            )

    async def cmd_today(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text, markup = self._stats_view(days=1)
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    async def cmd_week(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text, markup = self._stats_view(days=7)
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    # ── Reply-keyboard + slash-command action handlers ────────────────────
    # Single source of truth for the four top-level actions: each helper
    # accepts (update, context) and is reachable from BOTH the persistent
    # keyboard text dispatch (on_text) and the slash commands. The three
    # camera ones — livebild, clip, cameras — live in `_inbound_camera`
    # beside the `cam:*` dispatch their pickers route through, so
    # snapshot and clip still have exactly one implementation.

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Compact system overview: cams + Telegram polling + Coral + weather + storage."""
        log.info(
            "[tg] /status invoked by chat=%s",
            update.effective_chat.id if update.effective_chat else "?",
        )
        try:
            text = self._render_system_status_text()
        except Exception as e:
            log.warning("[tg] status render failed: %s", e)
            text = "Status nicht verfügbar."
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=PERSISTENT_KEYBOARD)

    async def _handle_mute_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set runtime.global_mute_until = now + 1 h and reply with a confirm
        bubble carrying two inline buttons (end-now / extend-to-4h)."""
        log.info(
            "[tg] /mute invoked by chat=%s",
            update.effective_chat.id if update.effective_chat else "?",
        )
        until = time.time() + _MUTE_DEFAULT_S
        if self.settings_store:
            self.settings_store.runtime_set("global_mute_until", until)
        end_local = datetime.fromtimestamp(until).strftime("%H:%M")
        log.info("[tg] mute_all activated until %s (epoch=%d)", end_local, int(until))
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Sofort beenden", callback_data="mute:end"),
                    InlineKeyboardButton("Auf 4 h verlängern", callback_data="mute:ext4h"),
                ],
            ]
        )
        await update.message.reply_text(
            f"🔇 Alle Pushes pausiert bis <b>{end_local}</b>",
            parse_mode="HTML",
            reply_markup=markup,
        )

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """MessageHandler for free-form text. The persistent keyboard now has
        only one button (🏠 Menü) which routes through cmd_menu; legacy
        button labels (still occasionally surfaced by old chat clients)
        keep their handlers as a courtesy."""
        if not update.message or not update.message.text:
            return
        txt = update.message.text.strip()
        if txt == ACTION_MENU:
            await self.cmd_menu(update, context)
            return
        # Legacy button labels — kept reachable so old clients with the
        # 5-button keyboard cached don't suddenly see "💡 Tipp" replies.
        legacy_map = {
            ACTION_LIVE: self._handle_livebild,
            ACTION_CLIP: self._handle_clip5,
            ACTION_STATUS: self._handle_status,
            ACTION_MUTE: self._handle_mute_all,
            ACTION_CAMS: self._handle_cameras,
        }
        handler = legacy_map.get(txt)
        if handler:
            await handler(update, context)
            return
        # Anything else: silent. The user explicitly didn't want a
        # "💡 Tipp" follow-up cluttering the chat for arbitrary text.

    # ── Callback router ───────────────────────────────────────────────────
    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        data = q.data or ""
        if data == "noop":
            await q.answer()
            return
        # Push-system prefixes (Phase 1)
        if data.startswith("ev:"):
            await self._handle_event_cb(q, data)
            return
        if data.startswith("hi:") or data.startswith("share:"):
            await self._handle_highlight_cb(q, data)
            return
        # Global mute control (set from /mute or the "Alles still 1 h" button).
        if data.startswith("mute:"):
            await self._handle_mute_cb(q, data)
            return
        # Timelapse: tl:send:<rel>  or  tl:save:<rel>
        if data.startswith("tl:"):
            await self._handle_timelapse_cb(q, data, context)
            return
        # Camera actions: cam:<id>:<verb>[:arg]
        if data.startswith("cam:"):
            await self._handle_camera_cb(q, data, context)
            return
        # Multi-level menu navigation
        if data.startswith("menu:"):
            await self._handle_menu_cb(q, data)
            return
        # Erkennungen tile (phase-2): pagination, filter sub-view, filter
        # setters, apply. Routed through _handle_menu_cb because the
        # tile renders edit-in-place via the same anchor pattern as
        # menu:* views.
        if data.startswith("det:"):
            await self._handle_menu_cb(q, data)
            return
        await q.answer()

    async def _handle_mute_cb(self, q, data: str):
        """mute:end → clear global mute. mute:ext4h → push end-time to now+4h."""
        if not self.settings_store:
            await q.answer()
            return
        verb = data.split(":", 1)[1] if ":" in data else ""
        if verb == "end":
            self.settings_store.runtime_set("global_mute_until", 0)
            log.info("[tg] mute_all cleared by chat=%s", q.message.chat_id if q.message else "?")
            await self._set_badge(q, "✅ Pushes wieder aktiv")
            await q.answer("✅ Pushes wieder aktiv")
            return
        if verb == "ext4h":
            until = time.time() + _MUTE_EXTEND_S
            self.settings_store.runtime_set("global_mute_until", until)
            end_local = datetime.fromtimestamp(until).strftime("%H:%M")
            log.info("[tg] mute_all extended to 4 h (until=%s)", end_local)
            await self._set_badge(q, f"🔇 Stumm bis {end_local}")
            await q.answer(f"🔇 Stumm bis {end_local}")
            return
        await q.answer()

    async def _handle_highlight_cb(self, q, data: str):
        # hi:<eid>     → original-resolution snapshot (uncompressed sendDocument)
        # share:<eid>  → forward-friendly photo + plain caption (no buttons)
        parts = data.split(":", 1)
        kind = parts[0]
        eid = parts[1] if len(parts) > 1 else ""
        ss = self.settings_store
        if not eid or not ss:
            await q.answer()
            return
        idx = ss.runtime_get_subkey("alert_index", eid) or {}
        cam_id = idx.get("cam") or ""
        snap_path = None
        if cam_id and self.store:
            ev = self.store.get_event(cam_id, eid) if hasattr(self.store, "get_event") else None
            rel = (ev or {}).get("snapshot_relpath")
            if rel:
                p = self._storage_root() / rel
                if p.exists():
                    snap_path = p
        if not snap_path:
            await q.answer("Original nicht mehr vorhanden.")
            return
        await q.answer("Wird gesendet…")
        try:
            with open(snap_path, "rb") as f:
                if kind == "hi":
                    # sendDocument keeps full resolution (sendPhoto would
                    # downscale to 1280 long-edge).
                    await q.message.reply_document(
                        document=f, filename=snap_path.name, caption=f"🖼 {snap_path.name}"
                    )
                else:
                    await q.message.reply_photo(photo=f, caption=f"📤 {snap_path.name}")
        except Exception as e:
            log.warning("[tg] highlight send failed: %s", e)

    async def _handle_timelapse_cb(self, q, data: str, context):
        # tl:send:<cam>/<filename>  → reply with the mp4
        # tl:save:<rel>             → ack (Telegram retains it in chat history)
        rest = data[3:]  # strip "tl:"
        if rest.startswith("send:"):
            rel = rest[5:]
            full = self._storage_root() / "timelapse" / rel
            if not full.exists():
                await q.answer("Datei nicht mehr vorhanden")
                return
            await q.answer("Wird gesendet…")
            try:
                with open(full, "rb") as f:
                    await context.bot.send_video(
                        chat_id=q.message.chat_id,
                        video=f,
                        caption=f"⏱ {rel}",
                    )
            except Exception as e:
                log.warning("[tg] tl send failed: %s", e)
                await q.message.reply_text(f"Senden fehlgeschlagen: {e}")
            return
        if rest.startswith("save:"):
            await q.answer("Bereits im Chat-Verlauf gespeichert.")
            return
        await q.answer()

    async def _handle_menu_cb(self, q, data: str):
        """Routes every menu:* callback. View functions return (text, markup);
        we render in the same bubble via edit_message_text."""
        self.log_action("menu_" + data.split(":", 1)[1])
        if data == "menu:root":
            await self._render_view(q, self._root_view())
            await q.answer()
            return
        if data == "menu:livebild":
            await self._render_view(q, self._cam_picker("livebild"))
            await q.answer()
            return
        if data == "menu:clip":
            await self._render_view(q, self._cam_picker("clip"))
            await q.answer()
            return
        if data == "menu:cams":
            await self._render_view(q, self._cam_picker("drilldown"))
            await q.answer()
            return
        if data == "menu:zeitraffer":
            await self._render_view(q, self._zeitraffer_view())
            await q.answer()
            return
        if data == "menu:zeitraffer:today":
            # Pick the newest of today's timelapses across cameras.
            today_pref = datetime.now().strftime("%Y-%m-%d")
            tls = [
                t
                for t in self._list_recent_timelapses(limit=20)
                if datetime.fromtimestamp(t["mtime"]).strftime("%Y-%m-%d") == today_pref
            ]
            if not tls:
                await q.answer("Heute kein Zeitraffer vorhanden.")
                return
            top = tls[0]
            full = self._storage_root() / "timelapse" / top["cam_id"] / top["filename"]
            try:
                with open(full, "rb") as f:
                    await q.message.reply_video(video=f, caption=f"⏱ {top['cam_id']} · heute")
            except Exception as e:
                log.warning("[tg] today timelapse send failed: %s", e)
            await q.answer()
            return
        if data == "menu:erkennungen":
            chat_id = q.message.chat_id if q.message else None
            st = self._tile_state_for(chat_id)
            await self._render_view(
                q,
                self._erkennungen_view(
                    filter_cam=st.get("det_cam"), filter_kind=st.get("det_kind"), page=0
                ),
            )
            await q.answer()
            return
        # Erkennungen pagination + filter sub-view + filter-state setters.
        if data.startswith("det:page:"):
            try:
                page = int(data.split(":")[-1])
            except ValueError:
                page = 0
            chat_id = q.message.chat_id if q.message else None
            st = self._tile_state_for(chat_id)
            await self._render_view(
                q,
                self._erkennungen_view(
                    filter_cam=st.get("det_cam"), filter_kind=st.get("det_kind"), page=page
                ),
            )
            await q.answer()
            return
        if data == "det:filter":
            chat_id = q.message.chat_id if q.message else None
            await self._render_view(q, self._erkennungen_filter_view(chat_id))
            await q.answer()
            return
        if data.startswith("det:setcam:"):
            chat_id = q.message.chat_id if q.message else None
            st = self._tile_state_for(chat_id)
            sel = data.split(":", 2)[2]
            st["det_cam"] = None if sel == "_all" else sel
            await self._render_view(q, self._erkennungen_filter_view(chat_id))
            await q.answer()
            return
        if data.startswith("det:setkind:"):
            chat_id = q.message.chat_id if q.message else None
            st = self._tile_state_for(chat_id)
            sel = data.split(":", 2)[2]
            st["det_kind"] = None if sel == "_all" else sel
            await self._render_view(q, self._erkennungen_filter_view(chat_id))
            await q.answer()
            return
        if data == "det:apply":
            chat_id = q.message.chat_id if q.message else None
            st = self._tile_state_for(chat_id)
            await self._render_view(
                q,
                self._erkennungen_view(
                    filter_cam=st.get("det_cam"), filter_kind=st.get("det_kind"), page=0
                ),
            )
            await q.answer()
            return
        if data == "menu:stats" or data == "menu:stats:today":
            await self._render_view(q, self._stats_view(days=1))
            await q.answer()
            return
        if data == "menu:stats:week":
            await self._render_view(q, self._stats_view(days=7))
            await q.answer()
            return
        if data == "menu:stats:month":
            await self._render_view(q, self._stats_view(days=30))
            await q.answer()
            return
        if data == "menu:status":
            await self._render_view(q, self._status_view())
            await q.answer()
            return
        if data == "menu:logs":
            await self._render_view(q, self._logs_view())
            await q.answer()
            return
        # Phase-1 stubs: tiles routed end-to-end so the navigation feels
        # complete even though the detail content lands in phase-2.
        if data == "menu:tierlog":
            await self._render_view(q, self._tier_log_view())
            await q.answer()
            return
        if data == "menu:wetter":
            await self._render_view(q, self._wetter_view())
            await q.answer()
            return
        if data == "menu:system":
            await self._render_view(q, self._system_view())
            await q.answer()
            return
        if data == "menu:muteall":
            # Same effect as the /mute command, but renders inside the
            # anchor and snaps back to root afterwards.
            until = time.time() + _MUTE_DEFAULT_S
            if self.settings_store:
                with contextlib.suppress(Exception):
                    self.settings_store.runtime_set("global_mute_until", until)
            end_local = datetime.fromtimestamp(until).strftime("%H:%M")
            log.info("[tg] mute_all activated until %s via menu", end_local)
            await self._render_view(q, self._root_view())
            await q.answer(f"🔇 Alle Pushes pausiert bis {end_local}")
            return
        await q.answer()
