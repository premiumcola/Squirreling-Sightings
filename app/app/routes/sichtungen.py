"""Sichtungen — cat / person identity registration + species achievements.

Migrated from server.py during R01.2. The route bodies are byte-for-
byte the originals; references to module-level state in server.py
have been rewritten to flow through `app_state`.

Achievement persistence (`_load_achievements`, `_save_achievements`)
lives here, but this is no longer the only writer of
`achievements.json`: `species_unlock.py` owns the species half of that
file (eintragen, und seit dem Raster-Abgleich auch zurücknehmen). Beide
teilen sich deshalb DAS Schloss dieser Datei — siehe `_ach_lock` unten.
"""

from __future__ import annotations

import json as _json_mod
import logging

import cv2
from flask import Blueprint, jsonify, request

from .. import app_state, species_unlock as _species_unlock
from ..cat_identity import IdentityRegistry
from ..storage import _atomic_write_text

bp = Blueprint("sichtungen", __name__)


# ── Cat / person identity ────────────────────────────────────────────────


@bp.get('/api/cats')
def api_cats():
    return jsonify({"profiles": app_state.cat_registry.list_profiles()})


@bp.get('/api/persons')
def api_persons():
    return jsonify({"profiles": app_state.person_registry.list_profiles()})


def _register_identity(registry: IdentityRegistry, cam_id: str, identity_type: str):
    store = app_state.store
    storage_root = app_state.storage_root
    payload = request.get_json(force=True, silent=True) or {}
    event_id = payload.get("event_id")
    name = (payload.get("name") or "").strip()
    whitelisted = bool(payload.get("whitelisted", False))
    notes = payload.get("notes", "")
    if not event_id or not name:
        return jsonify({"ok": False, "error": "event_id und name erforderlich"}), 400
    event = store.get_event(cam_id, event_id)
    if not event:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    snap_rel = event.get("snapshot_relpath")
    snap_path = storage_root / snap_rel if snap_rel else None
    if not snap_path or not snap_path.exists():
        return jsonify({"ok": False, "error": "Snapshot-Datei fehlt"}), 404
    img = cv2.imread(str(snap_path))
    if img is None:
        return jsonify({"ok": False, "error": "Snapshot nicht lesbar"}), 400
    det = next((d for d in event.get("detections", []) if d.get("label") == identity_type), None)
    if not det:
        return jsonify({"ok": False, "error": f"Kein {identity_type} in diesem Event"}), 400
    b = det.get("bbox") or {}
    crop = img[
        max(0, int(b.get("y1", 0))) : max(0, int(b.get("y2", 0))),
        max(0, int(b.get("x1", 0))) : max(0, int(b.get("x2", 0))),
    ]
    if crop.size == 0:
        return jsonify({"ok": False, "error": "Crop leer"}), 400
    ok = registry.register_crop(name, crop, whitelisted=whitelisted, notes=notes)
    if ok:
        if identity_type == "cat":
            event["cat_name"] = name
        else:
            event["person_name"] = name
            event["whitelisted"] = whitelisted
        store.update_event(cam_id, event_id, event)
    return jsonify({"ok": bool(ok), "profiles": registry.list_profiles()})


@bp.post('/api/camera/<cam_id>/cats/register')
def api_cat_register(cam_id):
    return _register_identity(app_state.cat_registry, cam_id, "cat")


@bp.post('/api/camera/<cam_id>/persons/register')
def api_person_register(cam_id):
    return _register_identity(app_state.person_registry, cam_id, "person")


@bp.post('/api/persons/<name>/flags')
def api_person_flags(name):
    payload = request.get_json(force=True, silent=True) or {}
    ok = app_state.person_registry.set_profile_flags(
        name,
        whitelisted=payload.get("whitelisted"),
        notes=payload.get("notes"),
        anonymous=payload.get("anonymous"),
    )
    return jsonify({"ok": ok, "profiles": app_state.person_registry.list_profiles()})


@bp.post('/api/persons/<name>/rename')
def api_person_rename(name):
    """Umbenennen — und, wenn der neue Name schon vergeben ist,
    ZUSAMMENFÜHREN. Zwei Profile für eine Person ist das normale Ergebnis
    davon, Gesichter einzeln zu benennen; das hier ist der Weg zurück."""
    payload = request.get_json(force=True, silent=True) or {}
    ok = app_state.person_registry.rename_profile(name, (payload.get("to") or "").strip())
    return jsonify({"ok": ok, "profiles": app_state.person_registry.list_profiles()})


@bp.delete('/api/persons/<name>')
def api_person_delete(name):
    """Ein Profil vergessen. Die Ausschnitte bleiben auf der Platte und
    fallen zurück in den unbenannten Haufen."""
    ok = app_state.person_registry.delete_profile(name)
    return jsonify({"ok": ok, "profiles": app_state.person_registry.list_profiles()})


# ── Achievements ────────────────────────────────────────────────────────────

# EIN Schloss über EINER Datei. `species_unlock` schreibt dieselbe
# `achievements.json` — die Freischaltung einer Art und der nächtliche
# Abgleich — und hielt dafür sein eigenes. Zwei Schlösser über einer
# Datei sind kein Schloss: die Quest-Auswertung läuft nach JEDEM
# Bewegungsereignis und schreibt die Datei komplett neu, also konnte sie
# eine gerade eingetragene Art wieder wegschreiben. Seit der Abgleich
# auch ZURÜCKNIMMT, ginge es auch andersherum — ein zurückgenommenes
# Abzeichen käme aus dem Quest-Puffer wieder hoch, also genau der Fehler,
# den der Abgleich beheben soll.
_ach_lock = _species_unlock._LOCK


def _ach_path():
    return app_state.storage_root / "achievements.json"


def _load_achievements() -> dict:
    try:
        p = _ach_path()
        if p.exists():
            return _json_mod.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_achievements(data: dict):
    try:
        _atomic_write_text(_ach_path(), _json_mod.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        logging.getLogger(__name__).warning("achievements save: %s", e)


@bp.get('/api/achievements')
def api_achievements_get():
    with _ach_lock:
        data = _load_achievements()
    # Surface every quest-related block alongside the species map so the
    # frontend gets active + archive + upcoming-preview in one roundtrip.
    # Existing clients ignore unknown keys — purely additive.
    from ..quests import preview_upcoming_quests

    return jsonify(
        {
            "achievements": data,
            "quests": data.get("quests") or {},
            "quests_archive": data.get("quests_archive") or {},
            "upcoming": preview_upcoming_quests(),
        }
    )


@bp.post('/api/achievements/quests/reevaluate')
def api_achievements_quests_reevaluate():
    """Manual full re-eval — wired up to the "Re-Eval"-Button in the
    Sichtungen pinboard. Same evaluator that runs hourly in the
    background and after every motion event."""
    from ..quests import reevaluate_and_save

    result = reevaluate_and_save()
    return jsonify(result)


# Hier stand ein POST /api/achievements/unlock, das eine Art von Hand
# freischaltete und ihren Zähler hochzählte. Es hatte im ganzen Projekt
# keinen einzigen Aufrufer — und wäre seit dem Raster-Abgleich auch
# falsch: die Zahl auf der Kachel ist ab jetzt eine Frage ans Archiv,
# also hätte der nächste Lauf jede Freischaltung von Hand wieder
# einkassiert. Wer eine Art eintragen will, gibt ihr einen Clip.


# ── Bird-species backfill ────────────────────────────────────────────────
# Manual "Vogelarten nachträglich bestimmen" trigger — mirrors routes/
# tracking.py's /api/tracking/reindex-all button: an operator-driven,
# on-demand pass instead of waiting for the daily maintenance sweep
# (maintenance.py::_sweep_bird_species). Useful right after installing
# the classifier model, when the passive catch-up would otherwise wait
# up to 24h.


@bp.post('/api/bird-species/backfill')
def api_bird_species_backfill():
    from ..bird_species_backfill import (
        MANUAL_BACKFILL_BUDGET,
        build_backfill_classifier,
        dossier_hook_for,
        dossier_lookup_for,
        sweep_bird_species_backfill,
    )

    classifier = build_backfill_classifier(app_state.get_effective_config())
    if not classifier.available:
        return jsonify(
            {
                "ok": False,
                "error": "Vogelarten-Klassifikator nicht verfügbar",
                "reason": classifier.reason,
                "examined": 0,
                "changed": 0,
            }
        ), 503
    cams = app_state.get_effective_config().get("cameras", []) or []
    cam_ids = [c["id"] for c in cams if c.get("id")]
    result = sweep_bird_species_backfill(
        app_state.store,
        app_state.storage_root,
        classifier,
        cam_ids,
        budget=MANUAL_BACKFILL_BUDGET,
        dossier_hook=dossier_hook_for(app_state.bird_dossiers),
        dossier_lookup=dossier_lookup_for(app_state.bird_dossiers),
    )
    return jsonify({"ok": True, **result})


# ── Sichtungsbuch (append-only) ────────────────────────────────────────────


@bp.get('/api/sightings/ledger')
def api_sightings_ledger():
    """Die Erkennungen, unabhängig davon, ob ihr Video noch da ist.

    Jede andere Art-Statistik dieser Anwendung zählt Dateien: das
    Sichtungs-Raster (`species_board.tally_species`), die Artfilter der
    Mediathek (`media_index/_visible.py::camera_stats`), die Zeitleiste.
    Das ist dort richtig — wer zählt, was er anzeigt, kann nicht
    auseinanderlaufen. Aber es heißt eben auch: einen Clip löschen heißt,
    die Sichtung löschen, und danach war der Vogel nie da.

    Diese Antwort kommt stattdessen aus `sightings_ledger` und ist damit
    die einzige, die eine Aufräumaktion überlebt — „auch wenn ich die
    video lösche […] auch für die statistik gespeichert". Nur-lesend;
    geschrieben wird das Buch beim Erkennen, beim Korrigieren und ein
    letztes Mal unmittelbar vor dem Löschen.

    ``since`` / ``until`` sind Kalendertage (``YYYY-MM-DD``, beide
    einschließlich), ``species`` grenzt auf eine Art ein.
    """
    from ..sightings_ledger import daily_counts, species_totals

    since = request.args.get("since") or None
    until = request.args.get("until") or None
    species = request.args.get("species") or None
    root = app_state.storage_root
    totals = species_totals(root, since=since, until=until, species=species)
    return jsonify(
        {
            "ok": True,
            "since": since,
            "until": until,
            "species": species,
            "species_totals": totals,
            "per_day": daily_counts(root, since=since, until=until, species=species),
            "total": sum(row["count"] for row in totals.values()),
        }
    )


# ── Bird dossiers (F08) ────────────────────────────────────────────────────


@bp.get('/api/bird-dossiers')
def api_bird_dossiers_list():
    svc = app_state.bird_dossiers
    if svc is None:
        return jsonify({"dossiers": []})
    return jsonify({"dossiers": svc.list_dossiers()})


@bp.get('/api/bird-dossiers/<path:latin>')
def api_bird_dossier_detail(latin: str):
    """Single dossier plus the last 10 motion events that featured this
    species. The events are gathered from every camera (a species
    visits multiple cams over time) and sorted by time DESC."""
    svc = app_state.bird_dossiers
    if svc is None:
        return jsonify({"ok": False, "error": "service unavailable"}), 404
    d = svc.get_dossier(latin)
    if not d:
        return jsonify({"ok": False, "error": "not found"}), 404
    store = app_state.store
    settings = app_state.settings
    cams = (
        settings.export_effective_config(app_state.base_cfg).get("cameras", []) or []
        if settings
        else []
    )
    events: list = []
    for cam in cams:
        cam_id = cam.get("id")
        if not cam_id:
            continue
        for ev in store.list_events(cam_id, limit=200, media_only=True):
            for det in ev.get("detections") or []:
                if (det.get("species_latin") or "").strip() == latin:
                    events.append(ev)
                    break
    events.sort(key=lambda e: e.get("time", ""), reverse=True)
    return jsonify({"ok": True, "dossier": d, "events": events[:10]})


@bp.post('/api/bird-dossiers/<path:latin>/refetch')
def api_bird_dossier_refetch(latin: str):
    svc = app_state.bird_dossiers
    if svc is None:
        return jsonify({"ok": False, "error": "service unavailable"}), 404
    started = svc.refetch_dossier(latin)
    if not started:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "queued": True})


@bp.get('/api/achievements/<species_id>/media')
def api_achievements_media(species_id: str):
    """All media events for a species, across every camera. The species
    is identified by its achievement ID (e.g. "gruenfink"); we walk the
    camera_runtime._SPECIES_TO_ACH_ID reverse-map to find every German
    variant that collapses into that ID ("Grünfink" / "Gruenfink") and
    union the results."""
    from ..camera_runtime import _SPECIES_TO_ACH_ID

    settings = app_state.settings
    store = app_state.store
    sid = (species_id or "").strip().lower()
    # Collect every species-name key that maps to this achievement ID
    name_variants = {name for name, ach in _SPECIES_TO_ACH_ID.items() if ach == sid}
    if not name_variants:
        return jsonify({"items": [], "total_count": 0})
    # Flask's type=int returns None on parse failure → fall through
    # to the legacy default. No more try/except wrappers needed.
    limit = max(1, request.args.get('limit', type=int) or 24)
    offset = max(0, request.args.get('offset', type=int) or 0)
    cams = app_state.get_effective_config().get("cameras", []) or []
    seen_ids: set[str] = set()
    pool: list = []
    for cam in cams:
        cam_id = cam.get("id")
        if not cam_id:
            continue
        for variant in name_variants:
            # list_events sorts desc by time internally. media_only skips
            # metadata-only entries — the drilldown only wants visible cards.
            for ev in store.list_events(cam_id, bird_species=variant, media_only=True, limit=5000):
                eid = ev.get("event_id")
                if not eid or eid in seen_ids:
                    continue
                seen_ids.add(eid)
                # Attach any stored review so the drilldown matches what the
                # main Mediathek shows for the same event.
                review = settings.get_review(f"{cam_id}:{eid}")
                if review:
                    ev["review"] = review
                pool.append(ev)
    pool.sort(key=lambda x: x.get("time", ""), reverse=True)
    total = len(pool)
    page = pool[offset : offset + limit]
    return jsonify({"items": page, "total_count": total})
