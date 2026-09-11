"""Personen-Ausschnitte aus den Aufnahmen holen, damit sie Namen bekommen.

„kannst du fotos der personen aus allen videos extrahieren damit ich die
dann auf individuen branden kann? ... die genehmigung habe ich!"

WARUM DAS NICHT NUR EIN WUNSCH IST, SONDERN EINE REPARATUR. Es gibt schon
eine Personen-Wiedererkennung (`cat_identity.IdentityRegistry` über
`storage/person_registry.json`) und einen Endpunkt, der einen Ausschnitt
unter einem Namen registriert. Dieser Endpunkt schneidet aber aus dem
GESPEICHERTEN SCHNAPPSCHUSS mit einem Rechteck aus dem EREIGNIS — und die
beiden liegen nicht im selben Pixelraum: der Schnappschuss wird auf
Breite 1280 herunterskaliert, bei Clips ist er sogar nur das ≤640er
Vorschaubild aus der Mitte des Videos, während das Rechteck in voller
Stromauflösung notiert ist. Für Clip-Ereignisse antwortet er deshalb in
der Regel mit „Crop leer". Der Weg über den Clip ist nicht die zweite
Möglichkeit, er ist die einzige, die rechnet.

DER GRUND, WARUM ER RECHNET: die Rechtecke in `<clip>.tracks.json`
stammen aus genau diesem MP4 — der Spuren-Arbeiter dekodiert die Datei
selbst und der Detektor rechnet seine Koordinaten in den Pixelraum eben
dieses Bildes zurück. Wer denselben Frame aus demselben MP4 holt, darf
das Rechteck unverändert anwenden. Kein Skalierungsfaktor, kein Raten.

KEIN NEUNTER DEKODIERER. Dieses Projekt holt an acht Stellen Einzelbilder
aus MP4s. Hier wird nichts davon wiederholt: gesucht wird mit
`tracking_worker._video.read_frame_at` (der einzige Helfer, der nach
FRAME-INDEX springt — und das ist die Einheit, in der `sample["f"]`
steht), geschnitten mit `bird_species_backfill.crop_bbox` (der einzige,
der ein übergroßes Rechteck ablehnt statt still das falsche Stück zu
nehmen). Der ffmpeg-Weg aus dem Telegram-Bestbild scheidet aus: der
springt laut eigenem Kommentar bis zu zwei Sekunden auf das nächste
Keyframe, und in zwei Sekunden hat die Person das Rechteck verlassen.

EIGENES VERZEICHNIS, NICHT NEBEN DEN CLIP. Mehrere Leser dieses Projekts
nehmen „das erste *.jpg im Ereignisordner" als Vorschau. Genau daran hat
sich heute schon der Filmstreifen verschluckt und Geisterkarten erzeugt.
Ausschnitte liegen deshalb unter `<Tag>/crops/`, und `storage_scan.
is_derived_media` weiß davon.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .bird_species_backfill import crop_bbox

log = logging.getLogger(__name__)

#: Das Klassenlabel, um das es geht — eines aus `labels.OBJECT_LABELS`.
PERSON_LABEL = "person"

#: Unterverzeichnis der Ausschnitte, neben dem Tag des Clips.
CROP_DIR = "crops"

#: Unterhalb dieser Kantenlänge ist ein Ausschnitt als Portrait wertlos —
#: und für die dHash-Wiedererkennung, die auf 9×8 herunterrechnet, erst
#: recht. Eine Person, die 30 px hoch durchs Bild läuft, taugt nicht zum
#: Benennen; sie würde die Galerie nur zumüllen.
MIN_CROP_H = 64
MIN_CROP_W = 32

#: JPEG-Qualität. Etwas höher als das Vorschaubild (75), weil dieser
#: Ausschnitt angesehen UND als Erkennungsprobe registriert wird.
CROP_QUALITY = 88


def crop_relpath_for(video_relpath: str, track_id) -> str:
    """``motion_detection/<cam>/<Tag>/crops/<event>-<track>.jpg``.

    Aus dem Video-Relpfad abgeleitet und nicht aus der Ereignis-ID, damit
    der Ausschnitt garantiert im selben Tagesordner landet wie der Clip,
    aus dem er stammt — auch bei Altbeständen, deren ID den Tag nicht
    verrät.
    """
    p = Path(str(video_relpath or ""))
    stem = p.stem
    return str(p.parent / CROP_DIR / f"{stem}-{track_id}.jpg")


def person_tracks(sidecar: dict) -> list[dict]:
    """Die Spuren, die eine Person zeigen.

    Gelesen wird das Spur-Label, nicht das der einzelnen Stichprobe: das
    Label einer Stichprobe kann mitten in der Spur kippen (der Tracker
    stimmt über fünf Frames ab), das Spur-Label ist die abgeschlossene
    Aussage.
    """
    tracks = (sidecar or {}).get("tracks")
    if not isinstance(tracks, list):
        return []
    return [t for t in tracks if isinstance(t, dict) and t.get("label") == PERSON_LABEL]


def observed_samples(track: dict) -> list[dict]:
    """Nur die Stichproben, die wirklich GESEHEN wurden.

    `source` unterscheidet drei Herkünfte: `detect` ist eine Messung,
    `track` ist zwischen zwei Messungen interpoliert und `predicted` ist
    die Gnadenfrist, in der der Tracker die Spur weiterschreibt, obwohl
    er nichts mehr findet. In einem vorhergesagten Rechteck steht mit
    einiger Wahrscheinlichkeit niemand mehr — als Portrait ist es
    wertlos, und als Erkennungsprobe ist es schädlich.
    """
    out = []
    for s in track.get("samples") or []:
        if not isinstance(s, dict) or s.get("source") != "detect":
            continue
        bbox = s.get("bbox")
        if isinstance(bbox, dict) and s.get("f") is not None:
            out.append(s)
    return out


def best_sample(track: dict) -> dict | None:
    """Die Stichprobe, aus der der Ausschnitt entsteht.

    Zuerst die, auf die die Spur selbst zeigt (`best_frame` — ihre eigene
    beste Messung, vom Tracker über Zusammenführungen hinweg gepflegt).
    Ist ausgerechnet die keine Messung, gewinnt die höchstbewertete
    beobachtete Stichprobe. Eine neue „bestes Bild"-Regel zu erfinden
    wäre die zweite in diesem Projekt; diese steht schon da.
    """
    obs = observed_samples(track)
    if not obs:
        return None
    want = track.get("best_frame")
    if want is not None:
        for s in obs:
            if s.get("f") == want:
                return s
    return max(obs, key=lambda s: float(s.get("score") or 0.0))


def _big_enough(crop) -> bool:
    if crop is None or getattr(crop, "size", 0) == 0:
        return False
    h, w = crop.shape[:2]
    return h >= MIN_CROP_H and w >= MIN_CROP_W


def read_sidecar(path: Path) -> dict:
    """Die Spurendatei eines Clips, oder ``{}``."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def extract_person_crops(storage_root, event: dict, *, tracks_path=None) -> list[dict]:
    """Je Personen-Spur einen Ausschnitt schreiben. Gibt die Treffer zurück.

    ``[{"track_id": …, "relpath": …, "score": …, "t": …}]`` — leer, wenn
    der Clip keine Person zeigt, keine Spurendatei hat oder sich nicht
    öffnen lässt. Nichts davon ist ein Fehler, den jemand sehen müsste:
    ein Clip ohne Personenspur ist der Normalfall.

    EINE ÖFFNUNG, MEHRERE SPRÜNGE. Das Video wird einmal geöffnet und
    dann je Spur an ihren besten Frame gesprungen. Ein Clip mit zwei
    Personen liefert damit zwei Portraits statt eines Kompromisses.
    """
    import cv2

    from .tracking_worker._job import tracks_path_for
    from .tracking_worker._video import open_video, read_frame_at

    rel = str(event.get("video_relpath") or "")
    if not rel:
        return []
    root = Path(storage_root)
    video = root / rel
    if not video.exists():
        return []
    sidecar = read_sidecar(tracks_path or tracks_path_for(video))
    tracks = person_tracks(sidecar)
    if not tracks:
        return []
    cap, _meta = open_video(video)
    if cap is None:
        log.debug("[crops] %s nicht lesbar", rel)
        return []
    out: list[dict] = []
    try:
        for track in tracks:
            sample = best_sample(track)
            if sample is None:
                continue
            ok, frame = read_frame_at(cap, int(sample["f"]))
            if not ok or frame is None:
                continue
            crop = crop_bbox(frame, sample["bbox"])
            if not _big_enough(crop):
                continue
            track_id = track.get("track_id")
            crop_rel = crop_relpath_for(rel, track_id)
            dest = root / crop_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(dest), crop, [int(cv2.IMWRITE_JPEG_QUALITY), CROP_QUALITY]):
                continue
            out.append(
                {
                    "track_id": track_id,
                    "relpath": crop_rel,
                    "score": float(sample.get("score") or 0.0),
                    "t": float(sample.get("t") or 0.0),
                }
            )
    finally:
        cap.release()
    return out


def crops_of(event: dict) -> list[dict]:
    """Die auf dem Ereignis notierten Ausschnitte."""
    val = (event or {}).get("person_crops")
    return [c for c in val if isinstance(c, dict)] if isinstance(val, list) else []


def needs_crops(event: dict, storage_root) -> bool:
    """Ob dieser Clip noch bearbeitet werden muss.

    BEIDE HÄLFTEN, nicht nur eine. Ein Ausschnitt auf der Platte, dessen
    Verweis das Ereignis nie erreicht hat, ist für die Galerie unsichtbar
    und würde beim nächsten Lauf trotzdem übersprungen — dieselbe Lehre,
    die der Filmstreifen-Nachlauf in seinem eigenen Kopf festhält.
    """
    noted = crops_of(event)
    if not noted:
        return True
    root = Path(storage_root)
    return any(not (root / c.get("relpath", "")).exists() for c in noted)


#: Wie viele Clips ein Durchlauf höchstens anfasst. Ein Ausschnitt ist
#: ein Sprung plus ein Schreibvorgang und damit im Zehntelsekundenbereich
#: — die Grenze schützt nicht vor Rechenzeit, sondern hält den Lauf
#: unterbrechbar, damit ein Neustart nicht mittendrin alles verwirft.
SWEEP_BUDGET = 400

#: Pause zwischen zwei Clips. Derselbe Wert und derselbe Grund wie beim
#: Filmstreifen-Nachlauf: ein Nachlauf darf den laufenden Kameras nicht
#: die Kerne wegnehmen.
SWEEP_PAUSE_S = 0.05


def sweep_person_crops(store, storage_root, *, cam_filter=None, budget=SWEEP_BUDGET) -> dict:
    """Über das Archiv laufen und fehlende Personen-Ausschnitte nachziehen.

    ``{"clips": n, "crops": n, "skipped": n, "remaining": n}`` —
    ``remaining`` ist nur dann von Null verschieden, wenn das Budget den
    Lauf abgeschnitten hat. Ein Aufrufer kann damit „morgen mehr" sagen,
    statt Vollständigkeit zu behaupten.

    NACHLAUF, NICHT AUF ABRUF. Die Galerie öffnet man, um Gesichter zu
    benennen — nicht, um dann auf hundert nacheinander dekodierte Clips
    zu warten. Dieselbe Entscheidung, die der Feinspur-Nachlauf in seinem
    eigenen Kopf begründet: „opening a clip is not the moment to start a
    job."
    """
    import time as _time

    root = Path(storage_root)
    events_dir = getattr(store, "events_dir", None)
    out = {"clips": 0, "crops": 0, "skipped": 0, "remaining": 0}
    if events_dir is None or not Path(events_dir).exists():
        return out
    cams = [d for d in Path(events_dir).iterdir() if d.is_dir()]
    if cam_filter:
        cams = [d for d in cams if d.name == cam_filter]
    for cam_dir in cams:
        for jf in sorted(cam_dir.rglob("*.json")):
            if jf.name.endswith(".tracks.json"):
                continue
            try:
                event = json.loads(jf.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if PERSON_LABEL not in (event.get("labels") or []):
                continue
            if not needs_crops(event, root):
                out["skipped"] += 1
                continue
            if budget is not None and out["clips"] >= budget:
                out["remaining"] += 1
                continue
            found = extract_person_crops(root, event)
            out["clips"] += 1
            if not found:
                continue
            out["crops"] += len(found)
            # Der Verweis gehört auf das Ereignis, sonst findet die
            # Galerie den Ausschnitt nie und der nächste Lauf hält den
            # Clip trotzdem für erledigt — siehe `needs_crops`.
            event["person_crops"] = found
            store.update_event(cam_dir.name, event.get("event_id") or jf.stem, event)
            _time.sleep(SWEEP_PAUSE_S)
    if out["crops"]:
        log.info(
            "[crops] %d Personen-Ausschnitte aus %d Clips (%d offen)",
            out["crops"],
            out["clips"],
            out["remaining"],
        )
    return out
