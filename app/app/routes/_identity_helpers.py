"""Gemeinsamer Unterbau für die Identitäten-Verwaltung.

„Die Zuordnung der Identitäten … sollte in dem Einstellungsmenü
Identitäten stattfinden. … Ich muss da bisschen an Google Fotos denken:
da wird nach Gesichtern gescannt, und sobald man etliche eingeordnet hat,
werden die nächsten automatisch zugeordnet."

Drei Dinge, die sich sonst über drei Blueprints verteilt hätten: das
Archiv nach Ausschnitten durchgehen, zu einem Ausschnitt einen Namen
VORSCHLAGEN, und einen Ausschnitt tatsächlich ablegen. Der Vorschlag und
die Ablage sind derselbe Vorgang aus zwei Entfernungen — deshalb stehen
sie nebeneinander und nicht in zwei Modulen.

WIE GUT DER VORSCHLAG IST, EHRLICH: der Abgleich ist ein dHash-Vergleich
(`cat_identity.dhash_bgr`), also Bildähnlichkeit, keine Gesichtserkennung.
Auf zwei Aufnahmen derselben Person in derselben Jacke am selben Ort
trifft er gut; über Kleidung, Tageszeit und Blickwinkel hinweg nicht. Für
den automatischen Lauf gilt deshalb eine STRENGERE Schwelle als für den
bloßen Vorschlag, und jede automatische Zuordnung wird als solche notiert
(`person_source: "auto"`), damit sie in der Oberfläche erkennbar bleibt
und zurückgenommen werden kann.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2

from ..cat_identity import IdentityRegistry
from ..person_crops import crops_of

#: Höchstabstand, ab dem der automatische Lauf zugreift. Die Registry
#: selbst schlägt bis `threshold` (10) noch etwas vor; von allein etwas
#: abzulegen ist eine andere Zusage als es vorzuschlagen, also liegt die
#: Latte hier höher.
AUTO_MAX_DISTANCE = 6

#: Wie viele Ausschnitte ein Vorschlagslauf höchstens öffnet. Jeder
#: Vorschlag ist ein JPEG von der Platte plus ein Hash — billig einzeln,
#: nicht mehr billig über ein ganzes Archiv, und die Galerie zeigt
#: ohnehin nur eine Seite.
SUGGEST_BUDGET = 120


def walk_person_crops(events_dir, *, only_unnamed: bool) -> list[dict]:
    """Alle notierten Ausschnitte, neueste zuerst.

    Gelesen wird aus den Ereignissen selbst — dort steht der Verweis, den
    der Nachlauf hinterlassen hat. Ein zweiter Index wäre eine zweite
    Wahrheit, die mit der ersten auseinanderlaufen kann.
    """
    rows: list[dict] = []
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
            crops = crops_of(event)
            if not crops:
                continue
            named = event.get("person_name")
            if only_unnamed and named:
                continue
            for c in crops:
                rows.append(
                    {
                        "event_id": event.get("event_id") or jf.stem,
                        "cam_id": event.get("camera_id") or cam_dir.name,
                        "time": event.get("time") or "",
                        "track_id": c.get("track_id"),
                        "url": f"/media/{c.get('relpath', '')}",
                        "relpath": c.get("relpath"),
                        "score": c.get("score"),
                        "person_name": named,
                        "person_source": event.get("person_source") or "",
                    }
                )
    rows.sort(key=lambda r: r.get("time") or "", reverse=True)
    return rows


def read_crop(storage_root, relpath: str):
    """Das Bild zu einem Verweis — oder None.

    Der Pfad kommt aus unserer eigenen Liste, aber er kommt über das Netz
    zurück, also wird er gegen das Archiv geprüft und nicht geglaubt.
    """
    if not relpath:
        return None
    root = Path(storage_root).resolve()
    path = (Path(storage_root) / relpath).resolve()
    if not str(path).startswith(str(root)) or not path.exists():
        return None
    return cv2.imread(str(path))


def suggest_for(registry: IdentityRegistry, storage_root, rows: list[dict], budget: int) -> None:
    """Hängt jeder Zeile — soweit das Budget reicht — einen `suggest` an.

    Ohne Profile gibt es nichts zu vergleichen; dann bleibt der Lauf aus,
    statt jedes Bild umsonst von der Platte zu holen.
    """
    if not registry.list_profiles():
        return
    opened = 0
    for row in rows:
        if opened >= budget:
            return
        img = read_crop(storage_root, row.get("relpath") or "")
        if img is None:
            continue
        opened += 1
        match = registry.match_details(img)
        if match:
            row["suggest"] = {
                "name": match.get("name"),
                "distance": match.get("distance"),
                "confident": int(match.get("distance", 99)) <= AUTO_MAX_DISTANCE,
            }


def file_crop(
    registry: IdentityRegistry,
    store,
    storage_root,
    item: dict,
    name: str,
    *,
    whitelisted: bool | None = None,
    notes: str = "",
    auto: bool = False,
    anonymous: bool | None = None,
) -> bool:
    """Einen Ausschnitt einer Person zuordnen: Probe in die Registry, Name
    auf das Ereignis. Beides oder nichts — ein Profil ohne das Ereignis
    dahinter fällt beim nächsten Lauf wieder in den unbenannten Haufen.

    Die Clip-Kennung wandert mit in die Registry: ohne sie lässt sich
    später nicht mehr trennen, was aus demselben Auftritt stammt, und die
    Güteprüfung (`identity_quality.py`) misst dann sich selbst."""
    img = read_crop(storage_root, (item or {}).get("relpath") or "")
    if img is None or not name:
        return False
    ok = registry.register_crop(
        name,
        img,
        whitelisted=bool(whitelisted),
        notes=notes,
        relpath=item.get("relpath") or "",
        event_id=(item.get("event_id") or "").strip(),
        anonymous=anonymous,
    )
    if not ok:
        return False
    cam_id = (item.get("cam_id") or "").strip()
    event_id = (item.get("event_id") or "").strip()
    if cam_id and event_id:
        event = store.get_event(cam_id, event_id)
        if event:
            event["person_name"] = name
            event["person_source"] = "auto" if auto else "manual"
            if whitelisted is not None:
                event["whitelisted"] = bool(whitelisted)
            store.update_event(cam_id, event_id, event)
    return True


def clear_person(store, cam_id: str, event_id: str) -> bool:
    """Den Namen von einem Ereignis nehmen — der Weg zurück aus einer
    falschen automatischen Zuordnung. Die Probe in der Registry bleibt;
    die wird über das Profil selbst verworfen, nicht über ein Ereignis."""
    if not cam_id or not event_id:
        return False
    event = store.get_event(cam_id, event_id)
    if not event:
        return False
    event.pop("person_name", None)
    event.pop("person_source", None)
    store.update_event(cam_id, event_id, event)
    return True
