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
from datetime import date, datetime
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

#: Genau die Abzeichen-IDs, die aus einer Artbestimmung entstehen.
#:
#: `achievements.json` trägt mehr als diese: die Quest-Blöcke (`quests`,
#: `quests_archive`) liegen in derselben Datei. Ein Abgleich, der aus dem
#: Archiv ableitet, darf deshalb NUR über dieser Menge aufräumen — alles
#: andere in der Datei gehört jemand anderem und wird nicht angefasst.
SPECIES_ACH_IDS = frozenset(_SPECIES_TO_ACH_ID.values())

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
                # Damit die Kachel sofort etwas Wahres sagt statt „1×" zu
                # raten. Die echte Zahl kommt aus dem Archiv — siehe
                # `apply_species_tally` — dies ist die untere Schranke,
                # die zwischen dieser Aufnahme und dem nächsten Abgleich
                # gilt.
                "count": 1,
            }
            atomic_write_json(path, data)
    except Exception as e:
        log.warning("[sichtungen] Freischaltung für %s fehlgeschlagen: %s", species, e)
        return False
    log.info("[sichtungen] Neue Art freigeschaltet: %s (%s)", ach_id, species)
    return True


def _day(iso: str) -> str:
    """Der Kalendertag eines ISO-Zeitstempels, oder „"."""
    return (iso or "")[:10]


def sightings_per_day(count: int, first_iso: str, last_iso: str) -> float:
    """Wie oft die Art an einem Tag zu sehen ist, ungefähr.

    Gezählt wird über die Spanne vom ersten bis zum letzten Beleg,
    einschließlich beider Tage — eine Art mit drei Aufnahmen an EINEM Tag
    hat drei je Tag, nicht drei je vier Monate. Beide Enden ohne
    lesbares Datum heißt: keine Aussage, also 0.

    Auf eine Nachkommastelle, weil dies eine Größenordnung ist und keine
    Messung: „wie oft je tag ca?!"
    """
    n = max(0, int(count or 0))
    a, b = _day(first_iso), _day(last_iso)
    if not n or not a or not b:
        return 0.0
    try:
        span = (date.fromisoformat(b) - date.fromisoformat(a)).days
    except ValueError:
        return 0.0
    return round(n / max(1, span + 1), 1)


def apply_species_tally(storage_root, tally: dict[str, dict]) -> dict:
    """Das Sichtungs-Raster auf den Stand des Archivs bringen.

    `tally` ist das Ergebnis EINES Laufs über das Archiv:
    ``{Artname: {"count": n, "date": iso, "camera_id": cam}}`` — also
    genau die Arten, die dort JETZT noch stehen, mit ihrer Anzahl Clips.

    Was hier passiert, und warum es beides braucht:

    eintragen    eine Art im Archiv bekommt ihr Abzeichen und ihre echte
                 Zahl. Das Erstsichtungsdatum eines schon vergebenen
                 Abzeichens bleibt stehen — „seit wann" ist die Aussage
                 der Kachel, und dieselbe Art am Dienstag wiederzufinden
                 darf den Sonntag nicht überschreiben.
    entziehen    eine Art, die im Archiv NICHT mehr vorkommt, verliert
                 ihr Abzeichen wieder.

    Der zweite Teil ist der Punkt. Bis hierher war die Datei ein
    Sperrklinken-Zähler: `unlock_species` trug ein und nahm nie etwas
    zurück, und keine der Stellen, die eine Art nachträglich ÄNDERN — die
    Korrektur von Hand (`routes/events.py`), die Neuentscheidung nach der
    Feinanalyse (`bird_species_backfill.resettle_headline_species`), das
    Löschen eines Clips — hat die Datei je angefasst. Eine Fehlerkennung,
    die einmal durchkam, blieb damit für immer freigeschaltet: „Aktuell
    sind jetzt dann durch die Fehlerkennungen von Videos eben Dinge
    freigeschalten, die faktisch nicht freigeschalten sind."

    Angefasst wird ausschließlich, was in `SPECIES_ACH_IDS` steht. Die
    Quest-Blöcke in derselben Datei bleiben unberührt, ebenso jede ID,
    die keine Artbestimmung als Quelle hat.
    """
    if storage_root is None:
        return {"unlocked": 0, "revoked": 0, "species": 0}
    path = Path(storage_root) / "achievements.json"
    unlocked: list[str] = []
    revoked: list[str] = []
    try:
        with _LOCK:
            data: dict = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    # Wie bei `unlock_species`: eine kaputte Datei bei
                    # leer neu anzufangen kostet die Quests. Lieber gar
                    # nichts schreiben.
                    log.warning("[sichtungen] achievements.json unlesbar — Abgleich übersprungen")
                    return {"unlocked": 0, "revoked": 0, "species": 0}
            if not isinstance(data, dict):
                return {"unlocked": 0, "revoked": 0, "species": 0}
            wanted = _entries_from_tally(tally)
            for ach_id, entry in wanted.items():
                old = data.get(ach_id)
                if isinstance(old, dict):
                    # „Seit wann" gehört dem ersten Fund, nicht diesem Lauf.
                    entry["date"] = old.get("date") or entry["date"]
                    entry["camera_id"] = old.get("camera_id") or entry["camera_id"]
                else:
                    unlocked.append(ach_id)
                data[ach_id] = entry
            for ach_id in SPECIES_ACH_IDS - set(wanted):
                if data.pop(ach_id, None) is not None:
                    revoked.append(ach_id)
            atomic_write_json(path, data)
    except Exception as e:
        log.warning("[sichtungen] Abgleich des Sichtungs-Rasters fehlgeschlagen: %s", e)
        return {"unlocked": 0, "revoked": 0, "species": 0}
    if unlocked or revoked:
        log.info(
            "[sichtungen] Raster abgeglichen: %d neu, %d zurückgenommen (%s)",
            len(unlocked),
            len(revoked),
            ", ".join(sorted(revoked)) or "—",
        )
    return {"unlocked": len(unlocked), "revoked": len(revoked), "species": len(wanted)}


def _entries_from_tally(tally: dict[str, dict]) -> dict[str, dict]:
    """`{Artname: …}` → `{Abzeichen-ID: Eintrag}`.

    Mehrere Schreibweisen derselben Art zeigen auf dieselbe ID (siehe
    `_SPECIES_TO_ACH_ID`: „grünfink" und „gruenfink"), also werden ihre
    Zahlen addiert statt sich gegenseitig zu überschreiben — sonst
    entscheidet die Reihenfolge des Verzeichnisdurchlaufs, wie oft ein
    Grünfink gesehen wurde.
    """
    out: dict[str, dict] = {}
    # Ereignisse aus sehr alten Beständen tragen keinen Zeitstempel. Die
    # Kachel sagt „seit wann", also braucht sie eine Antwort — heute ist
    # die einzige, die noch zu holen ist, und sie überschreibt weiter
    # unten kein bereits vergebenes Datum.
    fallback_date = datetime.now().isoformat(timespec="seconds")
    for species, row in (tally or {}).items():
        ach_id = achievement_id_for(species)
        if not ach_id:
            continue
        count = max(1, int(row.get("count") or 1))
        date = row.get("date") or fallback_date
        prev = out.get(ach_id)
        if prev is None:
            out[ach_id] = {
                "date": date,
                "camera_id": row.get("camera_id") or "",
                "species": species,
                "count": count,
                # Die drei Steckbrief-Kennzahlen, aus demselben Lauf:
                # „wie oft gesehen, wann das erste Mal, wie oft je Tag ca?!"
                # `date` beantwortet das „wann das erste Mal" schon.
                "last": row.get("last") or "",
                "days": int(row.get("days") or 0),
                "per_day": float(row.get("per_day") or 0.0),
            }
            continue
        prev["count"] += count
        prev["days"] += int(row.get("days") or 0)
        last = row.get("last") or ""
        if last > (prev.get("last") or ""):
            prev["last"] = last
        if date and (not prev["date"] or date < prev["date"]):
            prev["date"] = date
            prev["camera_id"] = row.get("camera_id") or prev["camera_id"]
    # Zwei Schreibweisen derselben Art sind EINE Art, also wird ihre Rate
    # auch über die vereinte Spanne gerechnet — nicht addiert, was zwei
    # halb so häufige Arten ergäbe statt einer ganzen.
    for entry in out.values():
        entry["per_day"] = sightings_per_day(entry["count"], entry["date"], entry["last"])
    return out
