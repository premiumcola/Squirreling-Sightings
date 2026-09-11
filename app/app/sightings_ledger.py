"""Das Sichtungsbuch — die Erkennung überlebt ihr Video.

WARUM ES DAS GIBT. Bis hierher stand eine Art an genau EINER Stelle: im
Feld `bird_species` der Ereignis-Datei unter `motion_detection/<cam>/
<datum>/<id>.json`. Der Papierkorb räumt genau diese Datei weg
(`trash.move_to_trash`), und weil die Zeitleiste, die Statistik und seit
dem Raster-Abgleich auch die Abzeichen (`species_board.py`) aus
denselben Dateien lesen, nahm das Löschen eines Clips die Sichtung
komplett mit: wann, welche Art, welche Kamera — weg. Wer hundert Clips
aufräumt, räumt seine Chronik mit ab.

    „wichtig auch wenn ich die video lösche die ereignisse wann welcher
    vogel / spezies erkannt wurde ich noch separat zum video in einer
    art erkennungs-datenbank auch für die statistik gespeichert??"

Und vorher schon: „Beim löschen der elemente bitte nicht die statistik
leeren also die events bleiben drin." Ab hier: ja. Eine Zeile je
Sichtung, unter dem Storage-Wurzelverzeichnis, angehängt sobald eine Art
auf einem Ereignis steht — und beim Löschen NICHT angefasst.

WARUM EIN EIGENES BUCH UND KEIN `kind` IN `detection_feedback`. Jenes
Buch ist die gleiche Bauart (append-only JSONL) und wäre technisch der
naheliegende Ort — aber es ist ausdrücklich BESCHRÄNKT: `_io._compact`
wirft ab 8 MB weg, was `_retention.select_retained` nicht behalten will.
Für einen Kalibrier-Korpus ist das richtig, hier wäre es der Fehler
selbst: eine Sichtung, die aus Platzgründen verfallen kann, ist keine
Aufzeichnung. Genau dieselbe Abwägung hat `species_video_count.py` schon
einmal getroffen und aus demselben Grund entschieden. Die Primitive
werden trotzdem geteilt und nicht nachgebaut — `io_utils.append_jsonl` /
`iter_jsonl` sind die Anhäng- und Lesebausteine, die dort ausgelagert
wurden für „Bücher ohne Größenkappe"; dieses ist eines.

FORM. Eine Zeile je Schreibung, gefaltet über `event_id` — die letzte
Zeile zu einer Ereignis-ID gewinnt. Das macht eine Artkorrektur zu einem
Anhängsel statt zu einer Änderung (nichts wird je überschrieben, die
ursprüngliche Entscheidung des Modells bleibt lesbar) und die
Schreibungen idempotent: derselbe Clip zweimal verbucht ergibt keine
zweite Sichtung. `species: null` ist die Rücknahme — die Art wurde vom
Ereignis entfernt, nicht der Clip gelöscht. Der Unterschied ist der
ganze Punkt dieses Moduls.

WAS ES NICHT TUT. Es zieht nie etwas zurück, weil eine Datei fehlt. Der
Nachlauf unten sieht nur, was im Archiv STEHT; ein gelöschter Clip ist
dort nicht mehr zu sehen, und genau deshalb darf Abwesenheit hier nichts
bedeuten. Nur ein ausdrücklicher Widerruf (Artkorrektur, Label-Änderung)
schreibt eine Rücknahme.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .io_utils import append_jsonl, iter_jsonl
from .species_unlock import _day

log = logging.getLogger("app.sichtungen")

#: Direkt unter dem Storage-Wurzelverzeichnis, neben
#: `species_video_counts.json` und `achievements.json` — nicht unter
#: `_diag/`. Dort liegen Diagnose-Artefakte, die verfallen dürfen; dies
#: ist Nutzdatenbestand.
LEDGER_FILE = "sightings.jsonl"

KIND_SIGHTING = "sighting"


def ledger_path(storage_root) -> Path:
    return Path(storage_root or "storage") / LEDGER_FILE


# ── Lesen ────────────────────────────────────────────────────────────────

# Die Faltung, solange die Datei unverändert ist.
#
# Jede Schreibung fragt zuerst „steht das schon so drin?", und das ist
# eine Frage an die ganze Datei. Auf dem Aufnahme-Thread, je Ereignis,
# wäre das ein vollständiger Parse — dieselbe Rechnung, die
# `detection_feedback._io.ledger_index` schon einmal aufgemacht hat, und
# dieselbe Antwort: Fingerabdruck aus (Größe, mtime_ns). Ein Anhängen
# ändert beides, eine veraltete Faltung kann eine Schreibung also nicht
# überleben. Das Ergebnis ist per Vertrag NUR-LESEND — wer es verändert,
# verändert es für jeden anderen Leser mit.
_cache_lock = threading.Lock()
_cache_key: tuple | None = None
_cache_value: dict | None = None


def _fingerprint(path: Path) -> tuple:
    try:
        st = path.stat()
        return (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(path), -1, -1)


def folded(storage_root) -> dict[str, dict]:
    """Der letzte Stand je Ereignis-ID, Rücknahmen eingeschlossen.

    ``{event_id: Zeile}`` in Dateireihenfolge gefaltet. Enthält auch
    Zeilen mit ``species: null`` — die Schreibseite muss eine Rücknahme
    von „noch nie verbucht" unterscheiden können, sonst hängt sie
    dieselbe Rücknahme bei jedem Lauf erneut an.
    """
    global _cache_key, _cache_value
    path = ledger_path(storage_root)
    key = _fingerprint(path)
    with _cache_lock:
        if _cache_key == key and _cache_value is not None:
            return _cache_value
    out: dict[str, dict] = {}
    for rec in iter_jsonl(path):
        if rec.get("kind") != KIND_SIGHTING:
            continue
        eid = rec.get("event_id")
        if isinstance(eid, str) and eid:
            out[eid] = rec
    with _cache_lock:
        _cache_key, _cache_value = key, out
    return out


def sightings(storage_root, *, since=None, until=None, species=None) -> list[dict]:
    """Die gültigen Sichtungen, neueste zuerst.

    `since` / `until` sind Kalendertage (``YYYY-MM-DD``; ein voller
    ISO-Zeitstempel wird auf den Tag gekürzt) und beide einschließlich.
    Verglichen wird auf Zeichenketten — ISO-Zeitstempel stehen als
    Zeichenketten in derselben Reihenfolge wie als Zeitpunkte, dieselbe
    Annahme, auf der `species_board.species_rows` schon sortiert.

    Eine Sichtung ohne lesbares Datum fällt aus JEDER eingegrenzten
    Abfrage heraus — sie kann weder drinnen noch draußen belegt werden,
    und sie stillschweigend mitzuzählen hieße, eine Monatsstatistik mit
    Zeilen zu füllen, die zu keinem Monat gehören.
    """
    lo, hi = _day(str(since or "")), _day(str(until or ""))
    want = (species or "").strip().casefold() or None
    out: list[dict] = []
    for row in folded(storage_root).values():
        name = (row.get("species") or "").strip()
        if not name:
            continue
        if want and name.casefold() != want:
            continue
        day = _day(str(row.get("time") or ""))
        if (lo or hi) and not day:
            continue
        if (lo and day < lo) or (hi and day > hi):
            continue
        out.append(row)
    out.sort(key=lambda r: (str(r.get("time") or ""), str(r.get("event_id") or "")), reverse=True)
    return out


def species_totals(storage_root, *, since=None, until=None, species=None) -> dict[str, dict]:
    """Sichtungen je Art über einen Zeitraum.

    ``{Artname: {"count", "days", "first", "last", "cameras",
    "species_latin"}}``. `days` ist die Zahl VERSCHIEDENER Kalendertage —
    dieselbe ehrlichere Antwort auf „wie oft", die auch das Sichtungs-
    Raster gibt, wenn zwölf Aufnahmen aus einem Vormittag stammen.

    Dies ist die Frage, für die das Buch existiert: sie wird aus den
    Zeilen beantwortet und nicht aus den Clips, also ändert das Löschen
    eines Videos sie nicht.
    """
    acc: dict[str, dict] = {}
    for row in sightings(storage_root, since=since, until=until, species=species):
        name = str(row.get("species") or "").strip()
        when = str(row.get("time") or "")
        entry = acc.setdefault(
            name,
            {
                "count": 0,
                "_days": set(),
                "_cams": set(),
                "first": "",
                "last": "",
                "species_latin": None,
            },
        )
        entry["count"] += 1
        day = _day(when)
        if day:
            entry["_days"].add(day)
        cam = str(row.get("cam_id") or "")
        if cam:
            entry["_cams"].add(cam)
        if when and (not entry["first"] or when < entry["first"]):
            entry["first"] = when
        if when > entry["last"]:
            entry["last"] = when
        if not entry["species_latin"] and row.get("species_latin"):
            entry["species_latin"] = row["species_latin"]
    out: dict[str, dict] = {}
    for name, entry in acc.items():
        out[name] = {
            "count": entry["count"],
            "days": len(entry["_days"]),
            "first": entry["first"],
            "last": entry["last"],
            "cameras": sorted(entry["_cams"]),
            "species_latin": entry["species_latin"],
        }
    return out


def daily_counts(storage_root, *, since=None, until=None, species=None) -> dict[str, int]:
    """Sichtungen je Kalendertag, ``{"YYYY-MM-DD": n}``, aufsteigend.

    Nur Tage MIT Sichtungen; die Lücken dazwischen gehören der
    Darstellung, nicht dem Buch — welche Null ein leerer Tag und welche
    eine fehlende Kamera ist, kann diese Ebene nicht entscheiden.
    """
    out: dict[str, int] = {}
    for row in sightings(storage_root, since=since, until=until, species=species):
        day = _day(str(row.get("time") or ""))
        if day:
            out[day] = out.get(day, 0) + 1
    return dict(sorted(out.items()))


# ── Schreiben ────────────────────────────────────────────────────────────


def _score(value) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _species_meta(event: dict, species: str) -> tuple:
    """``(score, species_latin)`` zu einer Art aus dem Ereignis, wenn da.

    Zuerst die Clip-Bilanz (`whole_clip.species`, die über den GANZEN
    Clip akkumulierte Antwort), dann die Auslöse-Detektionen. Diese
    Reihenfolge ist dieselbe, in der `bird_species` selbst entschieden
    wird (`_motion._refresh_bird_species`) — die Zahl im Buch soll zu der
    Art gehören, die im Buch steht, und nicht zu einem Einzelbild, das
    gerade zufällig auch etwas gesehen hat.
    """
    want = species.strip().casefold()
    for row in (event.get("whole_clip") or {}).get("species") or []:
        if str(row.get("species") or "").strip().casefold() == want:
            return _score(row.get("best_score")), (row.get("species_latin") or None)
    for det in event.get("detections") or []:
        if str(det.get("species") or "").strip().casefold() == want:
            return _score(det.get("species_score")), (det.get("species_latin") or None)
    return None, None


def sighting_row(event, known, *, cam_id=None, source: str = "live") -> dict | None:
    """PUR: die Zeile, die dieses Ereignis verdient — oder ``None``.

    `known` ist der letzte Stand dieser Ereignis-ID aus dem Buch (oder
    ``None``). Getrennt von `record_sighting`, weil die Entscheidung EINEN
    gefalteten Stand braucht und nicht einen pro Zeile: der Nachtrag über
    das Archiv rief `record_sighting` je Clip auf, und das las jedes Mal
    das ganze Buch neu — dessen Fingerabdruck sich durch den eigenen
    Anhang gerade geändert hatte, der Zwischenspeicher also nie griff.
    Quadratisch, bei jedem Start, über ein Archiv, das nur wächst.
    """
    if not isinstance(event, dict):
        return None
    event_id = str(event.get("event_id") or "").strip()
    if not event_id:
        return None
    species = str(event.get("bird_species") or "").strip() or None
    if known is not None:
        if (str(known.get("species") or "").strip() or None) == species:
            return None
    elif species is None:
        # Nie verbucht und keine Art: es gibt nichts zurückzunehmen.
        return None
    score, latin = _species_meta(event, species) if species else (None, None)
    return {
        "kind": KIND_SIGHTING,
        "event_id": event_id,
        "cam_id": str(cam_id or event.get("camera_id") or ""),
        "species": species,
        "species_latin": latin,
        "time": str(event.get("time") or ""),
        "score": score,
        "source": source,
    }


def record_sighting(storage_root, event, *, cam_id=None, source: str = "live") -> bool:
    """Den Artstand eines Ereignisses ins Buch schreiben, falls neu.

    `event` ist eine Ereignis-Datei in ihrer Plattenform — gelesen werden
    `event_id`, `camera_id`, `time` und `bird_species` (das trotz seines
    Namens auch die Säugetiere trägt, siehe `species_board.species_rows`).
    Eine leere Art ist die RÜCKNAHME einer vorher verbuchten Sichtung und
    wird nur dann geschrieben, wenn vorher wirklich eine dastand.

    Gibt ``True`` zurück, wenn eine Zeile angehängt wurde. ``False``
    heißt „stand schon genau so drin" (der Normalfall beim zweiten Lauf)
    oder ein Schreibfehler — den loggt `append_jsonl` selbst. Für die
    Aufrufer ist beides dasselbe: es ist nichts zu tun.

    Die Prüfung „steht schon drin" und das Anhängen sind nicht EIN
    Schritt, zwei Kamera-Threads können also im Rennen dieselbe Zeile
    zweimal anhängen. Das darf sein: gezählt wird nach der Faltung über
    `event_id`, und zwei gleiche Zeilen falten zu einer. Die Idempotenz
    hängt an der Leseseite, nicht an einem Schloss — deshalb überlebt sie
    auch einen Absturz mitten im Lauf.
    """
    if storage_root is None or not isinstance(event, dict):
        return False
    event_id = str(event.get("event_id") or "").strip()
    if not event_id:
        return False
    row = sighting_row(event, folded(storage_root).get(event_id), cam_id=cam_id, source=source)
    if row is None:
        return False
    return append_jsonl(
        ledger_path(storage_root),
        row,
    )


def preserve_before_delete(storage_root, cam_id: str, event: dict) -> bool:
    """Die Erkennung verbuchen, BEVOR die Ereignis-Datei weggeht.

    Der letztmögliche Moment. Danach steht die Art nirgends mehr, wo ein
    Nachlauf sie fände: nachgetragen wird aus dem Archiv
    (:func:`backfill_from_archive`), und der Papierkorb liegt außerhalb
    davon. Ein Clip aus der Zeit vor diesem Buch, oder einer, dessen
    Live-Schreibung ausgefallen ist, verlöre seine Sichtung genau hier —
    und das ist der Fall, um den es dem Betreiber überhaupt geht:
    „wichtig auch wenn ich die video lösche […] noch separat zum video
    […] gespeichert".

    Schluckt jeden Fehler. Eine Löschung, die am Buchhalten scheitert,
    wäre die schlechtere Antwort auf dieselbe Sorge.
    """
    try:
        return record_sighting(storage_root, event, cam_id=cam_id, source="pre_delete")
    except Exception as e:
        log.warning("[sichtungen] Sichtung vor dem Löschen nicht verbucht: %s", e)
        return False


def backfill_from_archive(store, storage_root) -> dict:
    """Das Buch aus dem Archiv nachziehen, wie es heute dasteht.

    Damit die Chronik nicht erst ab dem Tag beginnt, an dem dieses Modul
    eingebaut wurde: jeder Clip, der JETZT eine Art trägt, bekommt seine
    Zeile. Gibt ``{"examined", "added"}`` zurück.

    Läuft über `species_board.species_rows` und nicht über einen eigenen
    Archivlauf — das ist genau derselbe Durchlauf über dieselben Dateien
    und dasselbe Feld, aus dem auch das Sichtungs-Raster entsteht. Zwei
    Läufe wären zwei Gelegenheiten auseinanderzulaufen.

    Idempotent: verbucht wird nur, was noch nicht oder anders im Buch
    steht, also fügt der zweite Lauf über ein unverändertes Archiv nichts
    hinzu — und eine Zeile, die aus dem Live-Pfad schon einen Messwert
    trägt, wird von der ärmeren Archivzeile nicht ersetzt.

    KEIN ARCHIV IST NICHT DASSELBE WIE EIN LEERES ARCHIV: ein Lauf, der
    das Verzeichnis nicht findet, weiß nichts. Er nimmt hier ohnehin
    nichts zurück — dieses Buch kennt keine Rücknahme aus Abwesenheit —
    aber er hätte auch nichts anzuhängen.
    """
    from .species_board import species_rows

    events_dir = getattr(store, "events_dir", None)
    if events_dir is None or not Path(events_dir).exists():
        log.debug("[sichtungen] Kein Archivverzeichnis — Sichtungsbuch unverändert")
        return {"examined": 0, "added": 0}
    examined = added = 0
    # EIN gefalteter Stand für den ganzen Lauf. Jede eigene Zeile wird
    # direkt hineingeschrieben, damit auch zwei Schreibweisen derselben
    # Art im selben Lauf nicht doppelt verbuchen — und damit das Buch
    # NICHT je Clip neu gelesen wird, was diesen Lauf quadratisch machte.
    known = dict(folded(storage_root))
    path = ledger_path(storage_root)
    for species, rows in species_rows(events_dir).items():
        for row in rows:
            examined += 1
            line = sighting_row(
                {
                    "event_id": row["event_id"],
                    "camera_id": row["camera_id"],
                    "time": row["time"],
                    "bird_species": species,
                },
                known.get(row["event_id"]),
                source="backfill",
            )
            if line is None:
                continue
            if append_jsonl(path, line):
                known[line["event_id"]] = line
                added += 1
    if added:
        log.info(
            "[sichtungen] Sichtungsbuch nachgetragen: %d von %d Clips neu verbucht",
            added,
            examined,
        )
    return {"examined": examined, "added": added}
