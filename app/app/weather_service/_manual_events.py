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
import uuid
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

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

#: Cap on the user-supplied name, mirroring weather_episodes.USER_NAME_MAX.
#: Kept as its own constant rather than imported — this collection has no
#: other dependency on the episode archive and shouldn't grow one just for
#: a shared number.
MANUAL_EVENT_NAME_MAX = 120

#: Cap on the free-text "Charakteristik" — the operator's own narrative of
#: how the curves moved together (e.g. "Regen setzt ein, dann Blitze auf
#: hohem Niveau, Wind nimmt zu und wieder ab … mittelgroßes Gewitter").
#: Mirrors weather_episodes.USER_NOTE_MAX for the same reason
#: MANUAL_EVENT_NAME_MAX mirrors USER_NAME_MAX — a local constant, no
#: cross-package dependency for a shared number.
MANUAL_EVENT_CHARACTERISTIC_MAX = 2000

#: The category is one of the app's existing weather-event types
#: (core/weather-types.js's WEATHER_TYPES keys) so a manual event renders
#: with the same badge/icon/color/filter-chip machinery every other event
#: already uses, rather than inventing a separate visual identity. Keep in
#: sync with WEATHER_TYPES in app/web/static/js/core/weather-types.js.
MANUAL_EVENT_CATEGORIES: tuple[str, ...] = (
    "thunder",
    "heavy_rain",
    "snow",
    "fog",
    "sun_timelapse_rise",
    "sun_timelapse_set",
    "thunder_rising",
    "front_passing",
    "storm_front",
)

#: A real event is genuinely more than one thing — a thunderstorm that
#: also brings heavy rain — so the operator may tick several categories.
#: Three is the ceiling because that is what the grid card can show
#: without turning into noise on a 375 px screen (weather/_feed.js::
#: manualEventCardHTML stacks one badge per category in a fixed-height
#: slot). Keep in sync with MANUAL_CATEGORIES_MAX in
#: app/web/static/js/weather/_manual-event-cats.js.
MANUAL_EVENT_CATEGORIES_MAX = 3


def manual_event_categories(record: dict) -> list[str]:
    """The category list of a manual-event record, old shape or new.

    Records written before multi-select carry a single ``category``
    string; records written since carry a ``categories`` list *and* keep
    ``category`` as its first entry. This is the one place that knows
    both shapes — every reader (``list_manual_events``, the card
    builder's JS twin) goes through it rather than branching on the
    record's age. Order is preserved, duplicates dropped.
    """
    out: list[str] = []
    raw = record.get("categories")
    if isinstance(raw, list):
        for c in raw:
            if isinstance(c, str) and c and c not in out:
                out.append(c)
    if not out:
        single = record.get("category")
        if isinstance(single, str) and single:
            out.append(single)
    return out


def normalize_manual_event(record: dict) -> dict:
    """Fill in both category fields so callers never see only one.

    An old single-``category`` record gains the ``categories`` list; a
    new one keeps ``category`` pointing at its first entry. Applied on
    read, so nothing on disk has to be migrated to stay readable.
    """
    cats = manual_event_categories(record)
    if cats:
        record["categories"] = cats
        record["category"] = cats[0]
    return record


class ManualEventsMixin:
    """User-saved chart ranges — a named time window, assigned to one or
    more of the app's existing weather-event categories, plus the curve
    keys and a free-text "characteristic" the operator entered to justify
    that categorisation (the drag-zoom feature's "save this as an event"
    action, e.g. categories=[thunder, heavy_rain], curves=[precipitation,
    lightning_potential], characteristic="Regen setzt ein, dann Blitze
    auf hohem Niveau … mittelgroßes Gewitter"). No clip attached.

    Mixin for WeatherService. Persisted exactly like RecapsMixin's
    recaps: one JSON file per record under
    ``<sightings_dir>/manual_events/``, read back with a plain glob.
    Deliberately NOT the weather_episodes append-only JSONL ledger —
    that machinery exists to keep a detector's own verdict recoverable
    underneath a user patch, which does not apply here: a manual event
    has no detector verdict to protect, so recaps' simpler one-file-
    per-record shape is the closer analogue.
    """

    def _manual_events_dir(self) -> Path:
        return self._sightings_dir() / "manual_events"

    def list_manual_events(self) -> list[dict]:
        root = self._manual_events_dir()
        if not root.exists():
            return []
        items: list[dict] = []
        for jf in root.glob("*.json"):
            try:
                items.append(normalize_manual_event(json.loads(jf.read_text(encoding="utf-8"))))
            except Exception:
                continue
        # Newest range first — matches the unified feed's own newest-first
        # sort (weather/_feed.js::unifiedFeedItems).
        items.sort(key=lambda m: m.get("range_start") or m.get("created_at") or "", reverse=True)
        return items

    def get_manual_event(self, event_id: str) -> dict | None:
        path = self._manual_events_dir() / f"{event_id}.json"
        if not path.exists():
            return None
        try:
            return normalize_manual_event(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def create_manual_event(
        self,
        name: str,
        range_start: str,
        range_end: str,
        curves: list[str],
        category: str | None = None,
        characteristic: str = "",
        categories: list[str] | None = None,
    ) -> dict:
        """Write a new manual-event manifest and return it.

        The route validates name/range/curves/categories before calling
        this — this method only mints the id and persists, mirroring how
        ``_build_recap`` is handed already-picked, already-valid inputs.

        Takes either shape: ``categories=[…]`` (what the form sends now)
        or the original single ``category=…``. Both land on disk as a
        ``categories`` list plus a ``category`` first-entry mirror, so a
        reader that only knows the old field keeps working.
        """
        cats = manual_event_categories({"categories": categories, "category": category})
        now = datetime.now()
        event_id = f"manual_{now.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
        manifest = {
            "id": event_id,
            "name": name,
            "category": cats[0] if cats else "",
            "categories": cats,
            "characteristic": characteristic or "",
            "range_start": range_start,
            "range_end": range_end,
            "curves": list(curves),
            "created_at": now.isoformat(timespec="seconds"),
        }
        _atomic_write_json(self._manual_events_dir() / f"{event_id}.json", manifest)
        log.info("[weather] manual event saved: %s (%s / %s)", event_id, name, ", ".join(cats))
        return manifest

    def delete_manual_event(self, event_id: str) -> bool:
        path = self._manual_events_dir() / f"{event_id}.json"
        if not path.exists():
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        log.info("[weather] manual event deleted: %s", event_id)
        return True
