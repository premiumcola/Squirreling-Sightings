"""SettingsStore — source of truth for storage/settings.json.

Boot sequence: build_defaults() seeds self.data from base_config, load()
merges any persisted state on top, runs the migrations, then save()
persists the merged result — exactly once.

The migration order is the explicit call block in
:meth:`SettingsStore._run_migrations`. There is
no registry to iterate: a function added to ``settings.migrations`` does
not run until it is imported and called there (or chained from a
migration that already is). ``test_settings_migration_wiring`` fails if
one is left unwired.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from ..schema import SECTION_SCHEMAS, validate_and_coerce
from ..storage import _atomic_write_text
from .defaults import build_defaults
from .migrations import (
    migrate_alerting_schedules,
    migrate_camera_defaults,
    migrate_class_severity,
    migrate_label_thresholds,
    migrate_rtsp_password_encoding,
    migrate_zone_source_space,
    migrate_runtime_defaults,
    migrate_schedules,
    migrate_server_location_defaults,
    migrate_telegram_push_defaults,
    migrate_timelapse_intervals,
    migrate_timelapse_profiles,
    migrate_thunder_lpi_scale,
    migrate_weather_defaults,
)
from ._cameras import CameraMixin
from ._export import ExportMixin
from ._runtime import RuntimeMixin
from .retention_migration import migrate_retention_defaults

log = logging.getLogger(__name__)


class SettingsStore(CameraMixin, ExportMixin, RuntimeMixin):
    def __init__(self, path: str | Path, base_config: dict):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.base_config = deepcopy(base_config)
        self.data = build_defaults(base_config)
        # Guards every mutation of data["runtime"]. Runtime data is touched
        # from Telegram callback threads, scheduler jobs and the camera
        # threads, so any read-modify-write needs the lock.
        self._runtime_lock = threading.RLock()
        # Serialises save(): a read-modify-write across settings.json,
        # .bak and .bak2, reached from request/Telegram/scheduler/camera
        # threads. RLock because load() saves while callers may already
        # hold it via a nested helper.
        self._save_lock = threading.RLock()
        self.load()

    def _run_migrations(self) -> bool:
        """THE migration sequence. There is no registry — this block is it.

        Never reorder existing entries: several depend on the output of
        an earlier one. A new migration is added here, at the position
        its dependencies allow, or it does not run at all.

        Returns whether the schedule migration reported a change.
        """
        migrate_camera_defaults(self.data, self.base_config)
        schedule_migrated = migrate_schedules(self.data)
        migrate_class_severity(self.data)
        migrate_alerting_schedules(self.data)
        migrate_timelapse_profiles(self.data)
        migrate_telegram_push_defaults(self.data)
        migrate_server_location_defaults(self.data)
        migrate_weather_defaults(self.data)
        # Runs AFTER migrate_weather_defaults, which owns the weather
        # categories; this one adds only the storage + trash rows of the
        # same panel. Additive, idempotent, and deliberately silent on
        # `storage.retention_days` — see the module docstring.
        migrate_retention_defaults(self.data)
        # Runs AFTER the backfill so the thunder block exists even on a
        # settings.json that predates it.
        migrate_thunder_lpi_scale(self.data)
        # E1 · runs AFTER weather_defaults so newly-added sun_timelapse /
        # event_timelapse blocks (from the additive backfill above)
        # already exist when the clamp tries to read interval_s / fps.
        migrate_timelapse_intervals(self.data)
        migrate_label_thresholds(self.data)
        migrate_runtime_defaults(self.data)
        migrate_rtsp_password_encoding(self.data)
        migrate_zone_source_space(self.data)
        return schedule_migrated

    def _load_json_or_none(self, path: Path) -> dict | None:
        """Parse `path` as a JSON object, or None if unusable."""
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error("[settings] %s is not readable JSON: %s", path.name, e)
            return None
        if not isinstance(parsed, dict):
            log.error("[settings] %s does not contain a JSON object", path.name)
            return None
        return parsed

    def load(self):
        if self.path.exists():
            loaded = self._load_json_or_none(self.path)
            if loaded is None:
                # Do NOT fall through to bare defaults and save over it.
                # load() ends in an unconditional save(), which rotates
                # settings.json → .bak → .bak2; two boots on a corrupt
                # file would therefore consume BOTH backups and destroy
                # the last good credentials for good. Quarantine the bad
                # file under a timestamp, then try the backups oldest-
                # first-preserving order before accepting defaults.
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                quarantine = self.path.with_suffix(f"{self.path.suffix}.corrupt.{stamp}")
                try:
                    shutil.copy2(str(self.path), str(quarantine))
                    log.error("[settings] corrupt settings quarantined as %s", quarantine.name)
                except Exception as e:
                    log.error("[settings] could not quarantine corrupt settings: %s", e)
                for cand in (
                    self.path.with_suffix(self.path.suffix + ".bak"),
                    self.path.with_suffix(self.path.suffix + ".bak2"),
                ):
                    if not cand.exists():
                        continue
                    recovered = self._load_json_or_none(cand)
                    if recovered is not None:
                        log.warning("[settings] recovered settings from %s", cand.name)
                        loaded = recovered
                        break
                if loaded is None:
                    log.error(
                        "[settings] no usable backup — continuing with defaults. "
                        "Camera credentials and the Telegram token must be re-entered; "
                        "the unreadable file is kept as %s",
                        quarantine.name,
                    )
            if loaded is not None:
                self.data.update(loaded)
        schedule_migrated = self._run_migrations()
        self._repair_snapshot_urls()
        # One-shot cleanup of any pre-existing duplicate camera rows.
        # Historically, a stale state.cameras array round-tripping through
        # /api/settings/cameras or migration churn around build_camera_id
        # could leave the same id present 2+ times. Every consumer
        # (weather scheduler, UI render, runtime registry) wants one
        # entry per id — collapse here so we never iterate ghosts again.
        removed = self._dedupe_cameras_by_id()
        if removed:
            log.warning("[Settings] removed %d duplicate camera entries during load", removed)
        self.data.setdefault("ui", {}).setdefault(
            "wizard_completed", bool(self.data.get("cameras"))
        )
        # Persist additive defaults (push schema, runtime section) so the
        # UI in Phase 2 finds every key present — and, with them, whatever
        # migrate_schedules rewrote.
        #
        # Exactly ONE save. A second one here (it used to be conditional
        # on `schedule_migrated`) rotated the 2-deep backup a second time
        # against a settings.json the first save had already replaced:
        # the previous generation was pushed out entirely and .bak came
        # out byte-identical to the live file. That halved the recoverable
        # history on the one boot where the pre-upgrade state matters
        # most. `schedule_migrated` is kept only for the log line.
        if schedule_migrated:
            log.info("[migration] unified camera schedules migrated to the actions shape")
        self.save()

    def save(self):
        """Persist settings.json with a 2-deep backup rotation.

        Sequence on every save:
          1. Existing settings.json.bak  → settings.json.bak2  (oldest moves out)
          2. Existing settings.json      → settings.json.bak   (previous state preserved)
          3. New content                 → settings.json       (atomic via os.replace)

        The rotation runs before the write so a crash mid-write leaves the
        previous state recoverable from .bak. We deliberately do not rotate
        when self.path doesn't exist yet (first-run write).

        The whole sequence is serialised under ``_save_lock``. It is a
        read-modify-write over three files, and callers arrive from
        Flask request threads, Telegram callback threads, scheduler jobs
        and the camera threads. Unsynchronised, two saves could
        interleave their rotation steps and copy a half-written
        settings.json over the last good backup — losing RTSP passwords
        and the Telegram token, which is precisely the file this project
        can least afford to corrupt.
        """
        with self._save_lock:
            new_text = json.dumps(self.data, ensure_ascii=False, indent=2)
            bak = self.path.with_suffix(self.path.suffix + ".bak")
            bak2 = self.path.with_suffix(self.path.suffix + ".bak2")
            try:
                if bak.exists():
                    shutil.copy2(str(bak), str(bak2))
                if self.path.exists():
                    shutil.copy2(str(self.path), str(bak))
            except Exception as e:
                log.warning("[settings] backup rotation failed: %s (continuing with save)", e)
            _atomic_write_text(self.path, new_text)

    def update_section(self, section: str, payload: dict):
        payload = payload or {}
        section_schema = SECTION_SCHEMAS.get(section)
        if section_schema:
            payload = validate_and_coerce(payload, section_schema)
        current = self.data.setdefault(section, {})
        # Deep-merge so partial UI saves to nested config (e.g. telegram.push.
        # labels.person.threshold) don't wipe sibling keys. A shallow .update
        # would replace the whole `push` dict, losing every other field the
        # client didn't echo back.
        self._deep_merge_into(current, payload)
        self.save()

    @staticmethod
    def _deep_merge_into(target: dict, src: dict):
        for key, val in (src or {}).items():
            if isinstance(val, dict) and isinstance(target.get(key), dict):
                SettingsStore._deep_merge_into(target[key], val)
            else:
                target[key] = val
