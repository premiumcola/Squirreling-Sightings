"""``cam:*`` — every camera action, from both surfaces.

Carved out of ``_inbound.py``, which stood 233 lines past the 500-line
file ceiling. The seam is the one the original file already documented:
the persistent keyboard's camera pickers deliberately emit
``cam:<id>:livebild`` / ``cam:<id>:clip:5`` / ``cam:<id>:drilldown``
callbacks so that snapshot and clip have exactly ONE implementation. The
pickers and that implementation now live together, which is what makes
the "no second implementation" rule visible rather than merely stated.

``_inbound.py`` keeps what is left: the slash commands, the text and
callback routers, and the mute / highlight / timelapse / menu branches.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime
from io import BytesIO

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from ._consts import (
    _MUTE_DEFAULT_S,
    PERSISTENT_KEYBOARD,
    log,
)


class CameraActionMixin:
    """Camera pickers + the ``cam:*`` callback dispatch. Mixin for
    TelegramService — shared state via ``self.*`` (runtimes, store,
    settings_store, cfg), exactly as the mixin it was split from."""

    async def _handle_livebild(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a snapshot or — when there are multiple cams — an inline
        cam picker. The picker buttons route through cam:<id>:livebild
        which the existing dispatcher already handles."""
        log.info(
            "[tg] /live invoked by chat=%s",
            update.effective_chat.id if update.effective_chat else "?",
        )
        cams = self._active_cams()
        if not cams:
            await update.message.reply_text(
                "Keine Kameras konfiguriert.", reply_markup=PERSISTENT_KEYBOARD
            )
            return
        if len(cams) == 1:
            info = cams[0]
            icon = self._cam_status_icon_for(info)
            text, markup = (
                "📷 Kamera wählen — livebild",
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                f"{icon} {info['name']}",
                                callback_data=f"cam:{info['cam_id']}:livebild"[:64],
                            )
                        ],
                    ]
                ),
            )
            await update.message.reply_text(text, reply_markup=markup)
            return
        text, markup = self._cam_picker("livebild")
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

    async def _handle_clip5(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """5-s clip cam picker. We deliberately don't offer 'all cams' —
        running 4 ad-hoc ffmpeg recordings in parallel pegs the host."""
        log.info(
            "[tg] /clip invoked by chat=%s",
            update.effective_chat.id if update.effective_chat else "?",
        )
        cams = self._active_cams()
        if not cams:
            await update.message.reply_text(
                "Keine Kameras konfiguriert.", reply_markup=PERSISTENT_KEYBOARD
            )
            return
        rows = []
        for info in cams:
            icon = self._cam_status_icon_for(info)
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{icon} 🎬 {info['name']}",
                        callback_data=f"cam:{info['cam_id']}:clip:5"[:64],
                    )
                ]
            )
        await update.message.reply_text(
            "🎬 Kamera wählen — 5 s Clip",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def _handle_cameras(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Per-cam drilldown picker. Tapping the persistent ``📹 Kameras``
        row sends an inline keyboard with one button per camera; tapping
        a camera opens its drilldown view via cam:<id>:drilldown."""
        log.info(
            "[tg] /cameras invoked by chat=%s",
            update.effective_chat.id if update.effective_chat else "?",
        )
        cams = self._active_cams()
        if not cams:
            await update.message.reply_text(
                "Keine Kameras konfiguriert.",
                reply_markup=PERSISTENT_KEYBOARD,
            )
            return
        rows = []
        for info in cams:
            icon = self._cam_status_icon_for(info)
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{icon} {info['name']}",
                        callback_data=f"cam:{info['cam_id']}:drilldown"[:64],
                    )
                ]
            )
        await update.message.reply_text(
            "📹 Kamera wählen",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def _handle_camera_cb(self, q, data: str, context):
        # cam:<cid>:<verb>[:<arg>]
        parts = data.split(":")
        if len(parts) < 3:
            await q.answer()
            return
        cam_id, verb = parts[1], parts[2]
        # Drilldown / status / mute1h work even when the runtime is down
        # (they don't need to talk to the camera). Render-only verbs first.
        if verb == "drilldown":
            await self._render_view(q, self._cam_drilldown_view(cam_id))
            await q.answer()
            return
        if verb == "status":
            # Phase-2 deep view replaces the phase-1 stub: cam header +
            # today's events + cam-only storage breakdown + applicable
            # health rows. Renders in-place inside the same anchor.
            await self._render_view(q, self._cam_deep_view(cam_id))
            await q.answer()
            return
        if verb == "mute1h":
            until = time.time() + _MUTE_DEFAULT_S
            if self.settings_store:
                try:
                    self.settings_store.runtime_set_subkey("cam_mute_until", cam_id, until)
                except Exception as e:
                    log.warning("[tg] per-cam mute write failed: %s", e)
            end_local = datetime.fromtimestamp(until).strftime("%H:%M")
            log.info("[tg] mute_cam %s activated until %s", cam_id, end_local)
            await self._render_view(q, self._cam_drilldown_view(cam_id))
            await q.answer(f"🔇 stumm bis {end_local}")
            return

        # Verbs that DO need a live runtime — try a restart once if missing.
        rt = self.runtimes.get(cam_id)
        if not rt:
            recovered = self._try_restart_runtime(cam_id)
            rt = self.runtimes.get(cam_id) if recovered else None
            if not rt:
                await q.answer("Kamera nicht erreichbar — Runtime startet noch.", show_alert=True)
                return
        cam_name = rt.status().get("name", cam_id)
        if verb == "livebild":
            await self._cam_send_snapshot(q, context, cam_id, rt, cam_name)
            return
        if verb == "clip":
            if len(parts) >= 4:
                # cam:<id>:clip:<sec>
                try:
                    sec = int(parts[3])
                except ValueError:
                    sec = 5
                await self._cam_send_clip(q, context, cam_id, rt, cam_name, sec)
                return
            # cam:<id>:clip → show duration picker
            await self._render_view(q, self._clip_dur_picker(cam_id))
            return
        if verb == "arm":
            await self._cam_toggle_armed(q, cam_id, cam_name)
            return
        if verb == "reconnect":
            try:
                rt.stop()
                time.sleep(0.5)
                rt.start()
                await q.answer(f"🔄 {cam_name}: Neuverbindung gestartet")
            except Exception as e:
                log.warning("[tg] reconnect failed: %s", e)
                await q.answer("Reconnect fehlgeschlagen")
            return
        await q.answer()

    async def _cam_send_snapshot(self, q, context, cam_id, rt, cam_name):
        await q.answer("📷 Snapshot wird geholt…")
        log.info(
            "[tg] cam:%s:livebild triggered by chat=%s",
            cam_id,
            q.message.chat_id if q.message else "?",
        )
        jpeg = rt.snapshot_jpeg() if hasattr(rt, "snapshot_jpeg") else None
        if not jpeg:
            await q.message.reply_text(f"Kein Live-Bild für {cam_name} verfügbar.")
            return
        bio = BytesIO(jpeg)
        bio.name = f"{cam_id}.jpg"
        rows = [
            [
                InlineKeyboardButton("🔄 Neu", callback_data=f"cam:{cam_id}:livebild"),
                InlineKeyboardButton("🎬 5 s Clip", callback_data=f"cam:{cam_id}:clip:5"),
            ]
        ]
        nav_row = self._other_cam_nav_row(cam_id, "livebild")
        if nav_row:
            rows.append(nav_row)
        markup = InlineKeyboardMarkup(rows)
        ts_hm = datetime.now().strftime("%H:%M")
        try:
            # reply_to_message_id threads the snapshot under the originating
            # alert bubble in the Telegram client, so the user can scroll back
            # and see the alert + their requested follow-ups together.
            await context.bot.send_photo(
                chat_id=q.message.chat_id,
                photo=bio,
                caption=f"📷 <b>{cam_name}</b> · {ts_hm}",
                parse_mode="HTML",
                reply_markup=markup,
                reply_to_message_id=q.message.message_id if q.message else None,
            )
        except Exception as e:
            log.warning("[tg] snapshot send failed: %s", e)
        # Snap the anchor back to the cam drilldown view so the user
        # lands on the same control surface they just acted from. The
        # delivered photo is a separate message; the anchor is edited
        # in place and stays at top of the chat-state.
        with contextlib.suppress(Exception):
            await self._anchor_send_or_edit(
                context.bot, q.message.chat_id, self._cam_drilldown_view(cam_id)
            )

    async def _cam_send_clip(self, q, context, cam_id, rt, cam_name, sec):
        await q.answer(f"🎬 {sec}-s Clip wird aufgenommen…")
        log.info(
            "[tg] cam:%s:clip:%d triggered by chat=%s",
            cam_id,
            sec,
            q.message.chat_id if q.message else "?",
        )
        # The blocking ffmpeg subprocess runs in a worker thread via run_in_executor
        # so it doesn't pin the asyncio loop while the recording is in progress.
        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(None, rt.record_adhoc_clip, sec)
        except Exception as e:
            log.warning("[tg] adhoc clip exception: %s", e)
            path = None
        if not path:
            await q.message.reply_text(
                f"Clip-Aufnahme für {cam_name} fehlgeschlagen "
                f"(ffmpeg/RTSP-Problem). Snapshot stattdessen verfügbar."
            )
            return
        ts_hm = datetime.now().strftime("%H:%M")
        # Same nav layout as snapshots: same-cam refresh / snapshot row,
        # plus a row of OTHER cameras (or a single "Andere Kamera" picker
        # when there are too many to fit).
        rows = [
            [
                InlineKeyboardButton("🔄 Neuer Clip", callback_data=f"cam:{cam_id}:clip:5"),
                InlineKeyboardButton("📷 Live-Bild", callback_data=f"cam:{cam_id}:livebild"),
            ]
        ]
        nav_row = self._other_cam_nav_row(cam_id, "clip:5")
        if nav_row:
            rows.append(nav_row)
        markup = InlineKeyboardMarkup(rows)
        try:
            with open(path, "rb") as f:
                await context.bot.send_video(
                    chat_id=q.message.chat_id,
                    video=f,
                    caption=f"🎬 <b>{cam_name}</b> · {sec} s · {ts_hm}",
                    parse_mode="HTML",
                    reply_markup=markup,
                    reply_to_message_id=q.message.message_id if q.message else None,
                )
        except Exception as e:
            log.warning("[tg] clip send failed: %s", e)
            await q.message.reply_text(f"Senden fehlgeschlagen: {e}")
        # Anchor snaps back to the cam drilldown — same UX rule as the
        # snapshot path so the user keeps a single control surface.
        with contextlib.suppress(Exception):
            await self._anchor_send_or_edit(
                context.bot, q.message.chat_id, self._cam_drilldown_view(cam_id)
            )

    async def _cam_toggle_armed(self, q, cam_id, cam_name):
        if not self.settings_store:
            await q.answer()
            return
        current = self.settings_store.get_camera(cam_id)
        if not current:
            await q.answer("Kamera nicht in Settings.")
            return
        new_armed = not bool(current.get("armed", True))
        current["armed"] = new_armed
        self.settings_store.upsert_camera(current)
        # Refresh the status view in place so the user sees the change.
        await self._render_view(q, self._status_view())
        await q.answer(f"🛡 {cam_name}: {'scharf' if new_armed else 'stumm'}")
