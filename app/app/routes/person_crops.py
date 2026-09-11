"""Personen-Ausschnitte auflisten, zuordnen und automatisch einsortieren.

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

Das Durchgehen des Archivs, der Vorschlag und das Ablegen stehen in
`_identity_helpers.py` — dieses Modul ist nur noch die HTTP-Schicht
darüber.
"""

from __future__ import annotations

import logging
import threading

from flask import Blueprint, jsonify, request

from .. import app_state
from ..person_crops import sweep_person_crops
from ._identity_helpers import (
    SUGGEST_BUDGET,
    clear_person,
    file_crop,
    suggest_for,
    walk_person_crops,
)

bp = Blueprint("person_crops", __name__)

log = logging.getLogger(__name__)

#: Wie viele Ausschnitte eine Seite der Galerie zeigt.
_PAGE = 60

_sweep_lock = threading.Lock()


def _events_dir():
    return getattr(app_state.store, "events_dir", None)


def _profile_card(profile: dict) -> dict:
    """Ein Profil so, wie die Karte es braucht.

    Ohne die Hashes: das sind je Probe sechzehn Hexziffern, die niemand
    ansieht, und sie machen die Antwort um ein Vielfaches größer als den
    Teil, der tatsächlich angezeigt wird. Die Ausschnitte kommen als
    fertige URLs zurück, damit die Oberfläche den Speicheraufbau nicht
    kennen muss.
    """
    return {
        "name": profile.get("name"),
        "whitelisted": bool(profile.get("whitelisted")),
        "notes": profile.get("notes", ""),
        "samples": len(profile.get("hashes") or []),
        "crops": [f"/media/{c}" for c in (profile.get("crops") or [])],
    }


@bp.get('/api/identities')
def api_identities():
    """Alles, was die Identitäten-Karte in einem Rutsch braucht: die
    benannten Personen, die Katzen und wie viele Gesichter noch
    unsortiert herumliegen."""
    rows = walk_person_crops(_events_dir(), only_unnamed=False)
    return jsonify(
        {
            "persons": [_profile_card(p) for p in app_state.person_registry.list_profiles()],
            "cats": [_profile_card(p) for p in app_state.cat_registry.list_profiles()],
            "crops": {
                "total": len(rows),
                "unnamed": sum(1 for r in rows if not r.get("person_name")),
                "auto": sum(1 for r in rows if r.get("person_source") == "auto"),
            },
        }
    )


@bp.get('/api/person-crops')
def api_person_crops():
    """Die Galerie: Ausschnitte zum Benennen, neueste zuerst.

    `only_unnamed=1` blendet aus, was schon eine Person trägt — das ist
    die Ansicht, in der man tatsächlich arbeitet. `suggest=1` legt zu
    jedem Ausschnitt den nächstgelegenen bekannten Namen dazu; das öffnet
    jedes Bild einzeln und gilt deshalb nur für die gezeigte Seite.
    """
    limit = max(1, min(200, request.args.get('limit', type=int) or _PAGE))
    offset = max(0, request.args.get('offset', type=int) or 0)
    only_unnamed = request.args.get('only_unnamed') in ('1', 'true', 'yes')
    rows = walk_person_crops(_events_dir(), only_unnamed=only_unnamed)
    page = rows[offset : offset + limit]
    if request.args.get('suggest') in ('1', 'true', 'yes'):
        suggest_for(app_state.person_registry, app_state.storage_root, page, SUGGEST_BUDGET)
    return jsonify({"items": page, "total": len(rows)})


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
    """Ausschnitte einer Person zuordnen — einen oder einen ganzen Schwung.

    Das ist der Vorgang, für den es die Ausschnitte gibt: der Ausschnitt
    wandert als Erkennungsprobe in `person_registry.json`, und das
    Ereignis merkt sich den Namen. Ein Profil entsteht dabei von selbst —
    `IdentityRegistry.register_crop` legt es beim ersten Ausschnitt an,
    es gibt bewusst kein „Person anlegen" davor.

    Mehrere auf einmal, weil das Einsortieren genau so abläuft: man
    erkennt eine Reihe Kacheln als dieselbe Person und tippt einmal.
    """
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        items = [payload]
    items = [i for i in items if isinstance(i, dict) and (i.get("relpath") or "").strip()]
    if not items or not name:
        return jsonify({"ok": False, "error": "relpath und name erforderlich"}), 400
    whitelisted = payload.get("whitelisted")
    registry = app_state.person_registry
    filed = 0
    for item in items:
        if file_crop(
            registry,
            app_state.store,
            app_state.storage_root,
            item,
            name,
            whitelisted=None if whitelisted is None else bool(whitelisted),
            notes=payload.get("notes", ""),
        ):
            filed += 1
    if not filed:
        return jsonify({"ok": False, "error": "Ausschnitt nicht lesbar"}), 400
    return jsonify({"ok": True, "filed": filed, "profiles": registry.list_profiles()})


@bp.post('/api/person-crops/auto-assign')
def api_person_crops_auto_assign():
    """Die sicheren Vorschläge in einem Zug übernehmen.

    „sobald man dann etliche eingeordnet hat, werden die nächsten
    automatisch zugeordnet." Genau das — aber nur die, bei denen der
    Abstand klein genug ist (`AUTO_MAX_DISTANCE`), und jede Zuordnung
    trägt `person_source: "auto"`, damit sie sichtbar bleibt und einzeln
    zurückgenommen werden kann.
    """
    registry = app_state.person_registry
    if not registry.list_profiles():
        return jsonify({"ok": False, "error": "Noch keine benannte Person"}), 400
    rows = walk_person_crops(_events_dir(), only_unnamed=True)
    suggest_for(registry, app_state.storage_root, rows, SUGGEST_BUDGET)
    filed = 0
    for row in rows:
        hint = row.get("suggest") or {}
        if not hint.get("confident"):
            continue
        if file_crop(
            registry, app_state.store, app_state.storage_root, row, hint["name"], auto=True
        ):
            filed += 1
    return jsonify({"ok": True, "filed": filed, "scanned": len(rows)})


@bp.post('/api/person-crops/clear')
def api_person_crops_clear():
    """Den Namen von einem Ereignis nehmen — der Weg zurück, wenn der
    automatische Lauf danebengelegen hat."""
    payload = request.get_json(force=True, silent=True) or {}
    ok = clear_person(
        app_state.store,
        (payload.get("cam_id") or "").strip(),
        (payload.get("event_id") or "").strip(),
    )
    return jsonify({"ok": ok}), (200 if ok else 404)
