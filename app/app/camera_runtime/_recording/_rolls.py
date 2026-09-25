"""Der Nachlauf eines Clips — eingestellt und tatsächlich.

„Vorlauf und Nachlauf ist auch nicht schön markiert in der Timeline."

WAS FALSCH WAR. Das Ereignis notierte als Nachlauf
``int(cam_cfg.get("post_motion_tail_s") or 0)`` — den EIGENEN Wert der
Kamera. Eine Kamera ohne eigenen Wert erbt aber die globale Voreinstellung
von 3 s, und genau mit der hat die Aufnahme auch gestoppt. Auf der Nut Bar
stand deshalb bei jedem Clip „Nachlauf 0", und der Zeitstrahl zeichnete
nie ein Nachlauf-Band (gemessen am 2026-09-25, fünf von fünf Clips).

Dieselbe Auflösung stand an drei Stellen von Hand hingeschrieben
(Aufnahmeschritt, Provenienz, Ereignis-Stub) und war an einer davon falsch.
Jetzt steht sie einmal, hier.

Und der Wert, der am Ende im Ereignis steht, ist nicht mehr die Absicht,
sondern die MESSUNG: die Sekunden zwischen letzter Bewegung und Stopp
(`record_post_roll`). Seit der Mindest-Aufnahmedauer (`MIN_LIVE_SEGMENT_S`)
kann das mehr sein als eingestellt — ein Clip mit einem Wimpernschlag
Bewegung läuft sechs Sekunden, und der Zeitstrahl soll zeigen, was im Clip
IST.
"""

from __future__ import annotations


def resolve_post_motion_seconds(cam_cfg: dict, global_cfg: dict) -> float:
    """0 oder leer an der Kamera heißt „globalen Wert erben" — dieselbe
    Regel wie `_preroll.resolve_pre_motion_seconds`."""
    proc = (global_cfg or {}).get("processing") or {}
    return float((cam_cfg or {}).get("post_motion_tail_s") or proc.get("post_motion_tail_s", 3.0))


def record_post_roll(meta: dict | None, since_last_motion_s: float) -> None:
    """Die gemessene Nachlaufzeit in die Metadaten des laufenden Clips —
    VOR dem Stopp, denn der Stopp gibt genau diese Metadaten an die
    Nachbearbeitung weiter."""
    if meta is None:
        return
    try:
        meta["post_roll_s"] = round(max(0.0, float(since_last_motion_s)), 2)
    except (TypeError, ValueError):
        return
