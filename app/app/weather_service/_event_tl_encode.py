"""Encode + publish for the weather event timelapse.

The back half of one capture: turn the scratch dir into an mp4, write the
thumbnail and the sighting manifest, hand the clip to the Telegram
pipeline. Split from ``_event_tl.py`` when the pre-roll ring landed —
capture and publish are separate concerns and the module was at its size
ceiling.

The encode goes through a dot-prefixed part-file so a container restart
mid-encode can never leave a truncated mp4 where the sighting lister
would find it.
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime
from pathlib import Path

from ._consts import _atomic_write_json, _safe_subset, log
from ._event_tl_ring import PART_MP4_PREFIX


class EventTLEncodeMixin:
    """Encode / manifest / push. Mixin for WeatherService."""

    def _encode_event_tl_clip(self, images: list, out_dir: Path, stem: str, fps: int, qa_ctx: dict):
        """Encode to a dot-prefixed part-file, then atomically rename.

        A container restart mid-encode must not leave a truncated mp4 in
        the sightings dir: both the manifest lister and the rescan skip
        dot-prefixed entries, and `_event_tl_boot_cleanup` removes them on
        the next boot. Returns the final mp4 path, or None on failure."""
        part_path = out_dir / f"{PART_MP4_PREFIX}{stem}.mp4"
        mp4_path = out_dir / f"{stem}.mp4"
        from ..timelapse import TimelapseBuilder

        tb = TimelapseBuilder(self._sightings_dir().parent.parent)
        target_seconds = max(15, min(45, len(images) // max(1, fps)))
        written = tb._write_video(images, part_path, target_seconds, fps, qa_ctx=qa_ctx)
        if not written or not part_path.exists():
            for leftover in (part_path, part_path.with_suffix(".jpg")):
                if leftover.exists():
                    with contextlib.suppress(Exception):
                        leftover.unlink()
            return None
        os.replace(str(part_path), str(mp4_path))
        # _write_video drops a sibling thumbnail + encode-diag next to its
        # out_path; carry the diag over and drop the thumb (the caller
        # writes its own from the middle raw frame).
        diag = part_path.with_suffix(part_path.suffix + ".encode-diag.txt")
        if diag.exists():
            with contextlib.suppress(Exception):
                os.replace(
                    str(diag), str(mp4_path.with_suffix(mp4_path.suffix + ".encode-diag.txt"))
                )
        part_thumb = part_path.with_suffix(".jpg")
        if part_thumb.exists():
            with contextlib.suppress(Exception):
                part_thumb.unlink()
        return mp4_path

    @staticmethod
    def _build_event_tl_manifest(kw: dict, mp4_path: Path, thumb_path: Path, n_images: int) -> dict:
        """Sighting manifest for one finished event timelapse."""
        cam_id = kw["cam_id"]
        trigger = kw["trigger"]
        fps = kw["fps"]
        manifest = {
            "id": f"{cam_id}__{trigger}__{kw['stem']}",
            "cam_id": cam_id,
            "cam_name": kw["cam_name"],
            "event_type": "event_timelapse",
            "trigger": trigger,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "score": round(float(kw["score"]), 3),
            "severity": round(float(kw["score"]), 3),
            "window_min": kw["window_min"],
            "interval_s": kw["interval_s"],
            "fps": fps,
            # Pre-roll bookkeeping — the manifest is the only place the
            # UI can learn that the first N frames predate the trigger.
            "prebuffer_frames": kw["n_pre"],
            "prebuffer_min": round(kw["n_pre"] * kw["interval_s"] / 60.0, 1),
            "api_snapshot": _safe_subset(
                kw["api_now"],
                [
                    "time",
                    "precipitation",
                    "snowfall",
                    "lightning_potential",
                    "visibility",
                    "wind_gusts_10m",
                    "cloud_cover",
                    "weather_code",
                ],
            ),
            "api_forecast": kw["fc_snapshot"],
            "clip_path": f"weather/{cam_id}/event_timelapse/{mp4_path.name}",
            "thumb_path": f"weather/{cam_id}/event_timelapse/{thumb_path.name}",
            "duration_s": max(1, n_images // max(1, fps)),
            "width": 0,
            "height": 0,
        }
        try:
            import cv2

            cap = cv2.VideoCapture(str(mp4_path))
            try:
                manifest["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                manifest["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            finally:
                cap.release()
        except Exception:
            pass
        return manifest

    def _finish_event_tl_clip(self, **kw):
        """Encode the scratch frames, write the thumbnail + manifest and
        hand the clip to the Telegram pipeline."""
        cam_id = kw["cam_id"]
        cam_name = kw["cam_name"]
        trigger = kw["trigger"]
        out_dir = kw["out_dir"]
        frames_dir = kw["frames_dir"]
        stem = kw["stem"]
        fps = kw["fps"]
        images = sorted(frames_dir.glob("*.jpg"))
        qa_ctx = {
            "camera_id": cam_id,
            "profile_name": trigger,
            "frames_dir": frames_dir,
            "settings_store": self.settings_store,
        }
        try:
            mp4_path = self._encode_event_tl_clip(images, out_dir, stem, fps, qa_ctx)
        except Exception as e:
            log.warning("[weather] Encode crash %s %s: %s", cam_name, trigger, e)
            return
        if mp4_path is None:
            log.warning("[weather] Encode failed: %s %s", cam_name, trigger)
            return
        thumb_path = out_dir / f"{stem}.jpg"
        try:
            mid = images[len(images) // 2]
            thumb_path.write_bytes(mid.read_bytes())
        except Exception:
            pass
        manifest = self._build_event_tl_manifest(kw, mp4_path, thumb_path, len(images))
        _atomic_write_json(out_dir / f"{stem}.json", manifest)
        log.info("[weather] Manifest geschrieben: %s · score=%.2f", manifest["id"], kw["score"])
        # Optional Telegram push reuses the existing weather pipeline. The
        # event_type for push gating is the trigger name (matches the
        # WEATHER_TYPES map key on the frontend AND the per-event toggle in
        # the push.weather.events block once users add it).
        push_manifest = dict(manifest)
        push_manifest["event_type"] = trigger
        self._maybe_push_telegram(push_manifest, mp4_path)
