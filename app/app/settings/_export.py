"""Reading settings back out: effective config, export, import.

``export_effective_config`` is the authoritative merge of the read-only
``config.yaml`` base and the GUI-written ``settings.json`` — everything
downstream reads the result of this, not either layer alone.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy

import yaml

from .migrations import migrate_camera_defaults

log = logging.getLogger("app.settings")


class ExportMixin:
    """Read-out and round-trip helpers for :class:`SettingsStore`."""

    def log_action(self, action: dict):
        actions = self.data.setdefault("telegram_actions", [])
        actions.insert(0, action)
        del actions[80:]
        self.save()

    def set_review(self, event_key: str, review: dict):
        self.data.setdefault("review", {})[event_key] = review
        self.save()

    def get_review(self, event_key: str) -> dict | None:
        return (self.data.get("review") or {}).get(event_key)

    def export_effective_config(self, base_cfg: dict) -> dict:
        cfg = deepcopy(base_cfg)
        cfg["app"] = deepcopy(self.data.get("app", {}))
        cfg["server"] = {
            **deepcopy(base_cfg.get("server", {})),
            **deepcopy(self.data.get("server", {})),
        }
        # Same layering as `server`: config.yaml supplies the section
        # (notably `root`, which settings.json never carries), settings
        # overrides per key. Without this the section was the base layer
        # verbatim and `storage.media_limit_default` — whose only reader
        # is `/api/camera/<id>/media` via get_effective_config — could
        # not be set at all. The other `storage.*` keys read
        # `settings.data` directly and were unaffected.
        cfg["storage"] = {
            **deepcopy(base_cfg.get("storage", {})),
            **deepcopy(self.data.get("storage", {})),
        }
        cfg["telegram"] = deepcopy(self.data.get("telegram", {}))
        cfg["mqtt"] = deepcopy(self.data.get("mqtt", {}))
        cfg["cameras"] = deepcopy(self.data.get("cameras", []))
        # Wetter-Sichtungen — exported so the WeatherService and the web UI
        # both read from the same canonical config block.
        if "weather" in self.data:
            cfg["weather"] = deepcopy(self.data["weather"])
        # Merge processing overrides (e.g. coral_enabled, bird_species_enabled) from settings
        if "processing" in self.data:
            base_proc = deepcopy(base_cfg.get("processing", {}))
            for key, val in deepcopy(self.data["processing"]).items():
                if isinstance(val, dict) and isinstance(base_proc.get(key), dict):
                    base_proc[key] = {**base_proc[key], **val}
                else:
                    base_proc[key] = val
            cfg["processing"] = base_proc
        return cfg

    def export_serializable(self) -> dict:
        return deepcopy(self.data)

    def export_text(self, format: str = "json") -> str:
        payload = self.export_serializable()
        if format == "yaml":
            return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def import_text(self, text: str, format: str = "json"):
        loaded = yaml.safe_load(text) if format == "yaml" else json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError("Import muss ein Objekt enthalten")
        allowed = {
            "app",
            "server",
            "telegram",
            "mqtt",
            "cameras",
            "ui",
            "review",
            "telegram_actions",
            "weather",
            # export_text ships `storage`; without it here a settings
            # backup restored the retention window and the media page
            # size to whatever the fresh install defaulted to. Same for
            # `trash` and its soft-delete grace period.
            "storage",
            "trash",
        }
        for key, value in loaded.items():
            if key in allowed:
                self.data[key] = value
        migrate_camera_defaults(self.data, self.base_config)
        self.data.setdefault("ui", {})["wizard_completed"] = bool(self.data.get("cameras")) or bool(
            self.data.get("ui", {}).get("wizard_completed")
        )
        self.save()

    def bootstrap_state(self) -> dict:
        ui = self.data.setdefault("ui", {})
        needs_wizard = not ui.get("wizard_completed", False)
        return {
            "wizard_completed": bool(ui.get("wizard_completed", False)),
            "needs_wizard": needs_wizard,
            "camera_count": len(self.data.get("cameras", [])),
            "telegram_configured": bool(self.data.get("telegram", {}).get("token")),
            "mqtt_configured": bool(self.data.get("mqtt", {}).get("host")),
        }
