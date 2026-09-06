"""Eine Art als gesichtet eintragen — egal, auf welchem Weg sie erkannt wurde.

WARUM DAS EIN EIGENES MODUL IST. Eine Art bekommt ihren Namen auf ZWEI
Wegen, und bis hierher trug nur einer davon etwas ein:

    live          der Vogel-Klassifikator läuft während der Aufnahme, das
                  Ereignis wird mit `bird_species` finalisiert, und
                  `_recording/_publish.py::_publish_achievement` schaltet
                  die Art frei.
    nachträglich  `bird_species_backfill` läuft über das Archiv und
                  schreibt `bird_species` auf ältere Ereignisse — und
                  kannte diesen Schritt nicht.

Gemessen an der laufenden Anlage: sechs Aufnahmen tragen
`bird_species: Kohlmeise`, der Steckbrief zeigt „5 / 6" eigene Aufnahmen,
und im Sichtungs-Raster stand die Kohlmeise gesperrt bei „2 von 27
gesichtet". Freigeschaltet waren genau die zwei Arten, die LIVE bestimmt
wurden. „Wieso werden erkannte Vogelarten trotz viel Media dazu nicht
eingetragen???" — weil der zweite Weg die Tür nicht kannte.

Die Freischaltung stand als Methode am Kamera-Laufzeitobjekt und war
damit für einen Sweep ohne Kamera unerreichbar. Hier ist sie eine
Funktion über einem Pfad, die jeder Erkennungsweg aufrufen kann.

Die Zuordnungstabelle wohnt mit ihr, nicht mehr in `camera_runtime`:
sonst importiert die Nachbestimmung die halbe Kamera-Laufzeit (und
`_timelapse.py` importierte im Kreis zurück). `camera_runtime._consts`
holt sie von hier und exportiert sie unverändert weiter.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from .io_utils import atomic_write_json

log = logging.getLogger("app.sichtungen")

# Artname → Achievement-ID (deutsche Namen → normalisierte IDs).
# Vögel: LBV Stunde der Gartenvögel 2025 Bayern — Top 20.
_SPECIES_TO_ACH_ID = {
    # Vögel (Top 20 Bayern)
    "haussperling": "haussperling",
    "amsel": "amsel",
    "kohlmeise": "kohlmeise",
    "star": "star",
    "feldsperling": "feldsperling",
    "blaumeise": "blaumeise",
    "ringeltaube": "ringeltaube",
    "mauersegler": "mauersegler",
    "elster": "elster",
    "mehlschwalbe": "mehlschwalbe",
    "buchfink": "buchfink",
    "rotkehlchen": "rotkehlchen",
    "grünfink": "gruenfink",
    "gruenfink": "gruenfink",
    "rabenkrähe": "rabenkraehe",
    "rabenkraehe": "rabenkraehe",
    "hausrotschwanz": "hausrotschwanz",
    "mönchsgrasmücke": "moenchsgrasmucke",
    "moenchsgrasmucke": "moenchsgrasmucke",
    "stieglitz": "stieglitz",
    "buntspecht": "buntspecht",
    "kleiber": "kleiber",
    "eichelhäher": "eichelhaher",
    "eichelhaher": "eichelhaher",
    # Säugetiere
    "eichhörnchen": "eichhoernchen",
    "eichhoernchen": "eichhoernchen",
    "igel": "igel",
    "feldhase": "feldhase",
    "reh": "reh",
    "fuchs": "fuchs",
}

#: Ein Schloss pro Prozess. Die Kamera-Laufzeiten hielten je EIGENES —
#: also ein Schloss pro Kamera über EINER gemeinsamen Datei. Zwei Kameras,
#: die in derselben Sekunde eine Art melden, lesen dann beide „noch nicht
#: freigeschaltet", und der zweite Schreiber überschreibt den ersten
#: Eintrag. Es ist eine Datei, also ist es ein Schloss.
_LOCK = threading.Lock()


def achievement_id_for(species: str | None) -> str | None:
    """Die Katalog-ID zu einem Anzeigenamen, oder None wenn unbekannt."""
    return _SPECIES_TO_ACH_ID.get((species or "").lower().strip())


def unlock_species(
    storage_root,
    species: str,
    *,
    camera_id: str = "",
    now: datetime | None = None,
) -> bool:
    """Eine Art als gesichtet eintragen. True NUR wenn sie neu war.

    Idempotent von Bauart: eine ID, die schon in der Datei steht, bleibt
    exakt wie sie ist — samt Zeitstempel und Kamera. Das Abzeichen sagt
    „seit wann", und dieselbe Art am Dienstag wiederzuerkennen darf den
    Sonntag nicht überschreiben, an dem sie zuerst da war.
    """
    ach_id = achievement_id_for(species)
    if not ach_id or storage_root is None:
        return False
    path = Path(storage_root) / "achievements.json"
    try:
        with _LOCK:
            data: dict = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    # Eine kaputte Datei darf die Sichtung nicht kosten —
                    # aber bei leer anzufangen kostet die Quests. Also
                    # lieber gar nicht schreiben; der Aufrufer liest das
                    # False als „nicht neu".
                    log.warning(
                        "[sichtungen] achievements.json unlesbar — %s nicht freigeschaltet",
                        species,
                    )
                    return False
            if not isinstance(data, dict) or ach_id in data:
                return False
            data[ach_id] = {
                "date": (now or datetime.now()).isoformat(timespec="seconds"),
                "camera_id": camera_id,
                "species": species,
            }
            atomic_write_json(path, data)
    except Exception as e:
        log.warning("[sichtungen] Freischaltung für %s fehlgeschlagen: %s", species, e)
        return False
    log.info("[sichtungen] Neue Art freigeschaltet: %s (%s)", ach_id, species)
    return True
