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
from . import _history_store as _hstore
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


# The buffer's own span in hours, at the default 5-minute poll. Derived
# so the API clamp and the buffer can never disagree again.
#
# Since _record_sample writes at most one row per 15-minute Open-Meteo
# slot, the deque actually spans about three times this. The derivation
# is left at the poll interval on purpose: it now UNDER-states the span,
# which makes the `hours` clamp conservative — it can refuse a window
# wider than the buffer is guaranteed to hold, never truncate one it
# already has.
_DEFAULT_POLL_S = 300
_MAX_HISTORY_HOURS = max(1, HISTORY_MAXLEN * _DEFAULT_POLL_S // 3600)


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

    def _storage_root(self) -> Path:
        try:
            return Path(
                self.settings_store.base_config.get("storage", {}).get("root", "/app/storage")
            )
        except Exception:
            return Path("/app/storage")

    def _load_history(self):
        """Fill the buffer from the append-only ledger (or the legacy
        document on first boot after the format change)."""
        rows = _hstore.load(self._storage_root(), HISTORY_MAXLEN)
        with self._history_lock:
            self._history.clear()
            for row in rows:
                self._history.append(row)
        log.info("[weather] history loaded: %d samples", len(rows))
        # A legacy install has no ledger yet; write one so the next poll
        # appends instead of falling back again.
        root = self._storage_root()
        if rows and not _hstore.history_path(root).exists():
            _hstore.write_all(root, rows)

    def _append_history(self, sample: dict):
        """Persist ONE sample. O(1) in the window length.

        The old path serialised and fsynced the entire buffer on every
        poll, which is what made a long window unaffordable. See
        _history_store.py's docstring for the reasoning.
        """
        root = self._storage_root()
        if not _hstore.append(root, sample):
            return
        if _hstore.needs_compaction(root, HISTORY_MAXLEN):
            with self._history_lock:
                rows = list(self._history)
            _hstore.compact(root, rows)

    def _save_history(self):
        """Full rewrite. Only for shutdown and explicit callers — the
        poll path uses :meth:`_append_history`."""
        with self._history_lock:
            rows = list(self._history)
        _hstore.write_all(self._storage_root(), rows)

    def _record_sample(self, latest: dict, sun: dict):
        """Append the latest poll's numeric values to the ring buffer.

        Called from _poll_once after a successful API response. Stores
        `None` for any field the API didn't return so the chart can show a
        gap instead of pretending to have data.

        Appends at most ONE row per Open-Meteo 15-minute slot. The poll
        runs every ``poll_interval`` (300 s) but `_latest_slice` anchors on
        the `minutely_15` slot covering now, so three consecutive polls
        read the same slot and used to write the same measurement three
        times. That is not extra resolution — it is one measurement in
        triplicate, and drawing it as three points is what put a visible
        staircase in the Wetterstatistik chart: 68 % of consecutive
        samples were exact repeats, laying a ~2.5 px tread under every
        curve on a phone. No interpolation can smooth that out, because
        the steps are already at the pixel scale.

        The skip is deliberately narrow: `current_values` still refreshes
        on every poll, and `_sweep_episodes` still runs on every poll, so
        the live panel and storm detection keep the full 5-minute cadence.
        Only the history row is suppressed. A slot with no time (an empty
        `minutely_15`, `_detection._latest_slice` returning {}) always
        records, so a run of empty payloads can never wedge the buffer.
        """
        values = {}
        for key in HISTORY_FIELDS:
            if key == "sun_altitude":
                values[key] = sun.get("altitude") if isinstance(sun, dict) else None
            else:
                v = latest.get(key) if isinstance(latest, dict) else None
                values[key] = float(v) if isinstance(v, (int, float)) else None
        # Update the live status snapshot so /api/weather/status carries the
        # last polled slice without a separate fetch. Unconditional: this is
        # what the panel reads, and it is fresh every poll.
        with self._lock:
            self._status["current_values"] = dict(values)
        slot = latest.get("time") if isinstance(latest, dict) else None
        if slot and slot == self._last_slot_time:
            self._sweep_episodes()
            return
        self._last_slot_time = slot or None
        ts_iso = datetime.now().isoformat(timespec="seconds")
        sample = {"ts": ts_iso, "values": values}
        with self._history_lock:
            self._history.append(sample)
        self._append_history(sample)
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
        """``record -> {"count": int, "hero": dict | None}``, for the
        list chip and the merged Library grid's footage-primary card.

        Both are stamped into the archive ledger HERE — on the poll
        thread, once per episode — because neither the list route nor
        the merged grid must walk the media tree to render. Bounded to
        the record's OWN window, so one call reads the two date folders
        that window touches instead of every event ever recorded.
        ``hero`` is ``episode_hero``'s pick from the SAME scan
        ``episode_footage`` already paid for, not a second one.

        Returns ``None`` for a record with no usable window, which tells
        the sweep to stop rather than stamp a wrong number.
        """
        from .. import app_state
        from ..weather_episodes import (
            build_footage_index,
            episode_footage,
            episode_hero,
            episode_window,
        )

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
            total = int(episode_footage(candidates, degraded, rec)["total"])
            return {"count": total, "hero": episode_hero(candidates, rec)}

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

    def history(
        self,
        hours: int = 24,
        since_iso: str | None = None,
        until_iso: str | None = None,
    ) -> dict:
        """Backing call for /api/weather/history.

        ``since_iso``/``until_iso`` are additive: when given, they
        replace the ``hours``-based cutoff with an explicit absolute
        window, so a saved manual-event range can be replayed exactly
        even when it no longer falls inside "the last N hours from
        now" (e.g. the operator opens a save from three days ago while
        the panel itself is set to 24 h). Every existing caller that
        only passes ``hours`` is unaffected.
        """
        # Clamp to the buffer's own span rather than a literal: the two
        # drifted apart the moment HISTORY_MAXLEN grew, and a caller
        # asking for more than the buffer holds should get the buffer,
        # not a silently shorter window.
        hours = max(1, min(_MAX_HISTORY_HOURS, int(hours or 24)))
        since_dt = _safe_dt(since_iso) if since_iso else None
        until_dt = _safe_dt(until_iso) if until_iso else None
        cutoff = since_dt or (datetime.now() - timedelta(hours=hours))
        with self._history_lock:
            samples = list(self._history)
        # Filter to time window. Tolerate parse failures by falling back to
        # "include the row" — a malformed timestamp shouldn't shrink the
        # visible window.
        out: list[dict] = []
        for row in samples:
            ts_str = row.get("ts") or ""
            try:
                ts_dt = datetime.fromisoformat(ts_str)
            except Exception:
                out.append(row)
                continue
            if ts_dt < cutoff:
                continue
            if until_dt and ts_dt > until_dt:
                continue
            out.append(row)
        # A long window must not become a download. Thinning preserves
        # spikes per field rather than striding — see _history_store's
        # `downsample` for why a stride would erase exactly the lightning
        # and gust peaks this chart is read for.
        out, bucket = _hstore.downsample(out)
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
            "bucket_size": bucket,
            "thresholds": thresholds,
            "events_enabled": events_enabled,
            "units": dict(HISTORY_UNITS),
            "labels_de": dict(HISTORY_LABELS_DE),
            "fields": list(HISTORY_FIELDS),
            "poll_interval_s": poll_interval_s,
        }

    # ── Telegram push (Phase 3) ─────────────────────────────────────────────
