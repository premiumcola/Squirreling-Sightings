"""The nightly retention sweep — the most destructive code in the repo.

Carved out of ``storage.py`` (772 lines against a 500 ceiling) so the
rules that decide what survives sit in one readable file instead of at
the bottom of the event store.

Four guarantees this module owns, none of which held before:

* **Nothing is unlinked.** Expired files move into ``storage/.trash``
  and live out ``trash.grace_days`` there, so a retention change that
  turns out to be wrong is recoverable for a week instead of gone the
  same night.
* **A timelapse record is immortal.** ``tl_<stem>.json`` is the *single*
  record of an mp4 the sweep deliberately never touches (it lives under
  ``timelapse/``, outside ``motion_detection/``). It lands in the camera
  root because ``event_date_subdir("tl_…")`` returns None, and the sweep
  walked the camera root — so 14 days after registration the April tile
  disappeared while its mp4 sat there untouched, came back at the next
  container restart, and vanished again.
* **A non-positive window is refused.** ``cleanup_old(0)`` used to mean
  "cutoff is now", i.e. delete the entire ``motion_detection/`` tree.
* **A widening is announced, never performed silently.** The sweep read
  ``config.yaml`` while the Aufbewahrung slider wrote ``settings.json``;
  the moment both are read in slider-first order, a slider value nobody
  ever enforced becomes the window — and the first night after the
  upgrade would remove everything between the two numbers. See
  :func:`nightly_window`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# Fields in the event JSON that mark a human verdict. Both are written
# exclusively by POST /api/camera/<cam>/events/<id>/confirm
# (routes/events.py) — the detection pipeline never writes them, because
# `detection_confirmer` keeps its two-frame state in memory only.
# `labels` is deliberately NOT a marker: add_event fills it from the
# detector on every single event, so a user-edited and an auto-labelled
# event are indistinguishable on disk.
JUDGEMENT_FIELDS = ("confirmed", "confirmed_at")

#: Event-id prefix of a timelapse manifest. Written by
#: ``media_index._timelapse`` and ``camera_runtime/_timelapse.py``.
TIMELAPSE_ID_PREFIX = "tl_"

#: Below this the sweep refuses to run at all. A window of zero days is
#: not a retention policy, it is "delete everything".
MIN_RETENTION_DAYS = 1

#: ``settings.json`` runtime key holding the window the nightly sweep
#: last actually enforced. Written through ``runtime_set``, which merges
#: into the existing document — never a wholesale rewrite.
ENFORCED_KEY = "retention_enforced_days"


def is_judged_event(payload: object) -> bool:
    """True when an event payload carries a human verdict.

    Falsy values (``confirmed: false``, empty ``confirmed_at``) and
    non-dict payloads count as unjudged, so a half-parsed or default
    manifest never becomes immortal.
    """
    if not isinstance(payload, dict):
        return False
    return any(payload.get(field) for field in JUDGEMENT_FIELDS)


def keep_judged_events_enabled(default: bool = True) -> bool:
    """Resolve ``storage.keep_judged_events``: settings.json first,
    then config.yaml, else ``default`` (True).

    Read-only — nothing is written back, so the additive-merge rule for
    settings.json holds. The import is local because `app_state` is a
    boot-time singleton module built after this one.
    """
    from . import app_state

    for source in (getattr(app_state.settings, "data", None), app_state.base_cfg):
        if not isinstance(source, dict):
            continue
        section = source.get("storage")
        if isinstance(section, dict) and "keep_judged_events" in section:
            return bool(section["keep_judged_events"])
    return default


def judged_event_ids(events_dir: Path) -> set:
    """Every event id under ``events_dir`` whose manifest carries a
    human verdict.

    Companion files are matched by id, not by name, because a judged
    event's mp4 and jpg carry no verdict of their own — protecting
    only the old JSONs would therefore protect nothing and let the
    media of exactly those events be deleted.

    Unreadable JSON is skipped with a WARNING and counted as NOT
    judged — a corrupt file must stay mortal, otherwise every
    truncated manifest becomes immortal.
    """
    import json

    ids: set = set()
    if not events_dir.exists():
        return ids
    for jf in events_dir.rglob("*.json"):
        if jf.name.endswith(".tracks.json"):
            continue
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("[storage] unreadable event JSON %s — not treated as judged: %s", jf, e)
            continue
        if is_judged_event(payload):
            ids.add(jf.stem)
    return ids


# ── the widening guard ─────────────────────────────────────────────────


def _settings():
    from . import app_state

    return getattr(app_state, "settings", None)


def enforced_days(fallback: int) -> int:
    """The window the sweep last enforced, or ``fallback`` when nothing
    was ever recorded — which is the state of every install upgrading
    into this code, and why the caller passes the ``config.yaml``
    number: that is what the sweep actually enforced before."""
    settings = _settings()
    if settings is None:
        return fallback
    try:
        value = settings.runtime_get(ENFORCED_KEY)
    except Exception:
        log.debug("[storage] runtime_get(%s) failed", ENFORCED_KEY, exc_info=True)
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def record_enforced_days(days: int) -> None:
    """Remember the window as enforced. Additive ``runtime_set``."""
    settings = _settings()
    if settings is None:
        return
    try:
        settings.runtime_set(ENFORCED_KEY, int(days))
    except Exception:
        log.debug("[storage] runtime_set(%s) failed", ENFORCED_KEY, exc_info=True)


def acknowledge_window(days: int) -> None:
    """Record ``days`` as confirmed by the operator.

    The manual "Jetzt bereinigen" button posts an explicit
    ``retention_days`` — a deliberate act on a screen that shows the
    number. That is the confirmation :func:`nightly_window` waits for,
    so the unattended sweep is never the first thing to act on a value
    nobody has yet seen take effect.

    A window the sweep refuses (:data:`MIN_RETENTION_DAYS`) is not
    recorded — otherwise "confirming" 0 would set the floor to 0 and
    silence the guard for every later change.
    """
    if days < MIN_RETENTION_DAYS:
        log.warning(
            "[storage] Aufbewahrung %d Tage nicht übernommen — mindestens %d Tage",
            days,
            MIN_RETENTION_DAYS,
        )
        return
    log.info("[storage] Aufbewahrung %d Tage vom Bediener bestätigt", days)
    record_enforced_days(days)


def nightly_window(resolved: int, baseline: int) -> int:
    """The window the *unattended* sweep may act on.

    ``resolved`` is what the config layers now say; ``baseline`` is the
    ``config.yaml`` number, i.e. what the sweep enforced before
    settings.json entered the resolution order. A smaller window deletes
    strictly more, so it is announced and NOT acted on — the sweep keeps
    the previous, wider window until the operator confirms the new one
    with "Jetzt bereinigen". The warning repeats every night until then,
    which is the point: a pending narrowing must stay visible.
    """
    previous = enforced_days(baseline)
    if resolved >= previous:
        if resolved >= MIN_RETENTION_DAYS:
            record_enforced_days(resolved)
        return resolved
    log.warning(
        "[storage] Aufbewahrung von %d auf %d Tage verkürzt — die nächtliche "
        "Bereinigung würde %d zusätzliche Tage entfernen. Sie läuft weiter mit %d "
        "Tagen; bestätige die %d Tage mit „Jetzt bereinigen“ in der Mediathek.",
        previous,
        resolved,
        previous - resolved,
        previous,
        resolved,
    )
    return previous


# ── the sweep ──────────────────────────────────────────────────────────


def _camera_of(events_dir: Path, path: Path) -> str:
    """Camera id a file under ``motion_detection/`` belongs to, or
    ``_lose`` for the odd file lying directly in the tree root."""
    try:
        parts = path.relative_to(events_dir).parts
    except ValueError:
        return "_lose"
    return parts[0] if len(parts) > 1 else "_lose"


def _collect_expired(events_dir: Path, cutoff: datetime, judged: set) -> tuple:
    """Group expired files by ``(camera, event_id)``.

    Returns ``(buckets, preserved_ids, preserved_files, timelapse_records)``.
    Grouping matters because the trash is organised per event, so one
    ``meta.json`` describes the whole set a restore has to put back.
    """
    buckets: dict = {}
    preserved_ids: set = set()
    preserved_files = 0
    timelapse_records = 0
    for path in events_dir.rglob("*"):
        try:
            if not path.is_file() or datetime.fromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
        except OSError:
            continue
        # Companions share the event id up to the first dot —
        # `<id>.json`, `<id>.jpg`, `<id>.mp4`, `<id>.tracks.json`,
        # `<id>.best.jpg`. Grouping on the id keeps the snapshot and the
        # clip with the manifest they belong to.
        event_id = path.name.split(".", 1)[0]
        if event_id.startswith(TIMELAPSE_ID_PREFIX):
            timelapse_records += 1
            continue
        if event_id in judged:
            preserved_files += 1
            preserved_ids.add(event_id)
            continue
        buckets.setdefault((_camera_of(events_dir, path), event_id), []).append(path)
    return buckets, preserved_ids, preserved_files, timelapse_records


def _retire(store_root, buckets: dict) -> int:
    """Move every grouped file into the trash. Local import: ``trash``
    reaches ``app_state``, which reaches back here at boot."""
    from .trash import retire_to_trash

    retired = 0
    for (cam_id, event_id), paths in buckets.items():
        retired += retire_to_trash(store_root, cam_id, event_id, paths)
    return retired


def _log_outcome(retention_days: int, retired: int, preserved: tuple, tl_records: int) -> None:
    preserved_files, preserved_ids = preserved
    if preserved_files:
        log.info(
            "[storage] autoclean: %d files of %d judged events preserved "
            "(storage.keep_judged_events)",
            preserved_files,
            preserved_ids,
        )
    if tl_records:
        log.info(
            "[storage] autoclean: %d Timelapse-Einträge geschützt — sie sind der "
            "einzige Nachweis eines mp4, das die Bereinigung nie anfasst",
            tl_records,
        )
    if retired:
        log.info(
            "[storage] %d files moved to storage/.trash (motion events + snapshots "
            "older than %dd)",
            retired,
            retention_days,
        )
    else:
        log.info(
            "[storage] nothing retired (all motion_detection/ files within %dd retention)",
            retention_days,
        )


def cleanup_old(store, retention_days: int, keep_judged: bool | None = None) -> int:
    """Retire files under ``motion_detection/`` older than
    ``retention_days`` into ``storage/.trash``.

    ``keep_judged`` skips events a human has judged; ``None`` (the
    default) resolves ``storage.keep_judged_events``, itself defaulting
    to True. The judgement corpus is the training signal for threshold
    calibration, so it must outlive the retention window.

    Returns the number of files retired.
    """
    if retention_days < MIN_RETENTION_DAYS:
        log.error(
            "[storage] autoclean abgebrochen: retention=%d Tage würde das gesamte "
            "motion_detection/ löschen — mindestens %d Tage erforderlich",
            retention_days,
            MIN_RETENTION_DAYS,
        )
        return 0
    if not store.events_dir.exists():
        log.info("[storage] motion_detection/ not found, nothing to clean")
        return 0
    if keep_judged is None:
        keep_judged = keep_judged_events_enabled()
    judged = judged_event_ids(store.events_dir) if keep_judged else set()
    cutoff = datetime.now() - timedelta(days=retention_days)
    log.info(
        "[storage] autoclean: retention=%dd cutoff=%s | eligible: motion snapshots + "
        "event JSON (motion_detection/) | protected: timelapse videos AND their "
        "tl_*.json records, judged events | expired files go to storage/.trash "
        "(restorable), they are not unlinked",
        retention_days,
        cutoff.strftime("%Y-%m-%d"),
    )
    buckets, preserved_ids, preserved_files, tl_records = _collect_expired(
        store.events_dir, cutoff, judged
    )
    retired = _retire(store.root, buckets)
    _log_outcome(retention_days, retired, (preserved_files, len(preserved_ids)), tl_records)
    return retired
