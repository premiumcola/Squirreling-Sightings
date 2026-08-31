"""The row set of the Mediathek-Verwaltung panel — one catalog, four
consumers.

Retention used to be described in four unrelated places: a Jinja
``retention.rows`` literal per panel, a defaults dict in
``settings/_consts.py``, an acknowledge loop in ``routes/app_settings.py``
and a field map in ``weather/maintenance.js``. Adding a category meant
editing all four, and forgetting one produced exactly the defect that
was live in this repo until today: a category that saves but never
acknowledges can be RAISED and never LOWERED, because
``storage_retention.nightly_window`` keeps deferring to the wider
previously-enforced window forever.

So the row set lives here once and every consumer derives from it:

* ``settings/retention_migration.py`` backfills :data:`~settings._consts.
  STORAGE_RETENTION_DEFAULTS` / ``TRASH_DEFAULTS`` additively;
* ``routes/retention_panel.py`` hands the template :func:`panel_groups`,
  already resolved, through an app-wide context processor;
* ``routes/app_settings.py`` confirms every saved window through
  :func:`acknowledge_payload` — one loop, so a newly added category
  cannot be the one nobody remembered to acknowledge;
* the template walks the same groups, stamping ``data-section`` /
  ``data-field`` on each control so the JS collector builds its payload
  from the DOM instead of a second field map;
* the sweeps (``storage_retention``, ``weather_service/_retention``,
  ``timelapse_retention``, ``trash``) keep their own resolution — they run
  in contexts where no request and sometimes no ``app_state`` exists —
  but their runtime keys are pinned against this catalog by
  ``tests/test_retention_catalog.py``.

Defaults are imported, never restated: the numbers live in
``settings/_consts.py`` next to every other shipped default. What this
module adds is the UI metadata (German label, what the row actually
governs, slider bounds, grouping) and the one thing no other layer knew:
which ``runtime.*`` key the widening guard tracks each category under.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .settings._consts import (
    CAMERA_TIMELAPSE_RETENTION_DAYS_DEFAULT,
    TRASH_DEFAULTS,
    WEATHER_RETENTION_DEFAULTS,
)

log = logging.getLogger(__name__)

#: Fallback for the motion-clip row when neither config layer carries a
#: usable number. Mirrors ``maintenance.DEFAULT_RETENTION_DAYS``; imported
#: there rather than here so ``maintenance`` keeps working without this
#: module, and pinned equal by the catalog test.
MOTION_FALLBACK_DAYS = 14


@dataclass(frozen=True)
class RetentionRow:
    """One configurable retention window.

    ``section`` / ``field`` are the settings.json coordinates — also what
    the rendered control carries as ``data-section`` / ``data-field``, so
    a save is a straight DOM walk. ``fallback_field`` is the key inside
    the same section consulted when ``field`` is literally absent (the
    weather categories defer to the legacy blanket ``retention_days``,
    which a real install may still be the only thing carrying a number).
    """

    key: str
    section: str
    field: str
    label: str
    hint: str
    group: str
    default: int
    minimum: int
    maximum: int
    runtime_key: str
    fallback_field: str | None = None
    #: True when ``0`` is a legitimate value meaning "nie löschen" rather
    #: than the "delete everything" hazard ``MIN_RETENTION_DAYS`` refuses.
    off_at_zero: bool = False


@dataclass(frozen=True)
class RetentionGroup:
    """A titled block of rows, optionally with its own Auto-Cleanup
    switch. Two switches, not one: ``storage.auto_cleanup_enabled`` and
    ``weather.auto_cleanup_enabled`` gate two independent nightly sweeps
    and were separately settable before this panel existed. Collapsing
    them into a single master toggle would silently take that apart."""

    key: str
    title: str
    note: str
    rows: tuple[RetentionRow, ...]
    toggle_section: str = ""
    toggle_field: str = ""


def weather_runtime_key(category: str) -> str:
    """Mirror of ``weather_service._retention.weather_retention_runtime_key``.

    Restated (and pinned equal by the catalog test) rather than imported:
    importing it here would drag the whole ``weather_service`` package
    into every settings save and every template render for one f-string.
    """
    return f"weather_retention_enforced_{category}_days"


#: ``runtime.*`` key the widening guard tracks the camera-timelapse
#: window under. New — the category was never swept, so nothing was ever
#: enforced for it.
CAMERA_TL_RUNTIME_KEY = "retention_enforced_camera_timelapses_days"

#: Same for the trash grace period. Lowering it hard-deletes trashed
#: files that are past the NEW cutoff but were inside the old one, and
#: those are unrecoverable — the trash is the last copy.
TRASH_RUNTIME_KEY = "trash_grace_enforced_days"


RETENTION_GROUPS: tuple[RetentionGroup, ...] = (
    RetentionGroup(
        key="kamera",
        title="Kamera-Aufnahmen",
        note="Bestätigte Ereignisse bleiben dauerhaft erhalten. Abgelaufene Dateien "
        "wandern in den Papierkorb, sie werden nicht sofort gelöscht.",
        toggle_section="storage",
        toggle_field="auto_cleanup_enabled",
        rows=(
            RetentionRow(
                key="motion_clips",
                section="storage",
                field="retention_days",
                label="Bewegungs-Clips",
                hint="Videos, Schnappschüsse und Metadaten der Bewegungserkennung",
                group="kamera",
                default=MOTION_FALLBACK_DAYS,
                minimum=1,
                maximum=365,
                runtime_key="retention_enforced_days",
            ),
            RetentionRow(
                key="camera_timelapses",
                section="storage",
                field="retention_camera_timelapses_days",
                label="Kamera-Timelapses",
                hint="Zeitraffer-Videos je Kamera samt Mediathek-Eintrag · 0 = nie löschen",
                group="kamera",
                default=CAMERA_TIMELAPSE_RETENTION_DAYS_DEFAULT,
                minimum=0,
                maximum=365,
                runtime_key=CAMERA_TL_RUNTIME_KEY,
                off_at_zero=True,
            ),
        ),
    ),
    RetentionGroup(
        key="wetter",
        title="Wetter-Aufnahmen",
        note="Angepinnte Einträge bleiben dauerhaft erhalten. Wetter-Dateien werden "
        "endgültig gelöscht — sie gehen nicht durch den Papierkorb.",
        toggle_section="weather",
        toggle_field="auto_cleanup_enabled",
        rows=(
            RetentionRow(
                key="weather_sightings",
                section="weather",
                field="retention_sightings_days",
                label="Wetter-Sichtungen",
                hint="Clips von Gewitter, Starkregen, Schnee und Nebel",
                group="wetter",
                default=WEATHER_RETENTION_DEFAULTS["retention_sightings_days"],
                minimum=7,
                maximum=365,
                runtime_key=weather_runtime_key("sightings"),
                fallback_field="retention_days",
            ),
            RetentionRow(
                key="weather_event_timelapses",
                section="weather",
                field="retention_event_timelapses_days",
                label="Ereignis-Timelapses",
                hint="Zeitraffer von Gewitteraufzug, Frontdurchgang und Sturmfront",
                group="wetter",
                default=WEATHER_RETENTION_DEFAULTS["retention_event_timelapses_days"],
                minimum=7,
                maximum=365,
                runtime_key=weather_runtime_key("event_timelapses"),
                fallback_field="retention_days",
            ),
            RetentionRow(
                key="weather_sun_timelapses",
                section="weather",
                field="retention_sun_timelapses_days",
                label="Sonnen-Timelapses",
                hint="Zeitraffer von Sonnenauf- und Sonnenuntergang",
                group="wetter",
                default=WEATHER_RETENTION_DEFAULTS["retention_sun_timelapses_days"],
                minimum=7,
                maximum=365,
                runtime_key=weather_runtime_key("sun_timelapses"),
                fallback_field="retention_days",
            ),
            RetentionRow(
                key="weather_recaps",
                section="weather",
                field="retention_recaps_days",
                label="Recaps",
                hint="Quartals- und Jahresrückblicke · die 2 neuesten bleiben immer",
                group="wetter",
                default=WEATHER_RETENTION_DEFAULTS["retention_recaps_days"],
                minimum=30,
                maximum=1000,
                runtime_key=weather_runtime_key("recaps"),
                fallback_field="retention_days",
            ),
            RetentionRow(
                key="weather_manual_events",
                section="weather",
                field="retention_manual_events_days",
                label="Manuelle Ereignisse",
                hint="Selbst gespeicherte Zeiträume aus dem Wetter-Diagramm",
                group="wetter",
                default=WEATHER_RETENTION_DEFAULTS["retention_manual_events_days"],
                minimum=30,
                maximum=1000,
                runtime_key=weather_runtime_key("manual_events"),
                fallback_field="retention_days",
            ),
        ),
    ),
    RetentionGroup(
        key="system",
        title="Papierkorb",
        note="Läuft immer — auch wenn Auto-Cleanup oben aus ist. Der Papierkorb hält "
        "bereits gelöschte Dateien; ihn einzufrieren hiesse, Platz nie zurückzubekommen.",
        rows=(
            RetentionRow(
                key="trash_grace",
                section="trash",
                field="grace_days",
                label="Papierkorb-Frist",
                hint="Wie lange gelöschte Dateien wiederherstellbar bleiben",
                group="system",
                default=TRASH_DEFAULTS["grace_days"],
                minimum=1,
                maximum=90,
                runtime_key=TRASH_RUNTIME_KEY,
            ),
        ),
    ),
)


RETENTION_ROWS: tuple[RetentionRow, ...] = tuple(
    row for group in RETENTION_GROUPS for row in group.rows
)


def rows_for_section(section: str) -> tuple[RetentionRow, ...]:
    return tuple(row for row in RETENTION_ROWS if row.section == section)


# ── resolution ─────────────────────────────────────────────────────────


def _layer_value(source, section: str, field: str):
    if isinstance(source, dict):
        block = source.get(section)
        if isinstance(block, dict) and block.get(field) is not None:
            return block[field]
    return None


def resolve_days(row: RetentionRow) -> int:
    """The number this row currently governs by.

    ``settings.json`` first, ``config.yaml`` second, the row's own
    shipped default last — the same order ``maintenance._storage_setting``
    uses, extended by the weather categories' legacy blanket fallback.
    Read-only: nothing is written back, so the additive-merge rule holds.
    """
    from . import app_state

    sources = (
        getattr(getattr(app_state, "settings", None), "data", None),
        getattr(app_state, "base_cfg", None),
    )
    for field in (row.field, row.fallback_field):
        if not field:
            continue
        for source in sources:
            value = _layer_value(source, row.section, field)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                log.debug(
                    "[storage] %s.%s ist keine Zahl (%r) — nächste Ebene", row.section, field, value
                )
    return row.default


def resolve_toggle(section: str, field: str, default: bool = True) -> bool:
    from . import app_state

    for source in (
        getattr(getattr(app_state, "settings", None), "data", None),
        getattr(app_state, "base_cfg", None),
    ):
        value = _layer_value(source, section, field)
        if value is not None:
            return bool(value)
    return default


# ── the widening guard, per row ────────────────────────────────────────


def acknowledge_payload(section: str, payload: dict) -> list[str]:
    """Confirm every retention window a settings-save payload carries.

    An explicit number on a screen the operator is looking at IS the
    confirmation ``storage_retention.nightly_window`` waits for before an
    unattended sweep may act on a NARROWER window. Without this call a
    row can only ever be raised.

    Tolerant by design, mirroring the two hand-written acknowledgers it
    replaces: a row absent from the payload stays deferred, and a value
    that does not parse is ignored rather than raising out of a save.

    Returns the row keys actually acknowledged — the return value exists
    for the test, the call sites use it for logging.
    """
    from .storage_retention import acknowledge_window

    if not isinstance(payload, dict):
        return []
    done: list[str] = []
    for row in rows_for_section(section):
        if row.field not in payload:
            continue
        try:
            days = int(payload[row.field])
        except (TypeError, ValueError):
            continue
        if days <= 0 and row.off_at_zero:
            # "Nie löschen" is not a window to enforce. Recording it as
            # one would set the guard's floor to 0 and silence it for
            # every later change of this row.
            log.info("[storage] %s auf „nie löschen“ gestellt", row.label)
            done.append(row.key)
            continue
        acknowledge_window(days, key=row.runtime_key)
        done.append(row.key)
    return done


# ── panel rendering ────────────────────────────────────────────────────


def _row_view(row: RetentionRow) -> dict:
    current = resolve_days(row)
    return {
        "key": row.key,
        "section": row.section,
        "field": row.field,
        "label": row.label,
        "hint": row.hint,
        "min": row.minimum,
        "max": row.maximum,
        "current": max(row.minimum, min(row.maximum, current)),
        "off_at_zero": row.off_at_zero,
        "input_id": f"ret_{row.key}",
        "range_id": f"ret_{row.key}_range",
    }


def panel_groups() -> list[dict]:
    """Everything the Jinja macro needs to render the panel, resolved
    against the live config. Plain dicts because Jinja is friendlier with
    them than with frozen dataclasses."""
    out: list[dict] = []
    for group in RETENTION_GROUPS:
        view = {
            "key": group.key,
            "title": group.title,
            "note": group.note,
            "rows": [_row_view(row) for row in group.rows],
            "toggle_section": group.toggle_section,
            "toggle_field": group.toggle_field,
        }
        if group.toggle_section:
            view["toggle_id"] = f"ret_auto_{group.key}"
            view["toggle_on"] = resolve_toggle(group.toggle_section, group.toggle_field)
        out.append(view)
    return out
