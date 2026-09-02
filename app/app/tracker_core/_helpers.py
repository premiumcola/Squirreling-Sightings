"""Pure helpers shared across the tracker: id + colour minting, the
score→tier mapping, and the cadence-aware miss-grace conversion.

No state, no I/O — every function here is a total function of its
arguments, which is what lets both the live and the post-clip caller
reach them without carrying any tracker context.
"""

from __future__ import annotations

import uuid

from ._consts import TRACK_MISS_WINDOWS


# ── ID + colour helpers ─────────────────────────────────────────────────────
def short_id() -> str:
    """6-hex-char id for a track. Stable across the clip but not globally
    unique — the (event_id, track_id) pair is what callers index on."""
    return uuid.uuid4().hex[:6]


def color_for_track(track_id: str) -> str:
    """Deterministic 6-char hex colour from the track id. The lightbox
    overlay uses this to keep each subject visually distinct without a
    server-side palette table. Picks from a hue-spread set of saturated
    colours so two adjacent tracks never collide."""
    palette = [
        "#22c55e",
        "#3b82f6",
        "#f59e0b",
        "#ef4444",
        "#a855f7",
        "#14b8a6",
        "#ec4899",
        "#84cc16",
        "#f97316",
        "#06b6d4",
        "#eab308",
        "#8b5cf6",
        "#10b981",
        "#f43f5e",
        "#0ea5e9",
    ]
    h = sum(ord(c) for c in track_id) % len(palette)
    return palette[h]


def classify_tier(score: float, spawn_score: float) -> str:
    """Map a detection score to ``"confirmed"`` (≥ spawn) or
    ``"tentative"`` (< spawn). Below-floor detections are expected to
    be filtered out by the caller BEFORE this function — we don't gate
    on the floor here because the live and post-clip floors are
    consumed at different points (post-clip: detect_frame_raw
    threshold; live: same)."""
    return "confirmed" if float(score) >= float(spawn_score) else "tentative"


def compute_miss_grace_samples(seconds: float, fps: float) -> int:
    """Translate a wall-clock grace period into a sample-count grace
    that ``associate_detections`` consumes. Same intent at every
    cadence — 4 s × 1 Hz = 4 samples, 4 s × 3 Hz = 12 samples. Returns
    ``TRACK_MISS_WINDOWS`` as a safe default when the inputs aren't
    usable (zero or negative)."""
    try:
        secs = float(seconds)
        rate = float(fps)
    except (TypeError, ValueError):
        return TRACK_MISS_WINDOWS
    if secs <= 0 or rate <= 0:
        return TRACK_MISS_WINDOWS
    return max(1, int(round(secs * rate)))
