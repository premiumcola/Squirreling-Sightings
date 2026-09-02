"""``bundle.md`` — the page someone reads before unpacking the rest.

Written for the person who did NOT build the archive: what this is,
when it was taken, from which build, which cameras it covers, what each
file holds, and what is deliberately not in it.
"""

from __future__ import annotations

from datetime import datetime

from ._consts import (
    ARC_CONFIG,
    ARC_EVENTS,
    ARC_LOG,
    ARC_STATUS,
    ARC_TELEMETRY,
    ARC_TUNING,
    EVENT_COUNT,
    LOG_TAIL_LINES,
    MAX_BUNDLES,
)

_INTRO = """# Debug-Bundle · Squirreling · Sightings

Momentaufnahme der Erkennung für die Weitergabe: Konfiguration, Zustand,
die letzten Ereignisse samt Provenienz und der Log-Auszug — genug, um
einen Lauf nachzustellen, ohne Zugriff auf die Box.
"""

_HANDOVER = f"""## Weitergabe

Die Datei enthält **keine** Zugangsdaten: Telegram-Token, Chat-IDs,
RTSP- und MQTT-Passwörter sind vor dem Schreiben durch `<name>_set`
(„ist gesetzt") ersetzt, eingebettete URL-Kennwörter maskiert und
private IP-Adressen (RFC 1918) durch `<lan-ip>` getauscht. Die rohe
`settings.json` ist in keiner Form enthalten.

Trotzdem gilt: vor dem Versand einmal `{ARC_CONFIG}` überfliegen — was
ein Nutzer selbst in ein Freitextfeld geschrieben hat, kann keine
Maskierung erraten.

Es werden höchstens {MAX_BUNDLES} Bundles aufbewahrt; das älteste fällt
beim nächsten Export weg. Herunterladen über die angezeigte URL.
"""


def _rows(events: int, cameras: int) -> list[tuple[str, str]]:
    return [
        (ARC_STATUS, "Zustand je Kamera plus TPU-Auslastung (~10-s-Fenster)"),
        (ARC_TELEMETRY, "Inferenzzeiten je Stufe, Gerät, Modell, Hochrechnung"),
        (ARC_CONFIG, "effektive Konfiguration (config.yaml + settings.json), geschwärzt"),
        (f"{ARC_EVENTS}/", f"die letzten {events} Ereignis-JSONs inkl. `provenance`"),
        (f"{ARC_TUNING}/", f"Feinschliff, Achsen und feste Werte je Kamera ({cameras})"),
        (ARC_LOG, f"die letzten {LOG_TAIL_LINES} Zeilen des Anwendungs-Logs"),
    ]


def render(*, now: datetime, build: dict, cameras: list[dict], events: int) -> str:
    """The bundle's own README. ``cameras`` is ``[{id, name, role}, …]``."""
    build = build or {}
    lines = [_INTRO, "## Momentaufnahme\n"]
    lines.append(f"- Erstellt: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.astimezone().tzname()})")
    lines.append(
        f"- Build: {build.get('commit', '—')} · {build.get('date', '—')}"
        f" · Commit-Zahl {build.get('count', '—')}"
    )
    lines.append(f"- Kameras: {len(cameras)}")
    for cam in cameras:
        role = cam.get("role") or "—"
        lines.append(f"  - `{cam.get('id')}` · {cam.get('name') or cam.get('id')} · {role}")
    lines.append(f"- Ereignisse im Bundle: {events} (max. {EVENT_COUNT})")
    lines.append("\n## Inhalt\n")
    lines.append("| Datei | Inhalt |")
    lines.append("| --- | --- |")
    for name, what in _rows(events, len(cameras)):
        lines.append(f"| `{name}` | {what} |")
    lines.append("")
    lines.append(_HANDOVER)
    return "\n".join(lines)
