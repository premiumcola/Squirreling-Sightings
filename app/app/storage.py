from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from . import storage_retention

# The judgement helpers and the retention sweep live in
# `storage_retention` together — this file only owns the store. They stay
# importable from here because that is where every caller (and the
# retention test) already looks for them.
from .storage_retention import (
    JUDGEMENT_FIELDS,
    is_judged_event,
    keep_judged_events_enabled,
)

__all__ = [
    "JUDGEMENT_FIELDS",
    "EventStore",
    "event_date_subdir",
    "is_judged_event",
    "keep_judged_events_enabled",
]

log = logging.getLogger(__name__)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` via temp file + os.replace so a crash
    mid-write never leaves a truncated or corrupt file.

    The temp name carries pid + thread id. A single shared ``<name>.tmp``
    is not safe when two writers target the same path: writer A can
    finish its write, writer B truncate and half-fill the same temp, and
    A's ``os.replace`` then publish B's partial content as the real file.
    Distinct temps make the replace the only interleaving point, and
    ``os.replace`` is atomic — so a reader sees either version whole.

    ``fsync`` before the replace so a power cut can't leave the rename
    durable while the data behind it is still in the page cache.
    """
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def event_date_subdir(event_id: str) -> str | None:
    """Derive the ``YYYY-MM-DD`` date-folder name from an event_id whose
    first 8 chars are ``YYYYMMDD`` (the standard
    ``%Y%m%d-%H%M%S-%f`` id format).

    Returns ``None`` for custom / legacy ids that don't start with 8
    digits, so callers fall back to the camera-root location and nothing
    breaks. This is the same date folder the mp4/jpg already use, so the
    event JSON ends up co-located with its media instead of littering
    the camera root."""
    head = event_id[:8]
    if len(head) == 8 and head.isdigit():
        return f"{head[:4]}-{head[4:6]}-{head[6:8]}"
    return None


class EventStore:
    def __init__(self, root: str):
        self.root = Path(root)
        self.events_dir = self.root / "motion_detection"
        # One-time migration: rename legacy events/ → motion_detection/
        old_events = self.root / "events"
        if old_events.exists() and not self.events_dir.exists():
            try:
                old_events.rename(self.events_dir)
            except Exception:
                # Best-effort one-time migration. Falling through is
                # fine — the mkdir() below ensures the canonical dir
                # exists regardless. Breadcrumb for the DEBUG channel.
                log.debug(
                    "[storage] legacy events/ → motion_detection/ rename skipped", exc_info=True
                )
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def _cam_dir(self, camera_id: str) -> Path:
        """Writable camera dir, created on demand. Write paths only."""
        p = self.events_dir / camera_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def camera_dir(self, camera_id: str) -> Path:
        """Read-only view of the camera dir — never created.

        Every read used to go through ``_cam_dir``, which mkdirs. So the
        read-only integrity report materialised
        ``motion_detection/<id>/`` for every id it inspected, unclaimed
        ghost ids included, and its second run then reported the
        directory its first run had fabricated. Reads take this path;
        only :meth:`add_event` may create.
        """
        return self.events_dir / camera_id

    def add_event(self, camera_id: str, payload: dict):
        payload = dict(payload)
        event_id = payload.get("event_id") or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        payload["event_id"] = event_id
        # Co-locate the event JSON with its media in the date subfolder
        # (motion_detection/<cam>/<YYYY-MM-DD>/<event_id>.json) instead
        # of littering the camera root. Falls back to the camera root for
        # custom/legacy ids whose first 8 chars aren't YYYYMMDD. Reads all
        # use rglob(), so both locations resolve during the transition.
        cam_dir = self._cam_dir(camera_id)
        subdir = event_date_subdir(event_id)
        if subdir is not None:
            target_dir = cam_dir / subdir
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = cam_dir
        path = target_dir / f"{event_id}.json"
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
        return path

    def get_event(self, camera_id: str, event_id: str) -> dict | None:
        cam_dir = self.camera_dir(camera_id)
        matches = list(cam_dir.rglob(f"{event_id}.json"))
        if not matches:
            return None
        try:
            return json.loads(matches[0].read_text(encoding="utf-8"))
        except Exception as e:
            # Returning None silently was hiding malformed event JSON
            # from operators — surface it once so a corrupted file
            # gets a clear signal in `docker logs`.
            log.warning("[storage] malformed event JSON %s: %s", matches[0], e)
            return None

    def find_event_anywhere(self, event_id: str) -> dict | None:
        """Cross-camera lookup for deep-links from Telegram. Walks every
        camera folder under motion_detection/ until a matching JSON is
        found. Returns the parsed event dict (with camera_id injected
        when missing) or None."""
        if not event_id or not self.events_dir.exists():
            return None
        for cam_dir in self.events_dir.iterdir():
            if not cam_dir.is_dir():
                continue
            matches = list(cam_dir.rglob(f"{event_id}.json"))
            if not matches:
                continue
            try:
                payload = json.loads(matches[0].read_text(encoding="utf-8"))
                payload.setdefault("camera_id", cam_dir.name)
                return payload
            except Exception as e:
                log.warning("[storage] malformed event JSON %s: %s", matches[0], e)
                continue
        return None

    def update_event(self, camera_id: str, event_id: str, payload: dict) -> bool:
        cam_dir = self.camera_dir(camera_id)
        matches = list(cam_dir.rglob(f"{event_id}.json"))
        if not matches:
            return False
        _atomic_write_text(matches[0], json.dumps(payload, ensure_ascii=False, indent=2))
        return True

    def delete_event_by_id(self, camera_id: str, event_id: str) -> bool:
        """Remove every event-JSON matching `<event_id>.json` under the camera tree.
        Returns True if at least one file was unlinked."""
        cam_dir = self.camera_dir(camera_id)
        matches = list(cam_dir.rglob(f"{event_id}.json"))
        for m in matches:
            try:
                m.unlink()
            except Exception:
                log.debug("[storage] unlink %s failed (best-effort)", m, exc_info=True)
        return bool(matches)

    def _filter_events(
        self,
        camera_id: str,
        label: str | None = None,
        labels: list | None = None,
        start: str | None = None,
        end: str | None = None,
        media_only: bool = False,
        type: str | None = None,
        bird_species: str | None = None,
    ):
        """Filter events for a camera. `labels` (list) takes precedence over `label` (str).
        Multi-label filter uses OR logic: event matches if any of its labels is in the filter set.
        media_only=True: skip metadata-only events (no snapshot/video file) — used by the viewer.
        bird_species: case-insensitive exact match against event.bird_species (used by the
        Sichtungen drilldown to pull every photo of e.g. "Grünfink")."""
        filter_set: set | None = None
        if labels:
            filter_set = set(labels)
        elif label:
            filter_set = {label}
        species_key = (bird_species or "").lower().strip() or None

        items = []
        cam_dir = self.camera_dir(camera_id)
        for file in cam_dir.rglob("*.json"):
            # `<event_id>.tracks.json` is the tracking worker's sidecar
            # for ONE existing event, not an event. Two other call sites
            # (routes/media, judged_event_ids) already filtered it; this
            # one did not, so every indexed clip was counted twice —
            # stats_range reported double the events, and the same
            # defect flowed through aggregate_summary into the Telegram
            # daily report. A sidecar carries no "time" key, so the
            # start/end guard below could not reject it either.
            if file.name.endswith(".tracks.json"):
                continue
            try:
                obj = json.loads(file.read_text(encoding="utf-8"))
            except Exception as e:
                # A malformed event JSON used to vanish from list_events
                # without a peep. Surface it as a one-line warning so
                # the operator notices and can investigate / repair.
                log.warning("[storage] malformed event JSON %s: %s", file, e)
                continue
            if media_only:
                has_media = (
                    obj.get("snapshot_relpath")
                    or obj.get("snapshot_url")
                    or obj.get("video_relpath")
                    or obj.get("video_url")
                )
                if not has_media:
                    continue
            t = obj.get("time", "")
            if start and t and t < start:
                continue
            if end and t and t > end:
                continue
            if type is not None and obj.get("type") != type:
                continue
            if filter_set:
                evt_labels = set(obj.get("labels", []))
                extras = {obj.get("cat_name"), obj.get("bird_species")} - {None}
                if not (filter_set & (evt_labels | extras)):
                    continue
            if species_key is not None:
                if (obj.get("bird_species") or "").lower().strip() != species_key:
                    continue
            items.append(obj)
        items.sort(key=lambda x: x.get("time", ""), reverse=True)
        return items

    def list_events(
        self,
        camera_id: str,
        label: str | None = None,
        labels: list | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 24,
        offset: int = 0,
        media_only: bool = False,
        type: str | None = None,
        bird_species: str | None = None,
    ):
        items = self._filter_events(
            camera_id,
            label=label,
            labels=labels,
            start=start,
            end=end,
            media_only=media_only,
            type=type,
            bird_species=bird_species,
        )
        return items[offset : offset + limit]

    def count_events(
        self,
        camera_id: str,
        label: str | None = None,
        labels: list | None = None,
        start: str | None = None,
        end: str | None = None,
        media_only: bool = False,
        bird_species: str | None = None,
    ) -> int:
        return len(
            self._filter_events(
                camera_id,
                label=label,
                labels=labels,
                start=start,
                end=end,
                media_only=media_only,
                bird_species=bird_species,
            )
        )

    def stats_range(
        self,
        camera_id: str,
        label: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ):
        """Statistik range payload — see
        :func:`app.app.storage_stats.stats_range`."""
        from .storage_stats import stats_range

        return stats_range(self, camera_id, label=label, start=start, end=end)

    def aggregate_summary(self, days: int = 1):
        """Telegram daily / weekly roll-up — see
        :func:`app.app.storage_stats.aggregate_summary`."""
        from .storage_stats import aggregate_summary

        return aggregate_summary(self, days)

    def delete_event(self, camera_id: str, event_id: str) -> dict:
        """Delete event JSON and its snapshot/video file. Returns info about what was deleted."""
        cam_dir = self.camera_dir(camera_id)
        matches = list(cam_dir.rglob(f"{event_id}.json"))
        event = None
        if matches:
            json_path = matches[0]
            try:
                event = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception as e:
                # Falling through with event=None still deletes the
                # JSON; sidecars (snapshot/video/tracks) just won't get
                # cleaned because we couldn't read their relpaths.
                log.warning("[storage] malformed event JSON during delete %s: %s", json_path, e)
            json_path.unlink(missing_ok=True)
        snap_deleted = False
        if event and event.get("snapshot_relpath"):
            snap_path = self.root / event["snapshot_relpath"]
            if snap_path.exists():
                snap_path.unlink(missing_ok=True)
                snap_deleted = True
        vid_deleted = False
        tracks_deleted = False
        if event and event.get("video_relpath"):
            vid_path = self.root / event["video_relpath"]
            if vid_path.exists():
                vid_path.unlink(missing_ok=True)
                vid_deleted = True
            # tracks.json sidecar lives next to the mp4 as
            # `<event_id>.tracks.json`. Drop it whenever the event is
            # deleted so the lightbox doesn't try to render boxes
            # against a missing video. The sidecar may also be stored
            # next to the camera root for legacy events without a
            # date-subdir; rglob picks both up.
            for tp in list(cam_dir.rglob(f"{event_id}.tracks.json")):
                try:
                    tp.unlink()
                    tracks_deleted = True
                except Exception:
                    log.debug("[storage] tracks sidecar unlink %s failed", tp, exc_info=True)
            # `<event_id>.best.jpg` is the Telegram-only "best frame"
            # cache (bbox burnt on) — recreated by the next push if
            # tracks.json is rebuilt, but pointless to keep around
            # once the source mp4 is gone.
            for bp in list(cam_dir.rglob(f"{event_id}.best.jpg")):
                try:
                    bp.unlink()
                except Exception:
                    log.debug("[storage] best.jpg unlink %s failed", bp, exc_info=True)
        return {
            "json_deleted": event is not None,
            "snap_deleted": snap_deleted,
            "vid_deleted": vid_deleted,
            "tracks_deleted": tracks_deleted,
        }

    def purge_orphans(self) -> int:
        """Delete event JSON files whose media file no longer exists. Returns count removed."""
        removed = 0
        if not self.events_dir.exists():
            return 0
        for cam_dir in (d for d in self.events_dir.iterdir() if d.is_dir()):
            for jf in list(cam_dir.rglob("*.json")):
                # Skip our own tracking sidecars — they're handled in
                # the second pass below so an orphaned tracks.json
                # (event already deleted) doesn't survive forever.
                if jf.name.endswith(".tracks.json"):
                    continue
                try:
                    obj = json.loads(jf.read_text(encoding="utf-8"))
                except Exception as e:
                    # purge_orphans intentionally treats unparseable
                    # JSON as an orphan (can't validate its media
                    # refs). Log so the deletion is visible.
                    log.warning("[storage] removing malformed event JSON %s: %s", jf, e)
                    jf.unlink(missing_ok=True)
                    removed += 1
                    continue
                snap_rel = obj.get("snapshot_relpath")
                vid_rel = obj.get("video_relpath")
                snap_missing = snap_rel and not (self.root / snap_rel).exists()
                vid_missing = vid_rel and not (self.root / vid_rel).exists()
                # Orphan: has a media reference that no longer exists on disk
                if snap_missing or vid_missing:
                    jf.unlink(missing_ok=True)
                    removed += 1
            # Second pass — tracks.json sidecars whose matching event
            # manifest is already gone (delete_event was bypassed at
            # some point, e.g. manual rm -rf). Stem of "<event_id>.
            # tracks.json" is "<event_id>.tracks"; the event JSON we
            # look for is "<event_id>.json".
            for tp in list(cam_dir.rglob("*.tracks.json")):
                event_id = tp.stem.removesuffix(".tracks")
                if not list(cam_dir.rglob(f"{event_id}.json")):
                    tp.unlink(missing_ok=True)
                    removed += 1
            # Same orphan check for the Telegram-only `.best.jpg`
            # cache. Pattern: `<event_id>.best.jpg` → stem is
            # `<event_id>.best`, the event JSON we look for is
            # `<event_id>.json`.
            for bp in list(cam_dir.rglob("*.best.jpg")):
                event_id = bp.stem.removesuffix(".best")
                if not list(cam_dir.rglob(f"{event_id}.json")):
                    bp.unlink(missing_ok=True)
                    removed += 1
        return removed

    def scan_media_files(self, camera_ids: list[str], public_base_url: str = "") -> int:
        """Register unclaimed media under ``motion_detection/`` — see
        :func:`app.app.storage_scan.scan_media_files`."""
        from .storage_scan import scan_media_files

        return scan_media_files(self, camera_ids, public_base_url)

    def judged_event_ids(self) -> set:
        """Event ids under ``motion_detection/`` carrying a human verdict."""
        return storage_retention.judged_event_ids(self.events_dir)

    def cleanup_old(self, retention_days: int, keep_judged: bool | None = None) -> int:
        """Retire expired files into ``storage/.trash`` — see
        :func:`app.app.storage_retention.cleanup_old` for the rules."""
        return storage_retention.cleanup_old(self, retention_days, keep_judged)
