"""Personen-Ausschnitte auflisten und einer Person zuordnen.

„kannst du fotos der personen aus allen videos extrahieren damit ich die
dann auf individuen branden kann? ... die genehmigung habe ich!"

Ein eigenes Blueprint statt einer Erweiterung von `sichtungen.py`: dort
stehen die Katzen-/Personen-Profile und die Abzeichen, und dort steht auch
der alte `.../persons/register`, der aus dem SCHNAPPSCHUSS schneidet. Der
bleibt, wo er ist — die Zuordnung hier holt ihren Ausschnitt aus dem Clip
und ist damit ein anderer Vorgang, kein Nachbessern am selben.

WARUM DER ALTE WEG NICHT REICHTE: er schneidet das Rechteck aus dem
Ereignis aus dem gespeicherten Schnappschuss, und die beiden liegen nicht
im selben Pixelraum — der Schnappschuss ist auf 1280 herunterskaliert,
bei Clips sogar nur das ≤640er Vorschaubild aus der Mitte des Videos,
während das Rechteck in voller Stromauflösung notiert ist. Für
Clip-Ereignisse antwortet er deshalb in der Regel mit „Crop leer". Die
Ausschnitte hier stammen aus dem Clip selbst (siehe `person_crops.py`),
womit dieselbe Registrierung endlich das bekommt, was sie braucht.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from .. import app_state
from ..person_crops import crops_of, sweep_person_crops

bp = Blueprint("person_crops", __name__)

log = logging.getLogger(__name__)

#: Wie viele Ausschnitte eine Seite der Galerie zeigt.
_PAGE = 60

_sweep_lock = threading.Lock()


def _walk_crops(limit: int, offset: int, *, only_unnamed: bool) -> tuple[list, int]:
    """Alle notierten Ausschnitte, neueste zuerst.

    Gelesen wird aus den Ereignissen selbst — dort steht der Verweis, den
    der Nachlauf hinterlassen hat. Ein zweiter Index wäre eine zweite
    Wahrheit, die mit der ersten auseinanderlaufen kann.
    """
    events_dir = getattr(app_state.store, "events_dir", None)
    rows: list[dict] = []
    if events_dir is None or not Path(events_dir).exists():
        return [], 0
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
                    }
                )
    rows.sort(key=lambda r: r.get("time") or "", reverse=True)
    return rows[offset : offset + limit], len(rows)


@bp.get('/api/person-crops')
def api_person_crops():
    """Die Galerie: Ausschnitte zum Benennen, neueste zuerst.

    `only_unnamed=1` blendet aus, was schon eine Person trägt — das ist
    die Ansicht, in der man tatsächlich arbeitet.
    """
    limit = max(1, min(200, request.args.get('limit', type=int) or _PAGE))
    offset = max(0, request.args.get('offset', type=int) or 0)
    only_unnamed = request.args.get('only_unnamed') in ('1', 'true', 'yes')
    items, total = _walk_crops(limit, offset, only_unnamed=only_unnamed)
    return jsonify({"items": items, "total": total})


@bp.post('/api/person-crops/sweep')
def api_person_crops_sweep():
    """Den Nachlauf anstoßen. Antwortet sofort, arbeitet im Hintergrund.

    Ein Durchlauf ist ein Sprung plus ein Schreibvorgang je Person — im
    Zehntelsekundenbereich — aber über ein ganzes Archiv summiert sich
    das, und eine HTTP-Antwort ist nicht der Ort, an dem man darauf
    wartet. Nur einer zur Zeit: zwei Läufe über denselben Baum schreiben
    dieselben Dateien doppelt.
    """
    if not _sweep_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Ein Lauf ist bereits unterwegs"}), 409

    def _run():
        try:
            res = sweep_person_crops(app_state.store, app_state.storage_root)
            log.info("[crops] Nachlauf fertig: %s", res)
        except Exception as e:
            log.warning("[crops] Nachlauf fehlgeschlagen: %s", e)
        finally:
            _sweep_lock.release()

    threading.Thread(target=_run, name="person-crops-sweep", daemon=True).start()
    return jsonify({"ok": True, "started": True})


@bp.post('/api/person-crops/assign')
def api_person_crops_assign():
    """Einen Ausschnitt einer Person zuordnen.

    Das ist der Vorgang, für den es die Ausschnitte gibt: der Ausschnitt
    wandert als Erkennungsprobe in `person_registry.json`, und das
    Ereignis merkt sich den Namen. Ein Profil entsteht dabei von selbst —
    `IdentityRegistry.register_crop` legt es beim ersten Ausschnitt an,
    es gibt bewusst kein „Person anlegen" davor.
    """
    import cv2

    payload = request.get_json(force=True, silent=True) or {}
    relpath = (payload.get("relpath") or "").strip()
    name = (payload.get("name") or "").strip()
    cam_id = (payload.get("cam_id") or "").strip()
    event_id = (payload.get("event_id") or "").strip()
    if not relpath or not name:
        return jsonify({"ok": False, "error": "relpath und name erforderlich"}), 400
    # Der Pfad kommt aus unserer eigenen Liste, aber er kommt über das
    # Netz zurück — also wird er gegen das Archiv geprüft und nicht
    # geglaubt.
    root = app_state.storage_root
    path = (root / relpath).resolve()
    if not str(path).startswith(str(root.resolve())) or not path.exists():
        return jsonify({"ok": False, "error": "Ausschnitt nicht gefunden"}), 404
    img = cv2.imread(str(path))
    if img is None:
        return jsonify({"ok": False, "error": "Ausschnitt nicht lesbar"}), 400
    registry = app_state.person_registry
    ok = registry.register_crop(
        name,
        img,
        whitelisted=bool(payload.get("whitelisted", False)),
        notes=payload.get("notes", ""),
    )
    if ok and cam_id and event_id:
        store = app_state.store
        event = store.get_event(cam_id, event_id)
        if event:
            event["person_name"] = name
            if "whitelisted" in payload:
                event["whitelisted"] = bool(payload.get("whitelisted"))
            store.update_event(cam_id, event_id, event)
    return jsonify({"ok": bool(ok), "profiles": registry.list_profiles()})
