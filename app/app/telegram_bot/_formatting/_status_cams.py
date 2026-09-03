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


class _StatusCamsMixin:
    """Per-camera live blocks, disk usage and status icons — "what are
    the cameras doing right now".

    The system-wide half of the old `_StatusMixin` lives next door in
    `_status_system.py`. Both are composed into `FormattingMixin`, so
    every `self._active_cams()` / `self._fmt_bytes()` call from the other
    mixins resolves exactly as before.
    """

    def _cam_storage_breakdown(self, cam_id: str) -> tuple[int, list[str]]:
        """One camera's disk use, as ``(total_bytes, ["Events …", …])``.

        The same three-tree walk stood byte-for-byte in `_cam.py`'s
        per-camera view and in `_system_view`'s breakdown table; the two
        copies are what this replaces. Unreadable files are skipped
        rather than aborting the row — a size readout must not be the
        thing that takes the whole screen down.
        """
        root = self._storage_root()
        parts: list[str] = []
        total = 0
        for sub_label, sub in (
            ("Events", "motion_detection"),
            ("TL", "timelapse"),
            ("Frames", "timelapse_frames"),
        ):
            p = root / sub / cam_id
            bs = 0
            if p.exists():
                try:
                    for f in p.rglob("*"):
                        if f.is_file():
                            with contextlib.suppress(OSError):
                                bs += f.stat().st_size
                except Exception:
                    pass
            total += bs
            parts.append(f"{sub_label} {self._fmt_bytes(bs)}")
        return total, parts

    def _cam_status_icon(self, st: dict) -> str:
        s = st.get("status", "")
        if s == "active":
            return "🟢"
        if s == "starting":
            return "🟡"
        return "🔴"

    def _status_view(self) -> tuple[str, InlineKeyboardMarkup]:
        lines = ["🛠 <b>Kamera-Status</b>", ""]
        rows = []
        cam_cfgs = {c["id"]: c for c in self._cfg().get("cameras", [])}
        today_iso = datetime.now().strftime("%Y-%m-%d")
        for cam_id, rt in self.runtimes.items():
            try:
                st = rt.status()
            except Exception:
                st = {}
            icon = self._cam_status_icon(st)
            name = st.get("name", cam_id)
            armed = bool((cam_cfgs.get(cam_id) or {}).get("armed", st.get("armed", True)))
            arm_label = "scharf" if armed else "stumm"
            extra = ""
            if st.get("status") not in ("active", "starting"):
                fa = st.get("frame_age_s")
                if isinstance(fa, (int, float)) and fa > 0:
                    extra = f" · offline {int(fa // 60)} min"
                else:
                    extra = " · offline"
            n_today = "?"
            if self.store:
                try:
                    n_today = len(self.store.list_events(cam_id, start=today_iso, limit=5000))
                except Exception:
                    n_today = "?"
            lines.append(f"{icon} <b>{name}</b> · {arm_label}{extra} · {n_today} Events heute")
            rows.append(
                [
                    InlineKeyboardButton(
                        ("🔇 Stumm" if armed else "🛡 Scharf") + f" {name[:10]}",
                        callback_data=f"cam:{cam_id}:arm",
                    ),
                    InlineKeyboardButton("🔄 Reconnect", callback_data=f"cam:{cam_id}:reconnect"),
                ]
            )
        rows.append([self._back_btn()])
        return "\n".join(lines), InlineKeyboardMarkup(rows)

    def _active_cams(self) -> list[dict]:
        """Single source of truth for "which cameras can the user act on".

        Returns a list of info dicts (one per cam):

            cam_id        camera id
            name          display name
            source        "runtime" — backed by a live CameraRuntime
                          "settings" — fallback, no runtime in self.runtimes
            runtime       the rt object (None for fallback)
            cfg           the cam dict from settings (None when source="runtime")
            status_kind   "active" | "starting" | "error" | "fallback"
            status        the rt.status() dict (empty for fallback)

        Fallback rule: when an enabled camera has no live runtime (recent
        boot crash, restart in progress, …), it still appears in this list
        so the Telegram bot can show it with a yellow icon instead of
        replying "Keine Kameras konfiguriert" — which historically led
        users to think the camera was lost when really the runtime just
        failed to construct."""
        out: list[dict] = []
        seen: set[str] = set()
        for cam_id, rt in (self.runtimes or {}).items():
            try:
                st = rt.status() if hasattr(rt, "status") else {}
            except Exception:
                st = {}
            kind = st.get("status") or "starting"
            out.append(
                {
                    "cam_id": cam_id,
                    "name": st.get("name") or cam_id,
                    "source": "runtime",
                    "runtime": rt,
                    "cfg": None,
                    "status_kind": kind,
                    "status": st,
                }
            )
            seen.add(cam_id)
        for cam_cfg in self._cfg().get("cameras", []) or []:
            cid = cam_cfg.get("id")
            if not cid or cid in seen:
                continue
            if not cam_cfg.get("enabled", True):
                continue
            out.append(
                {
                    "cam_id": cid,
                    "name": cam_cfg.get("name") or cid,
                    "source": "settings",
                    "runtime": None,
                    "cfg": cam_cfg,
                    "status_kind": "fallback",
                    "status": {},
                }
            )
        return out

    def _cam_status_icon_for(self, info: dict) -> str:
        """🟢 active · 🟡 starting/fallback · 🔴 error. Used by the picker
        and the per-cam status block."""
        kind = info.get("status_kind") or "starting"
        if kind == "active":
            return "🟢"
        if kind == "error":
            return "🔴"
        return "🟡"  # starting, fallback, or anything else unknown

    # Per-cam disk usage cache. Walking three sub-trees per call is too
    # expensive to do on every /status tap, so we cache for 60 s. Cleared
    # automatically because the dict is bound to the TelegramService
    # instance — restart_telegram_service() builds a fresh instance and
    # the cache starts empty again.
    _DISK_CACHE_TTL_S = 60.0

    def _cam_disk_usage_bytes(self, cam_id: str) -> int:
        cache = getattr(self, "_disk_cache", None)
        if cache is None:
            cache = {}
            self._disk_cache = cache
        ent = cache.get(cam_id)
        now = time.time()
        if ent and (now - ent[0]) < self._DISK_CACHE_TTL_S:
            return int(ent[1])
        root = self._storage_root()
        total = 0
        for sub in ("motion_detection", "timelapse", "timelapse_frames"):
            p = root / sub / cam_id
            if not p.exists():
                continue
            try:
                for f in p.rglob("*"):
                    if f.is_file():
                        with contextlib.suppress(OSError):
                            total += f.stat().st_size
            except Exception:
                pass
        cache[cam_id] = (now, total)
        return total

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        if n is None:
            return "—"
        n = int(n)
        if n >= 1024**3:
            return f"{n / 1024 ** 3:.1f} GB"
        if n >= 1024**2:
            return f"{n / 1024 ** 2:.0f} MB"
        if n >= 1024:
            return f"{n / 1024:.0f} KB"
        return f"{n} B"

    def _render_camera_block(self, info: dict) -> list[str]:
        """Render the per-cam multi-line block used by both the global
        /status bubble and the per-cam drilldown. Returns a list of
        already-formatted lines so the caller controls separators."""
        from html import escape as _esc

        today_iso = datetime.now().strftime("%Y-%m-%d")
        cam_id = info["cam_id"]
        name = _esc(info["name"])
        icon = self._cam_status_icon_for(info)
        st = info.get("status") or {}
        cam_cfg = info.get("cfg") or self._camera_cfg(cam_id) or {}
        armed = bool(cam_cfg.get("armed", st.get("armed", True)))
        arm_label = "scharf" if armed else "stumm"
        out = [f"{icon} <b>{name}</b>  · {arm_label}"]
        if info["source"] == "runtime" and st:
            kind = info.get("status_kind") or "starting"
            fps = st.get("preview_fps")
            age = st.get("frame_age_s")
            if kind == "active":
                rtsp_label = "stabil"
            elif kind == "starting":
                rtsp_label = "verbindet"
            else:
                rtsp_label = "getrennt"
            fps_str = f"{fps:.0f} fps" if isinstance(fps, (int, float)) and fps > 0 else "—"
            age_str = (
                f"letzter Frame vor {int(age)} s"
                if isinstance(age, (int, float)) and age >= 0
                else "kein Frame"
            )
            out.append(f"   RTSP: {rtsp_label} · {fps_str} · {age_str}")
        else:
            out.append("   Runtime nicht aktiv — wird gestartet …")
        # Per-cam disk usage (cached) + today event count
        n_today = "?"
        if self.store:
            try:
                n_today = len(self.store.list_events(cam_id, start=today_iso, limit=5000))
            except Exception:
                n_today = "?"
        try:
            disk = self._fmt_bytes(self._cam_disk_usage_bytes(cam_id))
        except Exception:
            disk = "—"
        out.append(f"   Heute: {n_today} Events · {disk} belegt")
        # Per-cam mute hint
        cam_mute = 0.0
        if self.settings_store:
            try:
                cam_mute = float(
                    self.settings_store.runtime_get_subkey("cam_mute_until", cam_id, 0) or 0
                )
            except Exception:
                cam_mute = 0.0
        if cam_mute and time.time() < cam_mute:
            end_local = datetime.fromtimestamp(cam_mute).strftime("%H:%M")
            out.append(f"   🔇 stumm bis {end_local}")
        return out
