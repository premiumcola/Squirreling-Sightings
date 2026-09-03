"""``TimelapseBuilder`` — the public entry point of the package.

Composes the encoders (:mod:`._encode`), the container check
(:mod:`._probe`) and the frame scan (:mod:`._scan`) into the two-pass
build the whole app calls: camera timelapses via ``camera_runtime``,
weather event and sun timelapses via ``weather_service``.
"""

from __future__ import annotations

from pathlib import Path

from ..timelapse_frames import frames_for_day_stamped
from ._consts import log
from ._encode import EncodeMixin
from ._labels import _duration_label, _period_label
from ._probe import ProbeMixin
from ._scan import ScanResult, log_scan_summary, scan_frames


def _pick_reference_size(scan: ScanResult, out_path: Path):
    """The output box follows the MAJORITY of the frames.

    Latching the first valid frame's size let one odd frame — a camera
    answering a single snapshot at a different resolution after a
    reconnect — set the aspect for a whole film. The tie-break on
    ``(count, size)`` keeps the pick reproducible: ``max`` on counts
    alone returns whichever key the dict happened to yield first, so two
    builds of the same folder could disagree.
    """
    if not scan.size_counts:
        return scan.ref_size
    majority = max(scan.size_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    if majority != scan.ref_size:
        log.info(
            "[timelapse] %s: %dx%d is the majority frame size (%d/%d), "
            "not the first frame's %sx%s — encoding to the majority",
            out_path.name,
            majority[0],
            majority[1],
            scan.size_counts[majority],
            sum(scan.size_counts.values()),
            scan.ref_size[0] if scan.ref_size else "?",
            scan.ref_size[1] if scan.ref_size else "?",
        )
    return majority


def _effective_fps(n: int, out_path: Path, target_duration_s: int, target_fps: int) -> float:
    """fps = frames / desired duration, capped at ``target_fps``.

    Keeps the encoded length near ``target_duration_s`` regardless of how
    many source frames the window actually captured.
    """
    fps = n / max(1.0, float(target_duration_s))
    fps = min(float(target_fps), max(1.0, fps))
    if fps < 15.0:
        log.warning(
            "[timelapse] %s will play at %.1f fps (< 15) — video will look "
            "choppy; only %d frames for a %ds target. Lower target_seconds "
            "or capture more frequently (shorter interval).",
            out_path.name,
            fps,
            n,
            target_duration_s,
        )
    return fps


def _log_completeness(
    out_path: Path,
    *,
    frames_on_disk: int,
    expected_frames: int,
    skipped: int,
    n: int,
    fps: float,
    target_duration_s: int,
    target_fps: int,
) -> None:
    """The operator-facing block: what was configured, what was on disk,
    what was dropped, and how long the result actually plays."""
    actual_duration = n / fps
    coverage_pct = min(100.0, 100.0 * frames_on_disk / expected_frames)
    shorter = actual_duration < target_duration_s * 0.95
    log.info(
        "[timelapse] %s\n"
        "  config   : %ds @ %dfps = %d frames expected\n"
        "  on disk  : %d frames (%.0f%% of expected%s)\n"
        "  corrupt  : %d frames dropped (%.1f%%)\n"
        "  result   : %.1fs video%s",
        out_path.name,
        target_duration_s,
        target_fps,
        expected_frames,
        frames_on_disk,
        coverage_pct,
        "" if coverage_pct >= 99 else " — app was down/restarting for part of window",
        skipped,
        100.0 * skipped / max(1, skipped + n),
        actual_duration,
        f" ⚠ shorter than target {target_duration_s}s" if shorter else " ✓",
    )


class TimelapseBuilder(EncodeMixin, ProbeMixin):
    def __init__(self, storage_root: str | Path):
        self.root = Path(storage_root)
        self.out_root = self.root / "timelapse"
        self.out_root.mkdir(parents=True, exist_ok=True)

    def _timelapse_frames_dir(self, camera_id: str) -> Path:
        return self.root / "timelapse_frames" / camera_id

    @staticmethod
    def _is_valid_frame(img) -> tuple[bool, str]:
        """Validate a decoded frame before it enters a timelapse video.
        Returns (is_valid, reason_if_rejected).

        Thin wrapper that delegates to ``frame_helpers.is_valid_frame`` so the
        capture loops, the build pre-filter, and the weather captures all
        agree on what a "good" frame looks like. Update thresholds in
        ``frame_helpers`` rather than here."""
        from ..frame_helpers import is_valid_frame as _is_valid

        return _is_valid(img)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _write_video(
        self,
        images: list,
        out_path: Path,
        target_duration_s: int,
        target_fps: int,
        qa_ctx: dict | None = None,
    ) -> str | None:
        """Subsample images, deduplicate, validate each frame, skip corrupt ones, write to out_path.
        Uses ffmpeg (H.264, small files, iOS-safe) with OpenCV mp4v as fallback.
        Two-pass: Pass 1 validates + deduplicates (no frame data kept in memory),
        Pass 2 encodes. FPS is computed from actual unique frame count so the encoded
        video length honours target_duration_s regardless of how many frames were captured.
        Also writes a .jpg thumbnail (middle valid frame, ≤640 px wide).
        Returns path string or None on failure."""
        # Record original frame count for completeness reporting
        frames_on_disk = len(images)
        expected_frames = max(2, target_duration_s * target_fps)

        # Limit source to what we'd need at target_fps — avoids processing thousands of frames
        if frames_on_disk > expected_frames:
            step = frames_on_disk / expected_frames
            images = [images[int(i * step)] for i in range(expected_frames)]

        scan = scan_frames(images, self._is_valid_frame)
        log_scan_summary(scan, out_path)
        if len(scan.valid_paths) < 2:
            log.warning(
                "[timelapse] only %d valid frames (of %d total) — skipping encode for %s",
                len(scan.valid_paths),
                scan.total_input,
                out_path.name,
            )
            return None

        n = len(scan.valid_paths)
        fps = _effective_fps(n, out_path, target_duration_s, target_fps)
        _log_completeness(
            out_path,
            frames_on_disk=frames_on_disk,
            expected_frames=expected_frames,
            skipped=scan.skipped,
            n=n,
            fps=fps,
            target_duration_s=target_duration_s,
            target_fps=target_fps,
        )

        ref_size = _pick_reference_size(scan, out_path)
        path = self._encode(scan.valid_paths, out_path, fps, ref_size)
        if path is None:
            return None
        if not self._accept_or_reject(
            out_path,
            encode_args={
                "valid_paths_count": n,
                "target_duration_s": target_duration_s,
                "target_fps": target_fps,
                "effective_fps": fps,
                "ref_size": ref_size,
            },
        ):
            return None

        # ── Thumbnail from middle valid frame ─────────────────────────────────
        self._write_thumbnail(scan.valid_paths[n // 2], out_path)
        self._run_qa_sidecar(out_path, target_duration_s, target_fps, qa_ctx)
        return path

    def _encode(self, valid_paths: list, out_path: Path, fps: float, ref_size) -> str | None:
        """ffmpeg first, OpenCV as the fallback."""
        path = self._write_video_ffmpeg(valid_paths, out_path, fps, ref_size)
        if path is None:
            log.debug(
                "[timelapse] ffmpeg unavailable/failed, falling back to OpenCV for %s",
                out_path.name,
            )
            path = self._write_video_opencv(valid_paths, out_path, fps, ref_size)
        if path is None:
            log.warning("[timelapse] encode failed for %s", out_path.name)
        return path

    def _accept_or_reject(self, out_path: Path, *, encode_args: dict) -> bool:
        """Pass 3: validate the encoded MP4, deleting it if it is broken.

        ffmpeg occasionally exits 0 while writing a tiny / single-frame /
        zero-duration container (cleanup races, codec crashes, an empty
        concat list slipping through). ffprobe catches those before the
        file lands in /storage/timelapse and confuses the operator. On
        rejection we delete the bad MP4 and leave a sidecar diag file so
        the rejection is not silent.
        """
        ok, reason, probe_info = self._ffprobe_validate(out_path)
        if ok:
            return True
        log.warning(
            "[timelapse] encode produced invalid MP4 %s — %s · deleting + writing diag",
            out_path.name,
            reason,
        )
        self._write_encode_diag(out_path, reason, probe_info, encode_args=encode_args)
        try:
            out_path.unlink()
        except Exception as e:
            log.debug("[timelapse] unlink of bad mp4 %s failed: %s", out_path.name, e)
        return False

    @staticmethod
    def _run_qa_sidecar(
        out_path: Path, target_duration_s: int, target_fps: int, qa_ctx: dict | None
    ) -> None:
        """Quality-analysis sidecar (cm-36 / timelapse-quality pass).

        Decodes the just-written mp4 frame-by-frame, computes pHash
        duplicate ratio + freeze clusters, embeds any matching
        capture-side _stats.json, grades the build, and writes
        <mp4>.qa.json. Best-effort — a sidecar write failure logs but
        does not fail the build. Camera id is derived from the output
        path; the caller can pass settings_store + frames_dir +
        profile_name through the kwargs the public build_* methods
        accept (cm-37 / qa hooks).
        """
        try:
            from ..timelapse_qa import write_qa_sidecar

            ctx = qa_ctx or {}
            write_qa_sidecar(
                out_path,
                declared_fps=float(target_fps),
                target_duration_s=float(target_duration_s),
                frames_dir=ctx.get("frames_dir"),
                camera_id=ctx.get("camera_id"),
                profile_name=ctx.get("profile_name"),
                validator_profile_used=ctx.get("validator_profile_used"),
                settings_store=ctx.get("settings_store"),
            )
        except Exception as e:
            log.debug("[timelapse] QA sidecar pass swallowed: %s", e)

    # ── Naming helpers ────────────────────────────────────────────────────────

    def make_output_name(
        self, window_key: str, profile_name: str, period_s: int, target_s: int, cam_slug: str = ""
    ) -> str:
        """Generate a human-readable filename stem.

        Example without slug: ``'2026-04-14_020435_custom_1min_to_10sec'``
        Example with slug:    ``'2026-04-14_020435_custom_1min_to_10sec_garten'``

        ``cam_slug`` is a filesystem-safe identifier
        (``camera_id.camera_slug``) appended so cross-camera
        downloads / shares don't collide on the same stem. Empty
        string leaves the legacy filename unchanged — keeps the
        callsite signature backward-compatible with any caller
        that hasn't been updated to pass the slug.
        """
        p_label = _period_label(period_s)
        d_label = _duration_label(target_s)
        stem = f"{window_key}_{profile_name}_{p_label}_to_{d_label}"
        return f"{stem}_{cam_slug}" if cam_slug else stem

    # ── Frame discovery ───────────────────────────────────────────────────────

    def frames_for_day_stamped(self, camera_id: str, day: str) -> list[tuple[float, Path]]:
        """``(mtime, path)`` for every frame of ``day``, oldest first.
        See :mod:`timelapse_frames` for what "for ``day``" means per
        profile."""
        return frames_for_day_stamped(self._timelapse_frames_dir(camera_id), day)

    def frames_for_day(self, camera_id: str, day: str) -> list[Path]:
        """Every captured frame for ``day``, chronologically."""
        return [p for _, p in self.frames_for_day_stamped(camera_id, day)]

    def build_period(
        self,
        camera_id: str,
        day: str,
        target_duration_s: int = 60,
        target_fps: int = 30,
        period: str = "day",
        force: bool = False,
        images_override: list | None = None,
        cam_slug: str = "",
        qa_ctx: dict | None = None,
    ) -> str | None:
        """Build one day's timelapse on demand, from whichever layout
        holds that day's frames (see :meth:`frames_for_day`).
        ``cam_slug`` appended to the stem for unique cross-camera
        download filenames; see :func:`make_output_name`.
        """
        if images_override is not None:
            images = list(images_override)
        else:
            images = self.frames_for_day(camera_id, day)

        if len(images) < 2:
            return None

        out_dir = self.out_root / camera_id
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{day}_{period}" + (f"_{cam_slug}" if cam_slug else "")
        out_path = out_dir / f"{stem}.mp4"
        if out_path.exists() and not force:
            return str(out_path)
        ctx = dict(qa_ctx or {})
        ctx.setdefault("camera_id", camera_id)
        ctx.setdefault("profile_name", period)
        if images_override is None:
            # Capture stats live next to the frames; with the frames
            # possibly spread over several window dirs, point the QA
            # sidecar at the directory the first image came from.
            ctx.setdefault("frames_dir", images[0].parent)
        return self._write_video(images, out_path, target_duration_s, target_fps, qa_ctx=ctx)
