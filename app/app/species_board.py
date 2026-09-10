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


def tally_species(events_dir) -> dict[str, dict]:
    """Jede Art im Archiv mit Anzahl Clips, Erstsichtung und Kamera.

    ``{Artname: {"count": n, "date": iso, "camera_id": cam}}``.

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
    tally: dict[str, dict] = {}
    if events_dir is None or not Path(events_dir).exists():
        return tally
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
            when = str(event.get("time") or "")
            row = tally.get(species)
            if row is None:
                tally[species] = {"count": 1, "date": when, "camera_id": cam_dir.name}
                continue
            row["count"] += 1
            # Das Abzeichen sagt „seit wann" — also gewinnt der früheste
            # Fund, nicht der zuletzt gelesene. ISO-Zeitstempel sind als
            # Zeichenketten in derselben Reihenfolge wie als Zeitpunkte.
            if when and (not row["date"] or when < row["date"]):
                row["date"] = when
                row["camera_id"] = cam_dir.name
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
