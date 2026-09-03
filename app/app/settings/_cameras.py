"""The ``cameras`` list: upsert, delete, dedupe, URL repair.

``upsert_camera`` owns the canonical-id rebuild. A camera first lands
with empty manufacturer/model (id collapses to
``unknown_unknown_<name>_<octet>``); once the operator fills those in,
the id has to be rebuilt and the legacy row removed, or the UI shows two
entries for one camera.
"""

from __future__ import annotations

import logging

from ..schema import CAMERA_SCHEMA, validate_and_coerce
from .defaults import default_camera

log = logging.getLogger("app.settings")


class CameraMixin:
    """Camera-row maintenance for :class:`SettingsStore`."""

    def _dedupe_cameras_by_id(self) -> int:
        """Collapse duplicate camera rows (same id) keeping the first
        occurrence; returns the number of dropped duplicates. The first
        entry wins because upsert_camera updates by first-match — any
        later dupe is a stale older copy."""
        cams = self.data.get("cameras") or []
        if len(cams) < 2:
            return 0
        seen: set = set()
        cleaned: list[dict] = []
        for c in cams:
            cid = c.get("id")
            if not cid:
                cleaned.append(c)
                continue
            if cid in seen:
                continue
            seen.add(cid)
            cleaned.append(c)
        removed = len(cams) - len(cleaned)
        if removed:
            self.data["cameras"] = cleaned
        return removed

    def _repair_snapshot_urls(self):
        """Repair cameras whose snapshot_url was corrupted with a dashboard display URL.

        This happens when quick-action saves (toggleCameraEnabled, saveTlCameraProfiles,
        etc.) spread state.cameras objects — which previously contained the display-only
        /api/camera/<id>/snapshot.jpg URL — back to /api/settings/cameras.
        For cameras present in base_config we restore both snapshot_url and rtsp_url.
        For others we clear the broken relative URL so the error becomes recoverable.
        """
        base_cam_map = {c.get("id"): c for c in self.base_config.get("cameras", [])}
        count = 0
        for cam in self.data.get("cameras", []):
            cam_id = cam.get("id", "")
            if cam.get("snapshot_url", "").startswith("/api/camera/"):
                base = base_cam_map.get(cam_id)
                if base:
                    cam["snapshot_url"] = base.get("snapshot_url", "")
                    # Also restore rtsp_url if base has one (was wiped by the same bad save)
                    if base.get("rtsp_url"):
                        cam["rtsp_url"] = base["rtsp_url"]
                    log.warning(
                        "[settings] restored snapshot_url/rtsp_url for camera '%s' from base config",
                        cam_id,
                    )
                else:
                    cam["snapshot_url"] = ""
                    log.warning(
                        "[settings] cleared corrupted snapshot_url for camera '%s' (not in base config; re-enter URL)",
                        cam_id,
                    )
                count += 1
        if count:
            self.save()

    def get_camera(self, cam_id: str) -> dict | None:
        return next((c for c in self.data.get("cameras", []) if c.get("id") == cam_id), None)

    def upsert_camera(self, camera: dict):
        """Insert/update one camera. Returns the canonical id post-migration
        so the HTTP handler can detect a rename (manufacturer / model / name
        / rtsp_url change → build_camera_id rebuilds → migration renames
        folders + the cam id in settings.json) and rebind the live runtime
        accordingly.

        ja847 — for UPDATES the validated payload is merged directly onto
        the stored cam dict. The previous implementation funnelled the
        payload through ``default_camera()`` first, which rebuilt a fresh
        dict with only the keys it explicitly knew about — any field not
        listed there (icon, future-added fields, schema fields added
        without a default-builder line) silently fell on the floor every
        time the user pressed Speichern. The "tracking presets don't
        stick" fix from bw916 was a localised patch for four of those
        fields; the same bug pattern affected the whole Erkennung +
        Alerting + Allgemein tabs whenever the frontend sent a field
        default_camera didn't list. validate_and_coerce already
        preserves every key in ``camera`` (it only type-checks
        schema-known fields and copies unknown keys through unchanged),
        so handing it straight to existing.update is the
        non-destructive merge the user asked for. ``default_camera``
        still seeds NEW cameras with the full default skeleton.
        """
        camera = validate_and_coerce(camera, CAMERA_SCHEMA)
        in_id = camera.get("id", "")
        existing = self.get_camera(in_id)
        id_relevant_changed = False
        if existing:
            # Track whether any input that feeds build_camera_id actually
            # changed — only then is it worth running the per-camera storage
            # migration after the save. Unrelated edits (resolution, motion
            # sensitivity, …) skip the analysis pass entirely.
            for key in ("manufacturer", "model", "name", "rtsp_url"):
                if key in camera and existing.get(key) != camera.get(key):
                    id_relevant_changed = True
                    break
            # Non-destructive merge — every key the frontend sent lands
            # on the stored dict at its new value; keys the frontend
            # didn't send stay at their existing value (Python dict.update
            # semantics). Nested dicts (schedule, label_thresholds, …)
            # are still replaced wholesale because the frontend re-sends
            # the entire nested object on every save; partial nested
            # updates would need explicit deep-merge per section.
            existing.update(camera)
        else:
            merged = default_camera(camera)
            self.data.setdefault("cameras", []).append(merged)
            id_relevant_changed = True
        # Resolve the "post-merge canonical record" reference used by the
        # migration + return-id lookup further below. For updates we
        # already mutated existing in place; for inserts we just appended.
        merged = existing if existing else self.data["cameras"][-1]
        self.data.setdefault("ui", {})["wizard_completed"] = True
        # Migrate FIRST (it persists if the id needs to change), then write
        # one final save so any unrelated field updates also land. The
        # migration is idempotent — a no-op pass costs roughly one stat()
        # per legacy folder.
        if id_relevant_changed:
            try:
                from ..storage_migration import migrate as _migrate

                _migrate(self, self.path.parent)
            except Exception as e:
                log.warning("[Settings] per-cam migration after save failed: %s", e)
        # Migration may rename a cam id and leave a sibling entry with
        # the new id already present (rare, but possible when a discovery
        # re-add races with a manual rename) — dedupe before writing so
        # the on-disk file never carries the same id twice.
        self._dedupe_cameras_by_id()
        self.save()
        return self._canonical_id_after_migration(merged, in_id)

    def _canonical_id_after_migration(self, merged: dict, in_id: str) -> str:
        """The id that now points at ``merged``.

        The cam dict in ``self.data`` was mutated in place by the storage
        migration, so the record is looked up by its input identity
        (manufacturer / model / name / rtsp_url) rather than by the id we
        arrived with — that id may be exactly what just changed.
        """
        for c in self.data.get("cameras", []) or []:
            same_record = (
                c.get("name") == merged.get("name")
                and c.get("rtsp_url") == merged.get("rtsp_url")
                and c.get("manufacturer", "") == merged.get("manufacturer", "")
                and c.get("model", "") == merged.get("model", "")
            )
            if same_record or c.get("id") == in_id:
                return c.get("id", in_id)
        return in_id

    def delete_camera(self, cam_id: str) -> bool:
        cameras = self.data.get("cameras", [])
        before = len(cameras)
        self.data["cameras"] = [c for c in cameras if c.get("id") != cam_id]
        if len(self.data["cameras"]) < before:
            self.save()
            return True
        return False
