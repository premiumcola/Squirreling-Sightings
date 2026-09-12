"""K5 · der Splitter-Filter.

Wirft die Ein- und Zwei-Bild-Fehlfunde weg, die im selben Clip neben
einer viel größeren Spur derselben Klasse stehen — der Grund dafür, dass
eine ruhig hin- und hergehende Person als drei Personen im Player
landete. Die Begründung samt Messwerten steht bei den Konstanten in
:mod:`._consts`.

WARUM NICHT ZUSAMMENNÄHEN. Der naheliegende Gedanke ist, den Splitter
an die große Spur anzuhängen. Das wäre falsch: bei einem Höhen-
verhältnis von 4,8 ist der kleine Fund nicht dieselbe Person weiter
hinten, sondern etwas anderes im Bild. Ihn anzunähen würde die echte
Spur an eine Stelle ziehen, an der die Person nie war — die Box im
Player spränge quer durchs Bild. Wegwerfen ist die ehrliche Antwort auf
„das ist kein Subjekt", Annähen die auf „das ist dasselbe Subjekt", und
hier gilt das erste.
"""

from __future__ import annotations

import logging

from ._consts import (
    SPLINTER_MAX_DETECTS,
    SPLINTER_MIN_ANCHOR_DETECTS,
    SPLINTER_SIZE_RATIO,
)
from ._samples import bb_dims, observed_samples

log = logging.getLogger(__name__)


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def track_height(track) -> float:
    """Die typische Boxhöhe einer Spur — Median über ihre Beobachtungen.

    Median und nicht Maximum: ein einzelnes ausgefranstes Rechteck am
    Bildrand soll weder eine Spur groß rechnen noch sie klein rechnen.
    """
    det = observed_samples(track)
    if not det:
        return 0.0
    return _median(bb_dims(s["bbox"])[1] for s in det)


def anchor_height_by_label(tracks) -> dict:
    """Je Klasse die Höhe der größten ETABLIERTEN Spur dieses Clips.

    Etabliert heißt: mehr als ein Aufblitzen. Ohne diese Bedingung
    könnten zwei Splitter einander als Maßstab dienen und der Filter
    fräße sich an seinem eigenen Rauschen fest.
    """
    out: dict = {}
    for tr in tracks:
        if len(observed_samples(tr)) < SPLINTER_MIN_ANCHOR_DETECTS:
            continue
        label = tr.label or "unknown"
        height = track_height(tr)
        if height > out.get(label, 0.0):
            out[label] = height
    return out


def is_splinter(track, anchor_h: float) -> tuple[bool, str]:
    """``(drop, reason)`` — ist diese Spur ein Splitter der Ankerspur?"""
    det = observed_samples(track)
    if not det or len(det) > SPLINTER_MAX_DETECTS:
        return False, ""
    height = track_height(track)
    if height <= 0 or anchor_h <= 0:
        return False, ""
    if anchor_h < SPLINTER_SIZE_RATIO * height:
        return False, ""
    return True, (
        f"splinter · n={len(det)}≤{SPLINTER_MAX_DETECTS}, "
        f"h={height:.0f}px vs anchor={anchor_h:.0f}px "
        f"(×{anchor_h / height:.1f} ≥ ×{SPLINTER_SIZE_RATIO})"
    )


def prune_splinter_tracks(state, *, camera_id: str) -> int:
    """Splitter aus ``state.closed`` entfernen; Anzahl zurückgeben.

    Idempotent: nach dem ersten Lauf gibt es nichts mehr, was die
    Bedingung erfüllt, und der Anker ändert sich dabei nie (er ist
    selbst nie ein Splitter).
    """
    if not state.closed:
        return 0
    anchors = anchor_height_by_label(state.closed)
    if not anchors:
        return 0
    survivors = []
    dropped = 0
    for tr in state.closed:
        drop, reason = is_splinter(tr, anchors.get(tr.label or "unknown", 0.0))
        if not drop:
            survivors.append(tr)
            continue
        log.info(
            "[tracking] cam=%s SPLINTER dropped: tid=%s label=%s · %s",
            camera_id,
            tr.track_id,
            tr.label,
            reason,
        )
        dropped += 1
    if dropped:
        state.closed = survivors
    return dropped
