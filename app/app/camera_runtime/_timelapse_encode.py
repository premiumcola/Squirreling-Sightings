"""Timelapse window finalisation — encode, publish, delete the frames.

Split out of ``_timelapse.py``, which had grown to 821 lines against a
500-line ceiling, with a single 241-line ``_finalize_timelapse_window``
against an 80-line one. Capture (what to grab, and how often) and
finalisation (what to do with a closed window) are orthogonal: capture
runs every interval and must stay cheap, finalisation runs once per
window and does ffmpeg, EventStore and Telegram work.

The five steps of a finalise are one method each, so the failure of any
one of them reads as its own log line and none of them can silently
swallow the next:

    encode → thumbnail → sidecar JSON → EventStore event → Telegram push

and then the frames go, encode success or not — a window that cannot be
encoded twice will not be encoded a third time, and keeping its frames
only grows the largest transient directory on the box.
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path

from .. import timelapse_storage as _tl_storage
from ..io_utils import atomic_write_json
from ..timelapse_windows import window_key as _tl_window_key
from ._consts import log_tl

# Profile name → the word that reads naturally in a German push.
_PROFILE_DE = {
    "daily": "Tag",
    "weekly": "Woche",
    "monthly": "Monat",
    "quarterly": "Quartal",
    "yearly": "Jahr",
    "custom": "Custom",
}


class TimelapseEncodeMixin:
    """Everything that happens to a timelapse window after it closes."""

    # ── Boot-time reconcile ──────────────────────────────────────────────

    def _cleanup_stale_timelapse_frames(self):
        """Startup pass over the frame tree — one INFO line per window.

        Runs once from ``start()`` BEFORE any capture thread exists, so
        nothing here can be describing an active window:

        * closed windows are preserved — the profile loop's first
          ``_finalize_orphaned_windows`` encodes them, which is what
          makes a restart mid-window non-destructive;
        * abandoned same-day ``custom`` windows (a mid-run window the
          process was killed out of, superseded by a newer one) are
          removed.

        Window keys are per-period now (``2026-W35``, ``2026-08``,
        ``2026-Q3``), so the old ``name[:10] < today`` string compare no
        longer identifies a closed window — ask timelapse_windows for
        the current key instead.
        """
        storage_root = Path(self.global_cfg["storage"]["root"])
        today = datetime.now().strftime("%Y-%m-%d")
        tl_base = storage_root / "timelapse_frames" / self.camera_id
        if not tl_base.exists():
            return
        for profile_dir in tl_base.iterdir():
            if not profile_dir.is_dir():
                continue
            # None for the custom profile — its window key encodes the
            # wall-clock start, which only the running loop knows.
            current_key = _tl_window_key(profile_dir.name)
            all_windows = sorted([d for d in profile_dir.iterdir() if d.is_dir()])
            for i, window_dir in enumerate(all_windows):
                superseded_custom = (
                    current_key is None
                    and window_dir.name[:10] == today
                    and i < len(all_windows) - 1
                )
                if superseded_custom:
                    self._drop_abandoned_window(profile_dir.name, window_dir)
                elif window_dir.name != current_key:
                    n = len(list(window_dir.glob("*.jpg")))
                    log_tl.info(
                        "[%s][media] closed-window frames preserved for encoding: "
                        "%s/%s (%d frames) — will be encoded on profile startup",
                        self.camera_id,
                        profile_dir.name,
                        window_dir.name,
                        n,
                    )

    def _drop_abandoned_window(self, profile_name: str, window_dir: Path) -> None:
        try:
            shutil.rmtree(str(window_dir))
            log_tl.info(
                "[%s][media] cleaned abandoned window (today): %s/%s",
                self.camera_id,
                profile_name,
                window_dir.name,
            )
        except Exception as e:
            log_tl.warning(
                "[%s][media] abandoned cleanup failed for %s: %s",
                self.camera_id,
                window_dir,
                e,
            )

    # ── Finalise ─────────────────────────────────────────────────────────

    def _finalize_timelapse_window(
        self, profile_name: str, window_key: str, target_s: int, target_fps: int, period_s: int = 0
    ):
        """Encode a closed window, publish it, then delete its frames."""
        storage_root = Path(self.global_cfg["storage"]["root"])
        frames_dir = storage_root / "timelapse_frames" / self.camera_id / profile_name / window_key
        if not frames_dir.exists():
            log_tl.debug(
                "[%s][%s] finalize: no frames dir for window %s",
                self.camera_id,
                profile_name,
                window_key,
            )
            return
        images = sorted(frames_dir.glob("*.jpg"))
        n = len(images)
        if n < 2:
            log_tl.debug(
                "[%s][%s] finalize: only %d frames in window %s — skipping encode",
                self.camera_id,
                profile_name,
                n,
                window_key,
            )
            self._drop_window_frames(frames_dir, profile_name, window_key, 0)
            return

        log_tl.info(
            "[%s][timelapse] encoding window %s/%s (%d frames → %ds @ %dfps)",
            self.camera_id,
            profile_name,
            window_key,
            n,
            target_s,
            target_fps,
        )
        out_dir = storage_root / "timelapse" / self.camera_id
        out_dir.mkdir(parents=True, exist_ok=True)
        stem, out_path, ok = self._encode_window(
            storage_root,
            out_dir,
            frames_dir,
            images,
            profile_name,
            window_key,
            target_s,
            target_fps,
            period_s,
        )
        if ok:
            size_mb = round(out_path.stat().st_size / 1024 / 1024, 2) if out_path.exists() else 0
            thumb_path = out_dir / f"{stem}.jpg"
            self._write_window_thumb(out_path, thumb_path)
            self._write_window_sidecar(
                out_dir,
                frames_dir,
                out_path,
                stem,
                profile_name,
                window_key,
                period_s,
                target_s,
                n,
                size_mb,
            )
            self._register_window_event(
                out_path,
                thumb_path,
                stem,
                profile_name,
                window_key,
                period_s,
                target_s,
                n,
                size_mb,
            )
        else:
            log_tl.warning(
                "[%s][timelapse] encode failed for window %s/%s",
                self.camera_id,
                profile_name,
                window_key,
            )
        # Always clean up frames regardless of encode outcome.
        self._drop_window_frames(frames_dir, profile_name, window_key, n)

    def _encode_window(
        self,
        storage_root: Path,
        out_dir: Path,
        frames_dir: Path,
        images: list,
        profile_name: str,
        window_key: str,
        target_s: int,
        target_fps: int,
        period_s: int,
    ) -> tuple[str, Path, bool]:
        """Run the encoder. Returns ``(stem, out_path, succeeded)``."""
        from .. import app_state as _app_state
        from ..camera_id import camera_slug
        from ..timelapse import TimelapseBuilder as _TimelapseBuilder

        builder = _TimelapseBuilder(storage_root)
        # Per-camera slug so cross-camera downloads of the same
        # window/profile/target don't collide on the user's disk.
        cam_slug = camera_slug(getattr(_app_state, "store", None), self.camera_id)
        stem = builder.make_output_name(
            window_key, profile_name, period_s, target_s, cam_slug=cam_slug
        )
        out_path = out_dir / f"{stem}.mp4"
        # QA sidecar context — embeds this window's capture _stats.json
        # and enables fps auto-adjust per (camera_id, profile_name).
        qa_ctx = {
            "camera_id": self.camera_id,
            "profile_name": profile_name,
            "frames_dir": frames_dir,
            "settings_store": getattr(_app_state, "store", None),
        }
        _t0 = time.monotonic()
        path = builder._write_video(images, out_path, target_s, target_fps, qa_ctx=qa_ctx)
        if path:
            size_mb = round(out_path.stat().st_size / 1024 / 1024, 2) if out_path.exists() else 0
            log_tl.info(
                "[%s][timelapse] encoded %s: %d frames → %ds video in %.1fs real time (%.1f MB)",
                self.camera_id,
                out_path.name,
                len(images),
                target_s,
                time.monotonic() - _t0,
                size_mb,
            )
        return stem, out_path, bool(path)

    def _write_window_thumb(self, out_path: Path, thumb_path: Path) -> None:
        """Grab the middle frame of the finished video as a poster."""
        if thumb_path.exists():
            return
        try:
            import cv2 as _cv2

            cap = _cv2.VideoCapture(str(out_path))
            total = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
            if total > 0:
                cap.set(_cv2.CAP_PROP_POS_FRAMES, total // 2)
            ok_t, frame_t = cap.read()
            cap.release()
            if ok_t and frame_t is not None:
                tw = frame_t.shape[1]
                if tw > 640:
                    scale = 640 / tw
                    frame_t = _cv2.resize(frame_t, (640, int(frame_t.shape[0] * scale)))
                _cv2.imwrite(str(thumb_path), frame_t, [int(_cv2.IMWRITE_JPEG_QUALITY), 82])
        except Exception as _te:
            log_tl.debug("[%s][timelapse] thumb failed: %s", self.camera_id, _te)

    def _write_window_sidecar(
        self,
        out_dir: Path,
        frames_dir: Path,
        out_path: Path,
        stem: str,
        profile_name: str,
        window_key: str,
        period_s: int,
        target_s: int,
        n: int,
        size_mb: float,
    ) -> None:
        """Sidecar JSON next to the video — the fast index the
        /api/camera/<id>/timelapse/list endpoint reads."""
        try:
            from ..frame_helpers import read_capture_stats

            meta = {
                "event_id": f"tl_{stem}",
                "camera_id": self.camera_id,
                "type": "timelapse",
                "profile": profile_name,
                "window_key": window_key,
                "period_s": period_s,
                "target_s": target_s,
                "frame_count": n,
                "time": datetime.now().isoformat(timespec="seconds"),
                "filename": out_path.name,
                "relpath": f"timelapse/{self.camera_id}/{out_path.name}",
                "size_mb": size_mb,
            }
            cap_stats = read_capture_stats(frames_dir)
            if cap_stats:
                meta["capture_stats"] = cap_stats
            meta_path = out_dir / f"{stem}.json"
            atomic_write_json(meta_path, meta)
            log_tl.debug("[%s][timelapse] sidecar JSON written: %s", self.camera_id, meta_path.name)
        except Exception as e:
            log_tl.warning("[%s][timelapse] sidecar write failed: %s", self.camera_id, e)

    def _register_window_event(
        self,
        out_path: Path,
        thumb_path: Path,
        stem: str,
        profile_name: str,
        window_key: str,
        period_s: int,
        target_s: int,
        n: int,
        size_mb: float,
    ) -> None:
        """Unified EventStore entry, then the Telegram push."""
        video_rel = f"timelapse/{self.camera_id}/{out_path.name}"
        try:
            public_base = (self.global_cfg.get("server", {}).get("public_base_url") or "").rstrip(
                "/"
            )
            thumb_rel = f"timelapse/{self.camera_id}/{stem}.jpg" if thumb_path.exists() else None
            thumb_url = (
                (f"{public_base}/media/{thumb_rel}" if public_base else f"/media/{thumb_rel}")
                if thumb_rel
                else None
            )
            tl_event = {
                "event_id": f"tl_{stem}",
                "camera_id": self.camera_id,
                "camera_name": self.cfg.get("name", self.camera_id),
                "type": "timelapse",
                "labels": ["timelapse"],
                "top_label": "timelapse",
                "time": datetime.now().isoformat(timespec="seconds"),
                "profile": profile_name,
                "window_key": window_key,
                "period_s": period_s,
                "target_s": target_s,
                "frame_count": n,
                "filename": out_path.name,
                "video_relpath": video_rel,
                "video_url": f"{public_base}/media/{video_rel}"
                if public_base
                else f"/media/{video_rel}",
                "snapshot_relpath": thumb_rel,
                "snapshot_url": thumb_url,
                "thumb_url": thumb_url,
                "size_mb": size_mb,
                "duration_s": 0.0,
                "file_size_bytes": out_path.stat().st_size if out_path.exists() else 0,
                # Timelapse uses the same event shape as motion clips so
                # the lightbox + grid render uniformly, but the
                # detection-pipeline fields don't apply — the frontend
                # sees `mode: "timelapse"` and shows scrubber-only chrome.
                "recording_settings": {"mode": "timelapse"},
            }
            self.store.add_event(self.camera_id, tl_event)
            log_tl.info(
                "[%s][timelapse] event registered: %s", self.camera_id, tl_event["event_id"]
            )
        except Exception as e:
            log_tl.warning("[%s][timelapse] EventStore register failed: %s", self.camera_id, e)
        self._push_window_to_telegram(out_path, profile_name, target_s, video_rel)

    def _push_window_to_telegram(
        self, out_path: Path, profile_name: str, target_s: int, video_rel: str
    ) -> None:
        """Gated by push.timelapse.enabled inside the notifier, so the
        global toggle disables this without touching the camera config."""
        try:
            if self.notifier and hasattr(self.notifier, "send_timelapse_alert"):
                self.notifier.send_timelapse_alert(
                    video_path=out_path,
                    cam_name=self.cfg.get("name", self.camera_id),
                    profile_de=_PROFILE_DE.get(profile_name, profile_name),
                    duration_s=int(target_s),
                    rel_path=video_rel,
                )
        except Exception as e:
            log_tl.warning("[%s][timelapse] push failed: %s", self.camera_id, e)

    def _drop_window_frames(
        self, frames_dir: Path, profile_name: str, window_key: str, n: int
    ) -> None:
        """Remove the encoded window's frames and drop the cached size.

        The storage panel caches its scandir for 60 s — invalidating here
        makes it report the new total the moment the frames are gone
        instead of showing a stale quarter-gigabyte for up to a minute.
        """
        try:
            shutil.rmtree(str(frames_dir))
            log_tl.info(
                "[%s][timelapse] cleaned %d frames for window %s/%s",
                self.camera_id,
                n,
                profile_name,
                window_key,
            )
        except Exception as e:
            log_tl.warning("[%s][timelapse] frame cleanup failed: %s", self.camera_id, e)
        _tl_storage.invalidate(self.camera_id, profile_name)

    def _finalize_orphaned_windows(
        self, profile_name: str, current_key: str, target_s: int, target_fps: int, period_s: int
    ):
        """Encode every window of this profile other than ``current_key``.

        Called after a new window opens, so a window left behind by a
        restart or a crashed encode still becomes a video instead of
        sitting on disk forever.
        """
        storage_root = Path(self.global_cfg["storage"]["root"])
        profile_dir = storage_root / "timelapse_frames" / self.camera_id / profile_name
        if not profile_dir.exists():
            return
        for window_dir in sorted(profile_dir.iterdir()):
            if not window_dir.is_dir() or window_dir.name == current_key:
                continue
            log_tl.info(
                "[%s][%s] orphaned window found: %s — finalizing",
                self.camera_id,
                profile_name,
                window_dir.name,
            )
            self._finalize_timelapse_window(
                profile_name, window_dir.name, target_s, target_fps, period_s
            )
