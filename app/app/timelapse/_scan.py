"""Pass 1 of a build: validate every frame, drop duplicates, tally sizes.

Lifted out of ``_write_video`` — together with the summary logging that
reports what it dropped — to get that method back under CLAUDE.md's
80-line function ceiling. Pure bookkeeping: frames are opened read-only
and no frame data is kept beyond the single reference the near-duplicate
gate compares against.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from ._consts import log


@dataclass
class ScanResult:
    """What Pass 1 learned about a window's frames.

    ``ref_size`` is the FIRST valid frame's size, ``size_counts`` the
    tally over all of them. Keeping both is deliberate: the caller picks
    the majority from the tally, and the log line that reports an
    override has to be able to name the size it rejected.
    """

    valid_paths: list = field(default_factory=list)
    size_counts: dict = field(default_factory=dict)
    ref_size: tuple | None = None
    skipped: int = 0
    dup_count: int = 0
    dup_first: str | None = None
    dup_last: str | None = None
    magenta_drops: int = 0
    magenta_first: str | None = None
    magenta_last: str | None = None
    macroblock_drops: int = 0
    macroblock_first: str | None = None
    macroblock_last: str | None = None

    @property
    def total_input(self) -> int:
        return self.skipped + self.dup_count + len(self.valid_paths)


def _note_rejection(scan: ScanResult, reason: str, name: str) -> None:
    """Book one invalid frame, and its corruption class where we have one.

    The magenta and macroblock counters are audit figures — they surface
    in the build summary so a corruption burst shows up as a trend
    instead of drowning in per-frame DEBUG lines.
    """
    log.debug("[timelapse] skip corrupt frame %s — %s", name, reason)
    scan.skipped += 1
    if (
        reason.startswith("patterned_magenta")
        or reason.startswith("pink_artifact")
        or reason.startswith("partial_pink")
    ):
        scan.magenta_drops += 1
        if scan.magenta_first is None:
            scan.magenta_first = name
        scan.magenta_last = name
    if reason.startswith("macroblock_anomaly"):
        scan.macroblock_drops += 1
        if scan.macroblock_first is None:
            scan.macroblock_first = name
        scan.macroblock_last = name


def _note_duplicate(scan: ScanResult, name: str) -> None:
    """Book one dropped duplicate, keeping the first and last name."""
    scan.dup_count += 1
    scan.dup_last = name
    if scan.dup_first is None:
        scan.dup_first = name


def scan_frames(images: list, validate) -> ScanResult:
    """Validate + deduplicate ``images``.

    ``validate`` is ``TimelapseBuilder._is_valid_frame``, injected rather
    than imported so the build tests can wrap it and count its calls.

    Active dedup exists because pixel-identical replicated buffers (a
    stuck stream, RTSP redelivery) silently inflated source frame counts
    and produced visible "frozen-time" runs in the encoded video. Two
    gates:

      1. Fast exact match — MD5 of ``img[::8, ::8]`` catches truly
         pixel-identical replicas.
      2. Near-dup — pHash hamming <= 4 AND mean-abs-diff <= 1.5 against
         the most recently kept frame. Catches the camera resampling the
         same buffer with a fresh JPEG compress, where the bit pattern
         differs but the picture does not.

    A slowly-rotating scene — real timelapse content — clears both gates
    because its mean-abs-diff exceeds 1.5 byte-units.
    """
    from ..frame_helpers import is_near_duplicate, perceptual_hash

    scan = ScanResult()
    seen_hashes: set = set()
    kept_phashes: list[int] = []
    last_kept_frame = None

    for img_path in images:
        img = cv2.imread(str(img_path))
        ok, reason = validate(img)
        if not ok:
            _note_rejection(scan, reason, img_path.name)
            if img is not None:
                del img
            continue
        fhash = hashlib.md5(img[::8, ::8].tobytes()).hexdigest()
        _sz = (img.shape[1], img.shape[0])
        scan.size_counts[_sz] = scan.size_counts.get(_sz, 0) + 1
        if scan.ref_size is None:
            scan.ref_size = _sz
        if fhash in seen_hashes:
            _note_duplicate(scan, img_path.name)
            del img
            continue
        seen_hashes.add(fhash)
        # The last-kept reference moves forward on every kept frame, so a
        # scene where each step is under 1.5 byte-units — extremely rare
        # outdoors — keeps the first frame and drops the rest. That is
        # the right trade: better to lose a marginal-motion frame than to
        # ship a stuck-stream burst.
        this_phash = perceptual_hash(img)
        if last_kept_frame is not None and is_near_duplicate(
            kept_phashes[-1] if kept_phashes else 0,
            last_kept_frame,
            img,
        ):
            _note_duplicate(scan, img_path.name)
            del img
            continue
        kept_phashes.append(this_phash)
        last_kept_frame = img.copy()
        del img  # free original; last_kept_frame holds the reference
        scan.valid_paths.append(img_path)
    return scan


def log_scan_summary(scan: ScanResult, out_path: Path) -> None:
    """The one-line build summary plus a detail line per drop class."""
    total_input = scan.total_input
    n_valid = len(scan.valid_paths)
    # One-line build summary in the structured "[timelapse]" prefix
    # so log filters can pull all encode outcomes at a glance.
    log.info(
        "[timelapse] %s: %d frames total, %d valid, %d skipped "
        "(grey/colorbar/corrupt), %d duplicates dropped",
        out_path.name,
        total_input,
        n_valid,
        scan.skipped,
        scan.dup_count,
    )
    if scan.magenta_drops > 0:
        log.info(
            "[timelapse] %s: %d magenta-corruption frame(s) dropped, first=%s last=%s",
            out_path.name,
            scan.magenta_drops,
            scan.magenta_first or "?",
            scan.magenta_last or "?",
        )
    if scan.macroblock_drops > 0:
        log.info(
            "[timelapse] %s: %d macroblock-corruption frame(s) dropped, first=%s last=%s",
            out_path.name,
            scan.macroblock_drops,
            scan.macroblock_first or "?",
            scan.macroblock_last or "?",
        )
    if scan.skipped > 0:
        log.info(
            "[timelapse] skipped %d/%d corrupt frames for %s",
            scan.skipped,
            total_input,
            out_path.name,
        )
    if scan.dup_count > 0:
        _log_duplicate_ratio(scan, out_path, n_valid)


def _log_duplicate_ratio(scan: ScanResult, out_path: Path, n_valid: int) -> None:
    """Report the duplicate share, and warn when it dominates the window.

    An active-filter count, not a diagnostic — the duplicates were
    already dropped from ``valid_paths``, so the ratio is against the
    original valid-frame total (kept + dropped).
    """
    dup_ratio = scan.dup_count / max(1, scan.dup_count + n_valid)
    log.info(
        "[timelapse] %s: duplicates dropped: %d (%.0f%% of valid frames) · first=%s last=%s",
        out_path.name,
        scan.dup_count,
        dup_ratio * 100,
        scan.dup_first or "?",
        scan.dup_last or "?",
    )
    if dup_ratio > 0.6:
        log.warning(
            "[timelapse] %.0f%% duplicate frames in %s (%d) — "
            "stuck stream during capture window?",
            dup_ratio * 100,
            out_path.name,
            scan.dup_count,
        )
