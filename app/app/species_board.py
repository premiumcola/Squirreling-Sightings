"""Das Sichtungs-Raster aus dem Archiv ableiten statt es zu merken.

WARUM. Die Kacheln im Sichtungs-Tab waren eine Sperrklinke: `species_
unlock.unlock_species` trug eine Art ein und NICHTS nahm je etwas zurück.
Kein einziger Weg, auf dem eine Art nachträglich ihren Namen ändert, hat
die Datei je angefasst — nicht die Korrektur von Hand
(`routes/events.py`), nicht die Neuentscheidung nach der Feinanalyse
(`bird_species_backfill.resettle_headline_species`), nicht das Löschen
eines Clips. Einmal freigeschaltet hieß freigeschaltet, auch wenn der
Clip, der es ausgelöst hat, längst als etwas anderes im Archiv steht:
„Aktuell sind jetzt dann durch die Fehlerkennungen von Videos eben Dinge
freigeschalten, die faktisch nicht freigeschalten sind."

Deshalb ist die Zahl auf der Kachel ab hier keine gespeicherte Zahl mehr,
sondern eine Frage ans Archiv — dieselbe Kehrtwende, die die Artfilter in
der Mediathek schon hinter sich haben (`media_index/_visible.py::
camera_stats` zählt `species_counts` aus genau den Ereignissen, die das
Raster auch anzeigt; siehe den Kopf von `mediathek/_species-filter.js`
für den Fehler, den das dort behoben hat). Wer zählt, was er anzeigt,
kann nicht auseinanderlaufen.

WAS DIESES MODUL IST UND WAS NICHT. Hier steht der Lauf über das Archiv.
Das Schreiben gehört `species_unlock.py`, das die Datei und ihr Schloss
besitzt — dieses Modul stellt die Frage, jenes gibt die Antwort zu
Protokoll.

WANN ES LÄUFT. Beim Start, jede Nacht, und nach jeder Änderung am Archiv,
die eine Art betreffen kann (Umbenennung, Artkorrektur, Löschung). Ein
Lauf ist ein Dateidurchlauf ohne Video-Dekodierung, dieselbe
Größenordnung wie der Steckbrief-Abgleich daneben.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .species_unlock import apply_species_tally

log = logging.getLogger("app.sichtungen")


def species_rows(events_dir) -> dict[str, list[dict]]:
    """Jede Art im Archiv mit ALLEN ihren Clips.

    ``{Artname: [{"event_id": …, "camera_id": …, "time": iso}, …]}``,
    je Art nach Zeit sortiert, neueste zuerst.

    EIN Durchlauf, zwei Fragen. Das Sichtungs-Raster will wissen, WIE
    OFT und SEIT WANN (`tally_species`); die Aufbewahrung will wissen,
    WELCHE Aufnahmen die letzten Belege einer Art sind
    (`proof_event_ids`). Beide aus derselben Liste zu beantworten ist
    nicht nur billiger, es ist die Bedingung dafür, dass sie sich nicht
    widersprechen können: eine Art, deren Abzeichen das Raster vergibt,
    hat dann garantiert auch die Clips, die es begründen.

    Gelesen wird `bird_species` — dasselbe Feld, aus dem JEDER Weg zur
    Freischaltung liest (der Live-Weg über `_publish_achievement`, der
    Nachlauf über `bird_species_backfill`), und das trotz seines Namens
    auch die Säugetiere trägt. Das ist die Bedingung dafür, dass ein
    Abzeichen hier auch wieder ENTZOGEN werden darf: der Lauf sieht
    genau die Menge, aus der die Abzeichen entstanden sind, also ist
    „steht nicht mehr drin" hier eine belastbare Aussage und kein
    blinder Fleck.

    Der Papierkorb liegt unter ``storage/.trash/`` und damit außerhalb
    dieses Verzeichnisses — ein weggeworfener Clip zählt also nicht mehr
    mit, was genau richtig ist.
    """
    rows: dict[str, list[dict]] = {}
    if events_dir is None or not Path(events_dir).exists():
        return rows
    for cam_dir in (d for d in Path(events_dir).iterdir() if d.is_dir()):
        for jf in cam_dir.rglob("*.json"):
            if jf.name.endswith(".tracks.json"):
                continue
            try:
                event = json.loads(jf.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            species = (event.get("bird_species") or "").strip()
            if not species:
                continue
            rows.setdefault(species, []).append(
                {
                    "event_id": str(event.get("event_id") or jf.stem),
                    "camera_id": str(event.get("camera_id") or cam_dir.name),
                    "time": str(event.get("time") or ""),
                }
            )
    # ISO-Zeitstempel sind als Zeichenketten in derselben Reihenfolge wie
    # als Zeitpunkte. Ein Ereignis ohne Zeit sortiert nach hinten — es ist
    # der schlechtere Beleg, nicht der neuere.
    for lst in rows.values():
        lst.sort(key=lambda r: r["time"] or "", reverse=True)
    return rows


def tally_species(events_dir) -> dict[str, dict]:
    """Jede Art im Archiv mit Anzahl Clips, Erstsichtung und Kamera.

    ``{Artname: {"count": n, "date": iso, "camera_id": cam}}`` — die
    Sicht, die das Sichtungs-Raster braucht, abgeleitet aus
    :func:`species_rows`.
    """
    tally: dict[str, dict] = {}
    for species, lst in species_rows(events_dir).items():
        # Das Abzeichen sagt „seit wann" — also zählt der ÄLTESTE Beleg,
        # und der steht bei absteigender Sortierung am Ende.
        first = lst[-1]
        tally[species] = {
            "count": len(lst),
            "date": first["time"],
            "camera_id": first["camera_id"],
        }
    return tally


def resync_species_board(store, storage_root) -> dict:
    """Einmal über das Archiv laufen und das Raster darauf einnorden.

    Gibt `{"unlocked": n, "revoked": n, "species": n}` zurück. Idempotent
    — ein zweiter Lauf über unverändertes Archiv schreibt dieselbe Datei
    noch einmal und ändert nichts.

    KEIN ARCHIV IST NICHT DASSELBE WIE EIN LEERES ARCHIV. Ein Lauf, der
    das Verzeichnis nicht findet, weiß nichts und darf deshalb auch nichts
    zurücknehmen — sonst räumt ein noch nicht eingehängter Datenträger
    beim Start das ganze Raster ab, und der Betreiber verliert jedes
    Abzeichen an einen Fehler, der mit Arten nichts zu tun hat. Ein
    Verzeichnis, das da ist und keine Art mehr enthält, ist dagegen eine
    echte Aussage und wird auch als eine behandelt.
    """
    events_dir = getattr(store, "events_dir", None)
    if events_dir is None or not Path(events_dir).exists():
        log.debug("[sichtungen] Kein Archivverzeichnis — Raster unverändert")
        return {"unlocked": 0, "revoked": 0, "species": 0}
    return apply_species_tally(storage_root, tally_species(events_dir))


#: Wie viele Aufnahmen je Art als Beleg erhalten bleiben.
#:
#: „Sorge dafür auch in den lösch timern dass mindestens die letzten 10
#: erkennungen der spezies als video erhalten bleiben […] kein spezies
#: unlock ohne beweisvideo!"
#:
#: Seit das Raster Abzeichen auch wieder ZURÜCKNIMMT, hat eine Frist eine
#: Nebenwirkung, die sie vorher nicht hatte: läuft die letzte Aufnahme
#: einer Art ab, verschwindet mit ihr das Abzeichen. Zehn statt einer,
#: damit ein einzelner Fehlgriff — ein falsch bestimmter Clip, eine
#: versehentliche Löschung — nicht gleich die ganze Art kostet.
PROOF_CLIPS_PER_SPECIES = 10


def proof_event_ids(events_dir, keep: int = PROOF_CLIPS_PER_SPECIES) -> set[str]:
    """Die Ereignis-IDs, die als Beleg ihrer Art nicht wegdürfen.

    Je Art die `keep` neuesten. Neueste, nicht älteste: der Steckbrief
    soll zeigen, wie das Tier HEUTE aussieht, und eine Art mit weniger
    als `keep` Aufnahmen behält damit schlicht alle.
    """
    n = max(1, int(keep or 1))
    out: set[str] = set()
    for lst in species_rows(events_dir).values():
        for row in lst[:n]:
            if row["event_id"]:
                out.add(row["event_id"])
    return out


def species_losing_last_proof(events_dir, doomed_ids) -> dict[str, int]:
    """Arten, die durch das Löschen von `doomed_ids` JEDEN Beleg verlören.

    ``{Artname: Anzahl betroffener Aufnahmen}`` — leer, wenn keine Art
    dabei komplett verschwindet.

    Das ist die Frage vor einer Sammellöschung: „lasse es nicht zu bzw
    frage nach wenn alle videos einer spezies gelöscht werden sollen,
    dann würde man die erkennung verlieren". Nicht verbieten — der
    Betreiber darf auch eine Fehlerkennung samt Abzeichen loswerden
    wollen — aber er muss wissen, dass er es gerade tut.
    """
    doomed = {str(i) for i in (doomed_ids or []) if i}
    if not doomed:
        return {}
    out: dict[str, int] = {}
    for species, lst in species_rows(events_dir).items():
        ids = {r["event_id"] for r in lst if r["event_id"]}
        if ids and ids <= doomed:
            out[species] = len(ids)
    return out
