"""Weather sightings, sun-times, recaps, status, history.

Migrated from server.py during R01.5. Every route reads
`app_state.weather_service` fresh — `rebuild_services` may replace
the instance after a settings save.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import cv2
from flask import Blueprint, Response, jsonify, request, send_from_directory

from .. import app_state

#: Upper bound for ?page_size on the sightings list. The gallery asks
#: for everything so its multi-select chips can filter client-side;
#: this keeps "everything" from meaning an unbounded response.
MAX_SIGHTINGS_PAGE_SIZE = 500

bp = Blueprint("weather", __name__)

log = logging.getLogger(__name__)


# Serializes thumb-regen across parallel requests for the same sighting.
# A single global lock is overkill but the operation is rare (only fires
# when a thumb file is genuinely missing) and a per-path lock map would
# add bookkeeping for no measurable win.
_weather_thumb_regen_lock = threading.Lock()


def _regenerate_weather_thumb(clip_path: Path, thumb_path: Path) -> bool:
    """Extract a frame from roughly the middle of `clip_path` and write
    it as JPEG to `thumb_path` via temp-file + atomic rename. Returns
    True on success. cv2 is the same backend the original thumb writer
    uses so no new dependency."""
    try:
        cap = cv2.VideoCapture(str(clip_path))
        if not cap.isOpened():
            return False
        try:
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if n > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n // 2))
            ok, frame = cap.read()
            if (not ok or frame is None) and n > 0:
                # Some codecs misreport frame count — first frame always
                # decodes if the file is otherwise valid.
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
            if not ok or frame is None:
                return False
            ok2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if not ok2:
                return False
        finally:
            cap.release()
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        # Same-directory tempfile keeps the rename filesystem-local so
        # parallel readers never see a half-written JPEG.
        tmp = thumb_path.with_name(f".{thumb_path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
        tmp.write_bytes(buf.tobytes())
        os.replace(str(tmp), str(thumb_path))
        return True
    except Exception as e:
        log.warning("[weather] thumb regen exception: %s", e)
        return False


@bp.get('/api/weather/sightings')
def api_weather_sightings():
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"items": [], "counts": {}, "total": 0, "page": 0, "page_size": 50})
    # Flask's type=int parser swallows non-int values into None;
    # the explicit `or 0` matches the prior try/except default.
    page = request.args.get('page', type=int, default=0) or 0
    # The gallery filters client-side over a multi-select chip row, so it
    # needs the WHOLE list, not one page. It never sent a page_size and the
    # server defaulted to 50 while reporting `counts` over everything — so
    # the chips said "Starkregen 3" and the grid showed nothing, because
    # all three sat below the 50 newest of 86. Bounded, not unbounded: a
    # very large library must not become one enormous response.
    page_size = request.args.get('page_size', type=int, default=0) or 0
    page_size = min(max(page_size, 1), MAX_SIGHTINGS_PAGE_SIZE) if page_size else 50
    result = ws.list_sightings(
        cam_id=request.args.get('cam_id') or None,
        event_type=request.args.get('event_type') or None,
        since_iso=request.args.get('from') or None,
        until_iso=request.args.get('to') or None,
        page=page,
        page_size=page_size,
    )
    # Additive: stat each clip so the gallery card can render a size badge
    # (mirrors the Mediathek media-card's file_size_bytes). Never writes.
    for it in result.get("items") or []:
        _attach_clip_size(it)
    return jsonify(result)


@bp.get('/api/weather/sightings/<sighting_id>')
def api_weather_sighting_get(sighting_id: str):
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"error": "weather service not available"}), 503
    m = ws.get_sighting(sighting_id)
    if not m:
        return jsonify({"error": "not found"}), 404
    _attach_clip_size(m)
    return jsonify(m)


def _tolerant_resolve(stored_full: Path, storage_root: Path, ext: str) -> Path | None:
    """When the path stored in a manifest no longer matches what's on
    disk (cam-slug suffix migration renamed files post-write), look for
    any file in the same directory that shares the stem prefix up to
    the date. Returns a Path that exists and lives inside storage_root,
    or None when nothing matches. `ext` is the lowercase extension
    without leading dot (e.g. "mp4", "jpg")."""
    parent = stored_full.parent
    if not parent.exists():
        return None
    stem = stored_full.stem
    # The cam-slug migration appends an underscore + slug to the stem,
    # so the historical prefix is still a prefix of the new name.
    # Glob on `<stem>*.<ext>` covers both directions (stored name has
    # the slug but disk doesn't, or vice versa — fall back to any file
    # whose stem starts with the date portion before the first slug
    # underscore).
    candidates = list(parent.glob(f"{stem}*.{ext}"))
    if not candidates:
        # Try the date-prefix path: split on first "_sunrise"/"_sunset"
        # token because that's the stable part of every sun-tl name.
        for token in ("_sunrise", "_sunset"):
            if token in stem:
                prefix = stem.split(token, 1)[0] + token
                candidates = list(parent.glob(f"{prefix}*.{ext}"))
                if candidates:
                    break
    if not candidates:
        return None
    # Prefer an exact-stem match when present, otherwise pick the
    # shortest filename (most likely the original, un-suffixed one).
    candidates.sort(key=lambda p: (p.stem != stem, len(p.name)))
    picked = candidates[0]
    try:
        if not str(picked.resolve()).startswith(str(storage_root.resolve())):
            return None
    except (OSError, RuntimeError):
        return None
    return picked


def _attach_clip_size(item: dict) -> None:
    """Stat the sighting's mp4 and attach ``file_size_bytes`` (additive,
    in bytes) so the gallery card can render a size badge mirroring the
    Mediathek media-card. Best-effort + read-only — any failure leaves the
    field absent and the card omits the size line. Uses the same tolerant
    same-dir glob as the clip route so legacy manifests whose stored path
    drifted after the cam-slug migration still resolve to a real file."""
    storage_root = app_state.storage_root
    rel = item.get("clip_path") or ""
    if storage_root is None or not rel:
        return
    try:
        full = storage_root / rel
        if not full.exists():
            alt = _tolerant_resolve(full, storage_root, "mp4")
            if alt is None:
                return
            full = alt
        item["file_size_bytes"] = full.stat().st_size
    except (OSError, RuntimeError):
        return


@bp.get('/api/weather/sightings/<sighting_id>/clip')
def api_weather_sighting_clip(sighting_id: str):
    ws = app_state.weather_service
    storage_root = app_state.storage_root
    if ws is None:
        return Response(status=503)
    m = ws.get_sighting(sighting_id)
    if not m:
        return Response(status=404)
    rel = m.get("clip_path", "")
    full = storage_root / rel
    try:
        if not str(full.resolve()).startswith(str(storage_root.resolve())):
            return Response(status=404)
    except (OSError, RuntimeError):
        return Response(status=404)
    if not full.exists():
        # Stored path 404s — legacy manifests still point at the
        # pre-rename filename. Try a tolerant same-dir glob before
        # giving up so the user doesn't see a broken card.
        alt = _tolerant_resolve(full, storage_root, "mp4")
        if alt is None:
            log.warning("[weather] clip 404 — %s missing for %s", rel, sighting_id)
            return Response(status=404)
        log.info("[weather] clip resolved via fallback glob: %s → %s", rel, alt.name)
        full = alt
    return send_from_directory(full.parent, full.name, mimetype='video/mp4')


@bp.get('/api/weather/sightings/<sighting_id>/thumb')
def api_weather_sighting_thumb(sighting_id: str):
    ws = app_state.weather_service
    storage_root = app_state.storage_root
    if ws is None:
        return Response(status=503)
    m = ws.get_sighting(sighting_id)
    if not m:
        return Response(status=404)
    rel = m.get("thumb_path", "")
    full = storage_root / rel
    try:
        if not str(full.resolve()).startswith(str(storage_root.resolve())):
            return Response(status=404)
    except (OSError, RuntimeError):
        return Response(status=404)
    if not full.exists():
        # First try a tolerant same-dir glob — legacy manifests still
        # point at pre-rename filenames after the cam-slug migration.
        alt = _tolerant_resolve(full, storage_root, "jpg")
        if alt is not None:
            log.info("[weather] thumb resolved via fallback glob: %s → %s", rel, alt.name)
            full = alt
    if not full.exists():
        # Thumb JPG still missing — try to regenerate from the clip
        # before giving up. Both-missing is the only true 404 case.
        clip_rel = m.get("clip_path", "")
        clip_full = (storage_root / clip_rel) if clip_rel else None
        if clip_full and not clip_full.exists():
            alt_clip = _tolerant_resolve(clip_full, storage_root, "mp4")
            if alt_clip is not None:
                clip_full = alt_clip
        if not clip_full or not clip_full.exists():
            log.warning("[weather] thumb 404 — clip and thumb both missing for %s", sighting_id)
            return Response(status=404)
        with _weather_thumb_regen_lock:
            # Re-check inside the lock — another request may have won.
            if not full.exists():
                if not _regenerate_weather_thumb(clip_full, full):
                    log.warning("[weather] thumb regen failed for %s", sighting_id)
                    return Response(status=404)
                log.info("[weather] thumb regenerated for %s", sighting_id)
    return send_from_directory(full.parent, full.name, mimetype='image/jpeg')


@bp.delete('/api/weather/sightings/<sighting_id>')
def api_weather_sighting_delete(sighting_id: str):
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"error": "weather service not available"}), 503
    if ws.delete_sighting(sighting_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@bp.get('/api/weather/sun-times')
def api_weather_sun_times():
    """Today's sunrise/sunset for the configured location, plus per-camera
    sun-timelapse window previews. Powers the live preview row in
    Settings → Wetter."""
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"location_set": False, "sunrise": None, "sunset": None, "cameras": []})
    return jsonify(ws.sun_times_today())


@bp.get('/api/weather/recaps')
def api_weather_recaps():
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"items": []})
    return jsonify({"items": ws.list_recaps()})


@bp.get('/api/weather/recaps/<recap_id>/clip')
def api_weather_recap_clip(recap_id: str):
    ws = app_state.weather_service
    storage_root = app_state.storage_root
    if ws is None:
        return Response(status=503)
    m = ws.get_recap(recap_id)
    if not m:
        return Response(status=404)
    full = storage_root / m.get("clip_path", "")
    if not full.exists() or not str(full.resolve()).startswith(str(storage_root.resolve())):
        return Response(status=404)
    return send_from_directory(full.parent, full.name, mimetype='video/mp4')


@bp.get('/api/weather/status')
def api_weather_status():
    ws = app_state.weather_service
    if ws is None:
        return jsonify(
            {
                "enabled": False,
                "last_poll_at": None,
                "last_api_ok": None,
                "current_state": {},
                "current_values": {},
                "location": {"lat": None, "lon": None},
            }
        )
    return jsonify(ws.status())


@bp.get('/api/weather/history')
def api_weather_history():
    """Backing endpoint for the Wetterstatistik chart. `hours` clamped
    to 1..720 by the service (30 d at default 5-min poll). Returns a
    sample list, per-field thresholds drawn from the configured event
    triggers, units, German labels, and the configured poll interval.

    `since`/`until` (ISO timestamps) are additive optional params: when
    given they replace the `hours` cutoff with an explicit absolute
    window — used to replay a saved manual event's exact range, which
    may no longer fall inside "the last N hours from now". Every
    existing caller that only sends `hours` is unaffected."""
    ws = app_state.weather_service
    if ws is None:
        return jsonify(
            {
                "hours": 24,
                "samples": [],
                "thresholds": {},
                "units": {},
                "labels_de": {},
                "fields": [],
                "poll_interval_s": 300,
                "extent": {"oldest": None, "newest": None, "count": 0},
            }
        )
    hours = request.args.get("hours", type=int, default=24) or 24
    since_iso = request.args.get("since") or None
    until_iso = request.args.get("until") or None
    return jsonify(ws.history(hours, since_iso=since_iso, until_iso=until_iso))
