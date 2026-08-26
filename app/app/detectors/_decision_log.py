"""Per-frame "what was kept, what was dropped and why" diagnostics.

NOT dead code, despite having a single caller. These four functions are
reachable only through ``detect_frame(cam_id=…)``, and no caller sets
``cam_id`` yet — the live path goes through ``detect_frame_raw``. Wiring
``cam_id`` down from the camera runtime is a separate package (DIAG-1);
these drop reasons are exactly the signal it needs, so they stay.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def fmt_dets(dets, max_n: int = 8) -> str:
    if not dets:
        return "—"
    head = dets[:max_n]
    return ", ".join(f"{d.label} {int(round(d.score * 100))}%" for d in head) + (
        f" (+{len(dets) - max_n} weitere)" if len(dets) > max_n else ""
    )


def humanize_drop_reason(reason: str) -> str:
    """Translate the raw drop-reason emitted by _apply_label_filters
    into a German sentence the operator can read at a glance. Three
    shapes are produced upstream:

        label_threshold(person)=0.72 (got 0.67)
        size_floor (h_frac=0.12 < 0.18)
        size_floor (area_frac=0.005 < 0.012)

    Unknown shapes fall back to the raw string so we never silently
    lose information."""
    m = re.match(r"label_threshold\([^)]+\)=([\d.]+)\s*\(got\s+([\d.]+)\)", reason)
    if m:
        thr = float(m.group(1)) * 100
        got = float(m.group(2)) * 100
        return f"Schwellwert {thr:.0f}% nicht erreicht (war {got:.0f}%)"
    m = re.match(r"size_floor\s*\(h_frac=([\d.]+)\s*<\s*([\d.]+)\)", reason)
    if m:
        got = float(m.group(1)) * 100
        need = float(m.group(2)) * 100
        return f"zu klein im Bild: {got:.0f}% Höhe < {need:.0f}% nötig"
    m = re.match(r"size_floor\s*\(area_frac=([\d.]+)\s*<\s*([\d.]+)\)", reason)
    if m:
        got = float(m.group(1)) * 100
        need = float(m.group(2)) * 100
        return f"zu klein im Bild: {got:.1f}% Fläche < {need:.1f}% nötig"
    return reason


def fmt_drops(drops, max_n: int = 8) -> str:
    if not drops:
        return "—"
    head = drops[:max_n]
    return ", ".join(
        f"{d.label} {int(round(d.score * 100))}% ({humanize_drop_reason(reason)})"
        for d, reason in head
    ) + (f" (+{len(drops) - max_n} weitere)" if len(drops) > max_n else "")


def log_decision(cam_id: str, kept: list, drops: list) -> None:
    """Emit one INFO line per detect_frame call when there's anything
    worth seeing. Decision tree:
      - kept ≥ 1 → "[det][cam:…] ✓ erkannt: … · ✗ verworfen: …"
      - kept == 0 AND drops > 0 → "[det][cam:…] ✗ verworfen: …"
      - kept == 0 AND drops == 0 → silent (empty scene, no signal)
    ASCII check/cross markers stand out in `docker logs` greps.
    The previously-emitted "inference empty (raw=0)" DEBUG line is
    deliberately dropped: the inference loop runs at ~3 Hz per
    camera and ~99 % of frames on a quiet scene return 0 raw
    candidates, so the line was a per-frame heartbeat with zero
    diagnostic value. The real heartbeat in server.py already
    confirms each runtime is alive; if a camera silently stops
    producing frames, the [cam:…] connection logs surface that.
    """
    if not log.isEnabledFor(logging.INFO):
        return
    if kept:
        if drops:
            log.info(
                "[det][cam:%s] ✓ erkannt: %s · ✗ verworfen: %s",
                cam_id,
                fmt_dets(kept),
                fmt_drops(drops),
            )
        else:
            log.info("[det][cam:%s] ✓ erkannt: %s", cam_id, fmt_dets(kept))
        return
    if drops:
        # Sort by score descending so "almost made it" labels come first.
        ordered = sorted(drops, key=lambda x: x[0].score, reverse=True)
        log.info("[det][cam:%s] ✗ verworfen: %s", cam_id, fmt_drops(ordered))
