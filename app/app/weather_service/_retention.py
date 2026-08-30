"""Weather-media retention sweep — the per-category cousin of
``storage_retention.cleanup_old``, scoped to ``storage/weather/``.

Mirrors that module's safety rules rather than inventing looser ones:
a non-positive window is refused (:data:`storage_retention.
MIN_RETENTION_DAYS`), and a narrowed window is deferred via the very
same ``nightly_window`` widening guard — keyed per category (see
:func:`weather_retention_runtime_key`) so four independent trackers
never collide in ``runtime.*``. See ``storage_retention.py``'s own
module docstring for why that guard exists at all.

Four categories, four independent ``weather.*`` settings keys (see
``settings/_consts.py::WEATHER_RETENTION_DEFAULTS`` for the shipped
defaults and the reasoning behind each one):

    sightings          — raw thunder/heavy_rain/snow/fog clips
    event_timelapses   — thunder_rising/front_passing/storm_front
    sun_timelapses     — sunrise/sunset
    recaps             — quarterly/yearly compilations (own rule —
                          see :meth:`WeatherRetentionMixin._sweep_recaps`)

A sighting whose manifest carries ``"pinned": true`` is skipped
regardless of age — the "keep forever" flag set via
``POST /api/weather/sightings/<id>/pin`` (``routes/weather_pin.py``).
Deletion itself reuses ``ManifestsMixin.delete_sighting`` rather than a
second file-removal routine — that method already hard-deletes every
sidecar by stem, which is the existing convention for weather-scoped
deletes (see ``trash.py``'s module docstring: weather deletes are
hard, unlike the soft-delete-to-trash the main event store uses).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..storage_retention import MIN_RETENTION_DAYS, nightly_window
from ._consts import _safe_dt, log

#: Directory names under storage/weather/<cam_id>/ bucketed by which
#: retention category governs them. Anything not listed here (a future
#: dir type, or a hand-created one) falls back to "sightings" — the
#: same fallback-bucket principle the settings layer uses for a
#: category with no explicit value.
_EVENT_TL_DIRS: frozenset[str] = frozenset({"event_timelapse"})
_SUN_TL_DIRS: frozenset[str] = frozenset({"sunrise_timelapse", "sunset_timelapse", "sun_timelapse"})

#: Category keys swept as per-sighting directories, in sweep order.
#: "recaps" is deliberately excluded — it has its own item shape (one
#: mp4+json pair per period, no per-camera nesting) and its own rule.
WEATHER_RETENTION_CATEGORIES: tuple[str, ...] = (
    "sightings",
    "event_timelapses",
    "sun_timelapses",
)

#: Recaps fire quarterly/yearly — a flat day-count alone would delete
#: last quarter's recap the moment its own window expires, which is
#: the opposite of what a "recap" is for. This is the period-aware
#: floor layered on top of the flat cutoff below: the N most recent
#: recaps (by list_recaps()'s own newest-first ordering) are never
#: swept, however old — a deliberately simple approximation of "a
#: recap must outlive the period it covers" rather than a full
#: period-cadence calculation.
WEATHER_RECAP_MIN_KEEP = 2

#: Baseline used when a fresh/never-enforced install's resolved value
#: is compared against "what was enforced before" (nightly_window's
#: `baseline` argument). Weather has no config.yaml layer of its own,
#: so the shipped default stands in for it — mirrors what
#: `config_retention_days()` is for the main event store.
_DEFAULT_CATEGORY_DAYS: dict[str, int] = {
    "sightings": 90,
    "event_timelapses": 120,
    "sun_timelapses": 21,
    "recaps": 400,
}


def _dir_category(dirname: str) -> str:
    if dirname in _EVENT_TL_DIRS:
        return "event_timelapses"
    if dirname in _SUN_TL_DIRS:
        return "sun_timelapses"
    return "sightings"


def weather_retention_runtime_key(category: str) -> str:
    """The ``runtime.*`` key the widening guard stores this category's
    last-enforced window under. Exported so routes/app_settings.py can
    acknowledge a slider save without re-deriving the naming scheme."""
    return f"weather_retention_enforced_{category}_days"


def acknowledge_weather_retention_from_payload(weather_payload: dict) -> None:
    """Confirm every retention day-count present in a settings-save
    payload against the nightly widening guard.

    Mirrors ``routes/media.py``'s ``api_media_cleanup``: an explicit
    number on a screen the operator is looking at IS the confirmation
    ``nightly_window`` waits for before it may act on a narrower
    window. Weather has no separate "Jetzt bereinigen" button, so
    saving the maintenance-panel sliders doubles as that attended act.

    Silently ignores a category key absent from the payload (an
    unconfigured category keeps deferring to the blanket bucket,
    exactly as the settings layer intends) and a value that doesn't
    parse as an int.
    """
    from ..storage_retention import acknowledge_window

    if not isinstance(weather_payload, dict):
        return
    for category in (*WEATHER_RETENTION_CATEGORIES, "recaps"):
        key = f"retention_{category}_days"
        if key not in weather_payload:
            continue
        try:
            days = int(weather_payload[key])
        except (TypeError, ValueError):
            continue
        acknowledge_window(days, key=weather_retention_runtime_key(category))


class WeatherRetentionMixin:
    """Nightly sweep for ``storage/weather/``. Mixin for WeatherService.

    Methods access shared state via ``self.*`` (``settings_store``,
    ``_scheduler``, etc.) which live on the concrete class, same as
    every other weather_service mixin.
    """

    # ── settings resolution ─────────────────────────────────────────

    def _weather_section(self) -> dict:
        try:
            data = self.settings_store.data
        except Exception:
            return {}
        section = data.get("weather") if isinstance(data, dict) else None
        return section if isinstance(section, dict) else {}

    def _auto_cleanup_enabled(self) -> bool:
        return bool(self._weather_section().get("auto_cleanup_enabled", True))

    def _category_baseline_days(self, category: str) -> int:
        return _DEFAULT_CATEGORY_DAYS.get(category, _DEFAULT_CATEGORY_DAYS["sightings"])

    def _resolve_category_days(self, category: str) -> int:
        """``weather.retention_<category>_days``, falling back to the
        legacy blanket ``weather.retention_days`` when the category key
        is literally absent — see ``WEATHER_RETENTION_DEFAULTS``'s own
        docstring in ``settings/_consts.py`` for why that fallback must
        keep working for a real install."""
        w = self._weather_section()
        value = w.get(f"retention_{category}_days")
        if value is None:
            value = w.get("retention_days")
        try:
            return int(value)
        except (TypeError, ValueError):
            return self._category_baseline_days(category)

    # ── scheduling ───────────────────────────────────────────────────

    def _register_retention_job(self):
        if not self._scheduler:
            return
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger

        self._scheduler.add_job(
            self._run_weather_retention_sweep,
            CronTrigger(hour=3, minute=30),
            id="weather_retention_sweep",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        # Also run shortly after boot (mirrors weather_poll_initial) so a
        # freshly-deployed install doesn't wait until 03:30 for its first
        # sweep — best-effort, a scheduling failure here must not block
        # the rest of start().
        try:
            self._scheduler.add_job(
                self._run_weather_retention_sweep,
                DateTrigger(run_date=datetime.now() + timedelta(seconds=30)),
                id="weather_retention_sweep_initial",
            )
        except Exception as e:
            log.warning("[weather] retention sweep initial-run scheduling failed: %s", e)

    # ── the sweep ────────────────────────────────────────────────────

    def _run_weather_retention_sweep(self):
        if not self._auto_cleanup_enabled():
            log.info(
                "[weather] autoclean deaktiviert (weather.auto_cleanup_enabled) — übersprungen"
            )
            return
        try:
            removed = 0
            pinned = 0
            for category in WEATHER_RETENTION_CATEGORIES:
                window = nightly_window(
                    self._resolve_category_days(category),
                    self._category_baseline_days(category),
                    key=weather_retention_runtime_key(category),
                )
                if window < MIN_RETENTION_DAYS:
                    log.error(
                        "[weather] autoclean %s abgebrochen: retention=%d Tage — "
                        "mindestens %d Tage erforderlich",
                        category,
                        window,
                        MIN_RETENTION_DAYS,
                    )
                    continue
                r, p = self._sweep_sighting_category(category, window)
                removed += r
                pinned += p
            recap_window = nightly_window(
                self._resolve_category_days("recaps"),
                self._category_baseline_days("recaps"),
                key=weather_retention_runtime_key("recaps"),
            )
            recap_removed = 0
            if recap_window >= MIN_RETENTION_DAYS:
                recap_removed = self._sweep_recaps(recap_window)
            else:
                log.error(
                    "[weather] autoclean recaps abgebrochen: retention=%d Tage — "
                    "mindestens %d Tage erforderlich",
                    recap_window,
                    MIN_RETENTION_DAYS,
                )
            log.info(
                "[weather] autoclean: %d Sichtungen + %d Recaps entfernt, "
                "%d angepinnte Sichtungen übersprungen",
                removed,
                recap_removed,
                pinned,
            )
        except Exception as e:
            log.warning("[weather] retention sweep failed: %s", e)

    def _sweep_sighting_category(self, category: str, retention_days: int) -> tuple[int, int]:
        """Delete every un-pinned sighting of ``category`` older than
        ``retention_days``. Returns ``(removed, pinned_skipped)``."""
        root = self._sightings_dir()
        if not root.exists():
            return 0, 0
        cutoff = datetime.now() - timedelta(days=retention_days)
        removed = 0
        pinned = 0
        for cam_dir in root.iterdir():
            if not cam_dir.is_dir() or cam_dir.name == "recaps":
                continue
            for evt_dir in cam_dir.iterdir():
                if not evt_dir.is_dir() or evt_dir.name.startswith(".scratch_"):
                    continue
                if _dir_category(evt_dir.name) != category:
                    continue
                # Materialise the glob before deleting — delete_sighting
                # removes the very files this loop is iterating over.
                for jf in list(evt_dir.glob("*.json")):
                    try:
                        m = json.loads(jf.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if m.get("pinned"):
                        pinned += 1
                        continue
                    started = _safe_dt(m.get("started_at", "")) or datetime.fromtimestamp(
                        jf.stat().st_mtime
                    )
                    if started >= cutoff:
                        continue
                    sighting_id = m.get("id")
                    if sighting_id and self.delete_sighting(sighting_id):
                        removed += 1
        return removed, pinned

    def _sweep_recaps(self, retention_days: int) -> int:
        """Delete every un-pinned recap older than ``retention_days``,
        except the :data:`WEATHER_RECAP_MIN_KEEP` most recent ones,
        which are never swept regardless of age."""
        root = self._recaps_dir()
        if not root.exists():
            return 0
        cutoff = datetime.now() - timedelta(days=retention_days)
        items = self.list_recaps()  # newest-first (period_end/built_at)
        protected = {r.get("id") for r in items[:WEATHER_RECAP_MIN_KEEP]}
        removed = 0
        for r in items:
            rid = r.get("id")
            if not rid or rid in protected or r.get("pinned"):
                continue
            built = _safe_dt(r.get("built_at", "")) or _safe_dt(r.get("period_end", ""))
            if built and built >= cutoff:
                continue
            deleted_any = False
            for ext in (".json", ".mp4"):
                p = root / f"{rid}{ext}"
                try:
                    if p.exists():
                        p.unlink()
                        deleted_any = True
                except Exception as e:
                    log.warning("[weather] recap sweep: %s: %s", p.name, e)
            if deleted_any:
                removed += 1
                log.info("[weather] Recap entfernt (Aufbewahrung %dd): %s", retention_days, rid)
        return removed
