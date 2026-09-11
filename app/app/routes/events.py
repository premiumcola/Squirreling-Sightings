"""Event CRUD — single-event delete, bulk delete, confirm, label edit, review.

Migrated from server.py during R01.4. Every write goes through the
`store.update_event` / `store.delete_event` API; the storage layer
handles atomic writes since B08.

FB-1 · the three surfaces here that carry a human judgement also write it
to the durable ledger (`detection_feedback`), joined to the alert record
by ``event_id``. Before this, every correction made in the web UI was
thrown away: `confirmed` has no reader in the Python code, and `labels`
is overwritten by the detector on every event, so an edited and an
auto-labelled event are indistinguishable on disk (see
`storage.JUDGEMENT_FIELDS`).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

from .. import app_state, trash as _trash
from ..detection_feedback import record_verdict
from ..event_relabel import apply_label_change, neutralize_sidecar_file
from ..species_video_count import record_confirmed_video

bp = Blueprint("events", __name__)


def _ledger_verdict(cam_id, event_id, *, correct, source, corrected_label=None, species=None):
    """Best-effort verdict write. A ledger failure must never turn a
    successful user action into a 500 — the module's own contract is
    that every write is swallowed and logged, and this keeps the same
    promise for the exception the caller could still raise (a missing
    storage root, a bad argument).

    ``species`` forwards straight to ``record_verdict`` — orthogonal to
    ``corrected_label``, see that function's own docstring. Optional so
    every existing call site (none of which judge a species) is
    unaffected; the web species-correction route below is the first
    caller that passes one, mirroring the Telegram path
    (`telegram_bot._inbound_event._book_verdict`), which already does.
    """
    with contextlib.suppress(Exception):
        record_verdict(
            app_state.storage_root,
            event_id=event_id,
            correct=correct,
            ts=time.time(),
            corrected_label=corrected_label,
            source=source,
            cam_id=cam_id,
            species=species,
        )


def _resync_species_board() -> None:
    """Das Sichtungs-Raster gegen das Archiv nachziehen.

    Jeder Aufruf hier folgt auf eine Änderung, die eine Art betreffen
    kann: eine Umbenennung, eine Artkorrektur, eine Löschung. Bis
    hierher hat KEINE davon das Raster angefasst, weil die Freischaltung
    eine reine Sperrklinke war — also blieb eine Fehlerkennung
    freigeschaltet, nachdem der Clip, der sie ausgelöst hat, längst
    etwas anderes hieß: „Einmal freigeschaltet heißt anscheinend
    freigeschaltet."

    Im Hintergrund, weil ein Dateidurchlauf über das Archiv nichts in
    einer Antwort auf einen Tap zu suchen hat; und best-effort, weil ein
    misslungener Abgleich die Korrektur selbst nicht scheitern lassen
    darf — der nächtliche Lauf holt ihn ohnehin nach.
    """
    with contextlib.suppress(Exception):
        from ..species_board import resync_species_board

        threading.Thread(
            target=lambda: resync_species_board(app_state.store, app_state.storage_root),
            name="species-board-resync",
            daemon=True,
        ).start()


@bp.delete('/api/camera/<cam_id>/events/<event_id>')
def api_event_delete(cam_id, event_id):
    """Soft-delete: move the event into ``storage/.trash/`` instead
    of hard-deleting. The trash entry sits for ``trash.grace_days``
    days before the daily sweep removes it. /api/trash/<id>/restore
    moves it back; /api/trash/empty hard-deletes everything now."""
    storage_root = app_state.storage_root
    result = _trash.move_to_trash(cam_id, event_id)
    # Timelapse fallback: tl_<stem> events live in storage/timelapse/<cam>/
    # and may not have an EventStore JSON yet (the migration that
    # registers them on boot can race against the user clicking delete
    # before it finishes, and old installs predate the unified
    # registration entirely). Also clean up the on-disk mp4 + sidecar +
    # thumb so the file disappears from the gallery either way.
    tl_cleaned = False
    if event_id.startswith("tl_"):
        stem = event_id[3:]
        if "/" not in stem and "\\" not in stem and ".." not in stem:
            tl_dir = storage_root / "timelapse" / cam_id
            mp4 = tl_dir / f"{stem}.mp4"
            if mp4.exists():
                mp4.unlink(missing_ok=True)
                tl_cleaned = True
                for suffix in (".json", ".jpg"):
                    companion = tl_dir / f"{stem}{suffix}"
                    if companion.exists():
                        with contextlib.suppress(Exception):
                            companion.unlink()
    if not result["json_deleted"] and not tl_cleaned:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    # Deleting a motion event is the user calling it a false alarm — but
    # only AFTER we know something was really deleted, and only for a
    # real event. Two ways this fabricated user claims when it sat above:
    #   * a 404 (double-tap, client retry) still booked a verdict;
    #   * the timelapse card's delete posts a second DELETE for
    #     `tl_<stem>` as a backstop, which booked "false alarm" for a
    #     timelapse video nobody judged.
    # A poisoned corpus is worse than an empty one: it silently biases
    # every threshold this data will later be used to calibrate.
    if not event_id.startswith("tl_"):
        _ledger_verdict(cam_id, event_id, correct=False, source="web_delete")
    # Der gelöschte Clip kann der einzige gewesen sein, der eine Art
    # belegt hat — dann fällt ihr Abzeichen mit ihm.
    _resync_species_board()
    return jsonify({"ok": True, "tl_cleaned": tl_cleaned, **result})


def _species_losing_proof(cam_id: str, event_ids: list) -> dict:
    """``{Art: Anzahl}`` für jede Art, die diese Löschung restlos träfe.

    Best-effort: kann das Archiv nicht gelesen werden, wird nicht
    gefragt — eine Rückfrage, die aus einem Lesefehler entsteht, ist
    schlechter als keine, weil sie den Betreiber darauf trainiert, sie
    wegzuklicken.
    """
    try:
        from ..species_board import species_losing_last_proof

        events_dir = getattr(app_state.store, "events_dir", None)
        return species_losing_last_proof(events_dir, event_ids)
    except Exception:
        logging.getLogger(__name__).debug(
            "[storage] Art-Beleg-Prüfung für %s übersprungen", cam_id, exc_info=True
        )
        return {}


@bp.post('/api/camera/<cam_id>/events/delete-bulk')
def api_event_delete_bulk(cam_id):
    """Bulk soft-delete — every successfully-moved event lands in
    the trash. Frontend URL stays the same so no client change is
    needed; the only behavioural difference is restorability."""
    payload = request.get_json(force=True, silent=True) or {}
    raw_ids = payload.get("event_ids")
    if not isinstance(raw_ids, list):
        return jsonify({"ok": False, "error": "event_ids muss eine Liste sein"}), 400
    event_ids = [eid for eid in raw_ids if isinstance(eid, str) and eid]
    if not event_ids:
        return jsonify({"ok": False, "error": "Keine event_ids angegeben"}), 400
    if len(event_ids) > 500:
        return jsonify({"ok": False, "error": "Maximal 500 Events pro Aufruf"}), 400
    # KEIN ABZEICHEN OHNE BELEG. Seit das Sichtungs-Raster aus dem Archiv
    # abgeleitet wird, nimmt eine Löschung, die die LETZTE Aufnahme einer
    # Art erwischt, auch deren Erkennung mit — und eine Sammelauswahl
    # über eine gefilterte Seite trifft genau diesen Fall leicht.
    # Nicht verbieten: der Betreiber darf eine Fehlerkennung samt
    # Abzeichen loswerden wollen. Aber nicht, ohne es zu wissen.
    if not payload.get("force"):
        losing = _species_losing_proof(cam_id, event_ids)
        if losing:
            return jsonify(
                {
                    "ok": False,
                    "needs_confirm": "species_proof",
                    "species": losing,
                    "error": "Letzte Aufnahmen dieser Arten",
                }
            ), 409
    deleted = 0
    failed = []
    for eid in event_ids:
        try:
            result = _trash.move_to_trash(cam_id, eid)
            if result.get("json_deleted"):
                deleted += 1
                # Deliberately books NOTHING. A bulk delete is tidying,
                # not judging: one gesture over a checkbox range up to
                # 500 wide would write 500 "Fehlalarm" verdicts nobody
                # looked at — and because `LedgerIndex` is last-write-
                # wins per event_id, every one of them would OVERWRITE
                # an honest ✅ the operator had already tapped in
                # Telegram. This project has been burned by exactly this
                # class twice (a deleted timelapse booked "false alarm",
                # a 404 double-tap booked one). Judging stays where a
                # human looked at one picture: the Telegram buttons and
                # the per-event web verdict.
            else:
                failed.append(eid)
        except Exception:
            failed.append(eid)
    logging.getLogger(__name__).info(
        "[bulk-delete→trash] cam=%s trashed=%d failed=%d",
        cam_id,
        deleted,
        len(failed),
    )
    # Einmal für den ganzen Schwung, nicht einmal je Clip: der Abgleich
    # liest ohnehin das gesamte Archiv, 500 Läufe wären 500-mal dieselbe
    # Antwort.
    if deleted:
        _resync_species_board()
    return jsonify({"ok": True, "deleted": deleted, "failed": failed})


@bp.post('/api/camera/<cam_id>/events/<event_id>/confirm')
def api_event_confirm(cam_id, event_id):
    store = app_state.store
    event = store.get_event(cam_id, event_id)
    if not event:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    event["confirmed"] = True
    event["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    store.update_event(cam_id, event_id, event)
    _ledger_verdict(cam_id, event_id, correct=True, source="web")
    return jsonify({"ok": True})


def _relabel_sidecar(event: dict, removed: set) -> None:
    """Carry a label correction into the clip's tracks.json, if it has
    one. Best-effort by construction — see neutralize_sidecar_file."""
    if not removed:
        return
    rel = event.get("video_relpath")
    if not rel:
        return
    with contextlib.suppress(Exception):
        from ..tracking_worker import tracks_path_for

        neutralize_sidecar_file(tracks_path_for(app_state.storage_root / rel), removed)


@bp.post('/api/camera/<cam_id>/events/<event_id>/labels')
def api_event_labels(cam_id, event_id):
    store = app_state.store
    payload = request.get_json(force=True, silent=True) or {}
    labels = payload.get("labels", [])
    event = store.get_event(cam_id, event_id)
    if not event:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    # Keep top_label in sync with labels so timeline/badges/stats agree,
    # and drop cat_name/bird_species when the class they pin just left
    # the list — see event_relabel for why both matter.
    prev_top = event.get("top_label")
    removed = set(event.get("labels") or []) - set(labels)
    apply_label_change(event, labels)
    store.update_event(cam_id, event_id, event)
    # The rail draws its lanes from the tracks.json sidecar whenever one
    # exists, so a correction that only rewrote the event left the
    # timeline still labelled with the class just taken off it. See
    # event_relabel.neutralize_sidecar_tracks.
    _relabel_sidecar(event, removed)
    # „bird" aus den Labels zu nehmen löscht `bird_species` mit (siehe
    # event_relabel.IDENTITY_FIELDS) — die Art verliert damit einen Beleg
    # und womöglich ihren letzten.
    _resync_species_board()
    # Only a changed top_label is a correction. Adding a secondary label
    # leaves the detector's verdict standing — recording that as "wrong"
    # would poison the corpus with events the user never disputed.
    #
    # Two shapes are excluded on purpose, because both fabricate a claim
    # the user never made:
    #   * an emptied list. "motion" there is OUR fallback, not the user
    #     saying "it was motion". Recording it as corrected_label would
    #     invent a positive example of a class nobody asserted.
    #   * the intermediate state of a two-tap correction. The label
    #     editor toggles one bubble per request, so changing cat→squirrel
    #     arrives as remove-cat then add-squirrel; booking the removal
    #     would file a spurious correction to whatever remained.
    #     Requiring a non-empty list means only the second tap counts.
    if labels and event["top_label"] != prev_top:
        _ledger_verdict(
            cam_id,
            event_id,
            correct=False,
            source="web",
            corrected_label=event["top_label"],
        )
    return jsonify(
        {
            "ok": True,
            "labels": labels,
            "top_label": event["top_label"],
            # cat_name/bird_species may just have been cleared by
            # apply_label_change() — the frontend needs both to drop a
            # stale identity chip without a full reload.
            "cat_name": event.get("cat_name"),
            "bird_species": event.get("bird_species"),
            # apply_label_change() also neutralized any per-detection row
            # that carried a disproven label — without handing the result
            # back, the player's object-list panel keeps reading its OWN
            # stale copy of whole_clip/detections until the next full
            # reload, and the heading a "Person raus editieren" tap was
            # just supposed to fix would still say "Person".
            "whole_clip": event.get("whole_clip"),
            "detections": event.get("detections"),
        }
    )


@bp.post('/api/camera/<cam_id>/events/<event_id>/species')
def api_event_species(cam_id, event_id):
    """Event-level bird species correction — the web analogue of the
    Telegram species picker (``telegram_bot._outbound._question.
    species_correction_markup`` builds the choices this endpoint answers
    a tap on; ``telegram_bot._inbound_event._cb_species_pick`` /
    ``_cb_species_unsure`` are the mutation this mirrors exactly).

    ONE ``bird_species`` PER EVENT — deliberately, not per detection row.
    See ``vplayer/panels/_objects-list.js``'s header for the three
    incompatible numbering schemes a per-row control would have to
    reconcile, and the fact that the verdict ledger is keyed by
    ``event_id`` alone.

    A picked species (``species`` a non-empty string) sets
    ``bird_species``, counts one more confirmed video for it
    (``species_video_count.record_confirmed_video`` — the same counter
    a Telegram "Ja"/species-pick feeds, so a class recorded from either
    surface is not double-counted or under-counted from the other), and
    books a ``correct=True`` verdict naming the species.

    ``species`` null/empty is "unsicher, welche genau" — mirrors
    ``_cb_species_unsure`` exactly: still confirms the class (a
    ``correct=True`` verdict, just with no species), leaves
    ``bird_species`` at whatever best-effort guess is already on the
    event (⁠``_cb_species_unsure`` never calls the Telegram path's
    ``_correct_bird_species`` either), and counts no video — a species
    the operator could not name must not inflate that species' cap.
    """
    store = app_state.store
    event = store.get_event(cam_id, event_id)
    if not event:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    raw = payload.get("species")
    species = raw.strip() if isinstance(raw, str) else None
    species = species or None
    if species:
        event["bird_species"] = species
        with contextlib.suppress(Exception):
            record_confirmed_video(app_state.storage_root, species)
    store.update_event(cam_id, event_id, event)
    _ledger_verdict(cam_id, event_id, correct=True, source="web", species=species)
    # Die Korrektur gibt einer Art einen Beleg und nimmt der vorher
    # eingetragenen genau diesen einen weg. Beides gehört ins Raster —
    # der Abgleich sieht ohnehin beide Seiten in einem Lauf.
    if species:
        _resync_species_board()
    return jsonify({"ok": True, "bird_species": event.get("bird_species")})


@bp.post('/api/camera/<cam_id>/review/<event_id>')
def api_camera_review(cam_id, event_id):
    payload = request.get_json(force=True, silent=True) or {}
    app_state.settings.set_review(f"{cam_id}:{event_id}", payload)
    return jsonify({"ok": True})
