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

from ...telegram_helpers import (
    DULL_BIRDS,
    LABEL_DE,
    LABEL_WEIGHT,
    OBJECT_LABELS,
    is_night,
    is_quiet_now,
    most_specific_label,
    truncate_caption,
)
from .._consts import (
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


class _StatusSystemMixin:
    """The system-wide views — `/status`'s bubble and the 🛠 System
    screen. Reads the per-camera helpers off `_StatusCamsMixin` through
    `self`, which is what composing both into `FormattingMixin`
    guarantees.
    """

    def _polling_status(self) -> dict:
        """The Telegram poller's state, or ``{}`` when it cannot be read.

        Both system views asked for this with the same four lines of
        hasattr-and-swallow; one copy now.
        """
        try:
            return self.get_polling_status() if hasattr(self, "get_polling_status") else {}
        except Exception:
            return {}

    @staticmethod
    def _coral_avg_ms(cams_info: list[dict]) -> list[float]:
        """Per-camera rolling inference averages, positives only.

        The other half of the same duplication: both views walked
        `cams_info` with this identical filter before averaging.
        """
        out: list[float] = []
        for info in cams_info:
            v = (info.get("status") or {}).get("inference_avg_ms")
            if isinstance(v, (int, float)) and v > 0:
                out.append(v)
        return out

    def _weather_row(self) -> str:
        """The `Wetter` line of the /status bubble — poll age plus a chip
        per event trigger. Falls back to the "kein Poll bekannt" text on
        any failure; the row is a status readout, so a broken weather
        service must not take the whole bubble down with it."""
        default = "Wetter     ⚪ kein Poll bekannt"
        try:
            from ... import app_state as _st

            wsvc = getattr(_st, "weather_service", None)
        except Exception:
            return default
        try:
            if not (wsvc and hasattr(wsvc, "status")):
                return default
            wstat = wsvc.status() or {}
            last_iso = wstat.get("last_poll_at")
            age_min = None
            if last_iso:
                try:
                    age_min = int(
                        (datetime.now() - datetime.fromisoformat(last_iso)).total_seconds() / 60
                    )
                except Exception:
                    age_min = None
            cur = wstat.get("current_state") or {}
            # Compact event chip list — only the events the user has
            # turned on (dot icon + label).
            from ...weather_service import EVENT_LABEL_DE

            ev_chips = [
                f"{lbl} {'🟡' if bool(cur.get(evt)) else '⚪'}"
                for evt, lbl in EVENT_LABEL_DE.items()
            ]
            age_str = (
                f"letzter Poll vor {age_min} min" if age_min is not None else "kein Poll bekannt"
            )
            return f"Wetter     🟢 {age_str} · {' · '.join(ev_chips)}"
        except Exception as e:
            log.debug("[tg] weather row render failed: %s", e)
            return default

    def _render_system_status_text(self) -> str:
        """Build the /status bubble. Defensive — any single source
        missing falls back to a question mark instead of crashing the
        whole render. Layout (from spec):

            📊 System-Status
            ━━━━━━━━━━━
            <per-cam block>     <— from _render_camera_block
            <per-cam block>
            ────
            Telegram   …
            Coral      …
            Wetter     …
            ────
            Speicher: free + sum of cam-belegt
            🔇 Pushes pausiert bis HH:MM   (only when muted)
        """
        import shutil as _sh

        cfg = self._cfg()
        lines = ["📊 <b>System-Status</b>", "━━━━━━━━━━━━━━", ""]
        cams_info = self._active_cams()
        cam_disk_total = 0
        for info in cams_info:
            try:
                lines.extend(self._render_camera_block(info))
                lines.append("")
            except Exception as e:
                log.warning("[tg] cam block render failed for %s: %s", info.get("cam_id"), e)
                continue
            with contextlib.suppress(Exception):
                cam_disk_total += self._cam_disk_usage_bytes(info["cam_id"])
        if not cams_info:
            lines.append("(keine Kameras konfiguriert)")
            lines.append("")
        lines.append("────")
        # Telegram polling
        ps = self._polling_status()
        ps_icon = {"active": "🟢", "conflict": "🟡", "starting": "🟡", "off": "⚪"}.get(
            ps.get("state", "?"), "⚪"
        )
        ps_dur_min = (ps.get("since_seconds", 0) or 0) // 60
        lines.append(f"Telegram   {ps_icon} Polling {ps_dur_min} min")
        # Coral state + rolling-average inference latency from any active cam
        det_mode = (cfg.get("processing", {}).get("detection") or {}).get("mode", "none")
        coral_icon = "🟢" if det_mode == "coral" else "⚪"
        avg_inferences = self._coral_avg_ms(cams_info)
        infer_str = (
            f" · {sum(avg_inferences)/len(avg_inferences):.0f} ms ø" if avg_inferences else ""
        )
        lines.append(f"Coral      {coral_icon} {det_mode}{infer_str}")
        lines.append(self._weather_row())
        lines.append("────")
        # Storage: free disk + sum of per-cam belegt
        try:
            root = str(self._storage_root())
            free_gb = _sh.disk_usage(root).free / (1024**3)
            cam_total_str = self._fmt_bytes(cam_disk_total) if cam_disk_total else "—"
            lines.append(
                f"Speicher:  <b>{free_gb:.1f} GB</b> frei · {cam_total_str} von Cams belegt"
            )
        except Exception:
            pass
        # Global mute hint
        if self.settings_store:
            try:
                mute_until = float(self.settings_store.runtime_get("global_mute_until") or 0)
            except Exception:
                mute_until = 0
            if mute_until and time.time() < mute_until:
                end_local = datetime.fromtimestamp(mute_until).strftime("%H:%M")
                lines.append(f"🔇 Pushes pausiert bis {end_local}")
        return "\n".join(lines)

    def _system_view(self) -> tuple[str, InlineKeyboardMarkup]:
        """🛠 System — per-cam disk breakdown + global health checks."""
        import shutil as _sh
        from html import escape as _esc

        lines = ["🛠 <b>System</b>", "─────────────"]
        # Per-cam storage breakdown
        cams_info = self._active_cams()
        cam_disk_total = 0
        if cams_info:
            lines.append("Speicher pro Kamera:")
            for info in cams_info:
                name = _esc(info["name"])
                row_total, parts = self._cam_storage_breakdown(info["cam_id"])
                cam_disk_total += row_total
                lines.append(
                    f"  {name:<12s} {self._fmt_bytes(row_total):>8s}  ({' · '.join(parts)})"
                )
            lines.append("")
        # Free disk
        try:
            usage = _sh.disk_usage(str(self._storage_root()))
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            lines.append(f"Gesamt frei: <b>{free_gb:.1f} GB</b> von {total_gb:.0f} GB")
        except Exception:
            free_gb = None
            lines.append("Speicher: nicht ermittelbar")
        lines.append("")
        # Health rows
        lines.append("Health:")
        # Cam state
        n_runtime = sum(1 for c in cams_info if c["source"] == "runtime")
        n_fallback = sum(1 for c in cams_info if c["source"] == "settings")
        if n_fallback == 0 and n_runtime > 0:
            lines.append("  ✅ Alle Kameras online")
        elif n_fallback > 0:
            lines.append(f"  ⚠️ {n_fallback} im Fallback (Runtime nicht aktiv)")
        elif n_runtime == 0:
            lines.append("  ⚠️ Keine Kamera-Runtime aktiv")
        # Reconnects 24h
        for info in cams_info:
            n24 = (info.get("status") or {}).get("reconnect_count_24h")
            if isinstance(n24, int) and n24 > 3:
                lines.append(f"  ⚠️ {_esc(info['name'])}: {n24} Reconnects letzte 24 h")
        # Coral
        cfg = self._cfg()
        det_mode = (cfg.get("processing", {}).get("detection") or {}).get("mode", "none")
        if det_mode == "coral":
            avg_inferences = self._coral_avg_ms(cams_info)
            if avg_inferences:
                lines.append(f"  ✅ Coral · {sum(avg_inferences) / len(avg_inferences):.0f} ms ø")
            else:
                lines.append("  ✅ Coral aktiv")
        else:
            lines.append(f"  ⚠️ Coral inaktiv (Modus: {det_mode})")
        # Disk
        if free_gb is not None:
            if free_gb < 10:
                lines.append(f"  🔴 Speicher: nur {free_gb:.1f} GB frei")
            elif free_gb < 25:
                lines.append(f"  ⚠️ Speicher: {free_gb:.1f} GB frei")
            else:
                lines.append(f"  ✅ Speicher: {free_gb:.0f} GB frei")
        # Telegram polling
        ps_state = self._polling_status().get("state", "?")
        if ps_state == "active":
            lines.append("  ✅ Telegram-Polling aktiv")
        elif ps_state in ("starting", "conflict"):
            lines.append(f"  ⚠️ Telegram-Polling {ps_state}")
        else:
            lines.append(f"  🔴 Telegram-Polling {ps_state}")

        rows = [
            [
                InlineKeyboardButton("🔄 Aktualisieren", callback_data="menu:system"),
                InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:root"),
            ],
        ]
        return "\n".join(lines), InlineKeyboardMarkup(rows)
