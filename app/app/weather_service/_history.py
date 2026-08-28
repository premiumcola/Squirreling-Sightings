from __future__ import annotations

# ruff: noqa: F401
# Comprehensive per-mixin import block — some symbols are unused in this
# mixin but kept identical across mixins so methods can move between them
# without import bookkeeping. See service.py for the canonical import list.
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from ..io_utils import atomic_write_json
from ._consts import (
    EVENT_ICON_HEX,
    EVENT_LABEL_DE,
    HISTORY_FIELD_TO_EVENT,
    HISTORY_FIELDS,
    HISTORY_LABELS_DE,
    HISTORY_MAXLEN,
    HISTORY_UNITS,
    _atomic_write_json,
    _is_quiet_now,
    _safe_dt,
    _safe_subset,
    log,
)


class HistoryMixin:
    """Wetterstatistik chart history: persist samples + serve /api/weather/history.

    Mixin for WeatherService. Methods access shared state via `self.*`
    (cfg, runtimes, settings_store, scheduler, etc.) which live on the
    concrete class.
    """

    def _history_path(self) -> Path:
        """Resolve `<storage_root>/weather_history.json` from settings_store."""
        try:
            root = self.settings_store.base_config.get("storage", {}).get("root", "/app/storage")
        except Exception:
            root = "/app/storage"
        return Path(root) / "weather_history.json"

    def _load_history(self):
        path = self._history_path()
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("[weather] history file unparseable, starting fresh: %s", e)
            return
        items = payload.get("samples") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            log.warning("[weather] history file has unexpected shape, starting fresh")
            return
        kept = 0
        with self._history_lock:
            self._history.clear()
            for row in items[-HISTORY_MAXLEN:]:
                if not isinstance(row, dict):
                    continue
                ts = row.get("ts")
                values = row.get("values")
                if not isinstance(ts, str) or not isinstance(values, dict):
                    continue
                # Migration: drop fields no longer in HISTORY_FIELDS, fill
                # missing ones with None — never crash on old/extra keys.
                clean = {k: values.get(k) for k in HISTORY_FIELDS}
                self._history.append({"ts": ts, "values": clean})
                kept += 1
        log.info("[weather] history loaded: %d samples from %s", kept, path)

    def _save_history(self):
        """Atomic write to .tmp + os.replace so a kill -9 mid-write cannot
        leave a half-written history.json on disk."""
        path = self._history_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.warning("[weather] history dir mkdir failed: %s", e)
            return
        with self._history_lock:
            samples = list(self._history)
        payload = {
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "samples": samples,
        }
        # fsync=True — history is the source of truth for the weather
        # chart; an OS-level crash mid-write would lose the rolling
        # window without the explicit flush + fsync.
        try:
            atomic_write_json(path, payload, fsync=True)
        except Exception as e:
            log.warning("[weather] history write failed: %s", e)

    def _record_sample(self, latest: dict, sun: dict):
        """Append the latest poll's numeric values to the ring buffer.
        Called from _poll_once after a successful API response. Stores
        `None` for any field the API didn't return so the chart can show a
        gap instead of pretending to have data."""
        values = {}
        for key in HISTORY_FIELDS:
            if key == "sun_altitude":
                values[key] = sun.get("altitude") if isinstance(sun, dict) else None
            else:
                v = latest.get(key) if isinstance(latest, dict) else None
                values[key] = float(v) if isinstance(v, (int, float)) else None
        ts_iso = datetime.now().isoformat(timespec="seconds")
        with self._history_lock:
            self._history.append({"ts": ts_iso, "values": values})
        # Update the live status snapshot so /api/weather/status carries the
        # last polled slice without a separate fetch.
        with self._lock:
            self._status["current_values"] = dict(values)
        self._save_history()
        self._sweep_episodes()

    def _sweep_episodes(self):
        """Lift finished storms out of the rolling window into the archive.

        The history buffer is 30 days deep and drops its oldest sample
        on every append — a storm that falls off the end is gone for
        good, which is exactly what makes "how bad was the 2026 one"
        unanswerable. The sweep re-segments the WHOLE buffer each poll
        and appends only ids the archive does not carry yet, so the
        first sweep after a restart backfills every episode still in
        the window and later sweeps cost a set lookup.

        Best-effort: an archive failure must never interrupt the poll
        cadence, the same contract `_save_history` runs under.
        """
        # Local import — weather_episodes imports back into this
        # package for the field/event map, so a module-level import
        # here would close an import cycle.
        from ..weather_episodes import sweep as _sweep_episodes_impl

        try:
            root = self.settings_store.base_config.get("storage", {}).get("root", "/app/storage")
        except Exception:
            root = "/app/storage"
        with self._history_lock:
            rows = list(self._history)
        try:
            result = _sweep_episodes_impl(
                root,
                rows,
                events_cfg=self.cfg.get("events"),
                episode_cfg=self.cfg.get("episodes"),
                footage_counter=self._episode_footage_counter(root),
            )
        except Exception as e:
            log.warning("[weather] episode sweep failed: %s", e)
            return
        with self._history_lock:
            self._episode_pending = result.get("pending")

    def _episode_footage_counter(self, root):
        """``record -> overlapping-recording count``, for the list chip.

        The count is stamped into the archive ledger HERE — on the poll
        thread, once per episode — because the list route must not walk
        the media tree to render a chip. Bounded to the record's OWN
        window, so one call reads the two date folders that window
        touches instead of every event ever recorded.

        Returns ``None`` for a record with no usable window, which tells
        the sweep to stop rather than stamp a wrong number.
        """
        from .. import app_state
        from ..weather_episodes import build_footage_index, episode_footage, episode_window

        def _count(rec: dict):
            start, end = episode_window(rec)
            if start is None:
                return None
            try:
                cameras = list(app_state.get_effective_config().get("cameras") or [])
            except Exception as e:
                log.warning("[weather] camera list unavailable for footage count: %s", e)
                return None
            candidates, degraded = build_footage_index(
                root,
                weather_service=self,
                store=app_state.store,
                cameras=cameras,
                since=start,
                until=end,
            )
            if "weather_service_unavailable" in degraded:
                return None
            return int(episode_footage(candidates, degraded, rec)["total"])

        return _count

    def episodes_pending(self) -> dict | None:
        """The storm currently being recorded, or None.

        An episode is only archived once no later sample can still
        change it (see weather_episodes._segment), which for the
        default margins is three hours after the rain stops. Without
        this the UI would have no way to say "a storm is happening and
        it is being captured".
        """
        with self._history_lock:
            return self._episode_pending

    def history(self, hours: int = 24) -> dict:
        """Backing call for /api/weather/history."""
        hours = max(1, min(720, int(hours or 24)))
        cutoff = datetime.now() - timedelta(hours=hours)
        with self._history_lock:
            samples = list(self._history)
        # Filter to time window. Tolerate parse failures by falling back to
        # "include the row" — a malformed timestamp shouldn't shrink the
        # visible window.
        out: list[dict] = []
        for row in samples:
            ts_str = row.get("ts") or ""
            try:
                if datetime.fromisoformat(ts_str) >= cutoff:
                    out.append(row)
            except Exception:
                out.append(row)
        # Thresholds from configured event settings. Always emit the
        # configured threshold value regardless of the enabled toggle —
        # the chart needs to draw the boundary even for events that are
        # currently off so the user can see what the trigger SHOULD fire
        # at. The parallel `events_enabled` map lets the renderer dim
        # disabled-event ticks instead of hiding them. Fields without an
        # associated event (cloud_cover, wind_gusts_10m, sun_altitude)
        # still emit thresholds[k]=None / events_enabled[k]=None.
        events_cfg = self.cfg.get("events") or {}
        thresholds: dict[str, float | None] = {k: None for k in HISTORY_FIELDS}
        events_enabled: dict[str, bool | None] = {k: None for k in HISTORY_FIELDS}
        for key in HISTORY_FIELDS:
            evt = HISTORY_FIELD_TO_EVENT.get(key)
            if not evt:
                continue
            ev_cfg = events_cfg.get(evt) or {}
            events_enabled[key] = bool(ev_cfg.get("enabled", False))
            thr = ev_cfg.get("threshold")
            try:
                thresholds[key] = float(thr) if thr is not None else None
            except (TypeError, ValueError):
                thresholds[key] = None
        poll_interval_s = int(self.cfg.get("poll_interval", 300) or 300)
        return {
            "hours": hours,
            "samples": out,
            "thresholds": thresholds,
            "events_enabled": events_enabled,
            "units": dict(HISTORY_UNITS),
            "labels_de": dict(HISTORY_LABELS_DE),
            "fields": list(HISTORY_FIELDS),
            "poll_interval_s": poll_interval_s,
        }

    # ── Telegram push (Phase 3) ─────────────────────────────────────────────
