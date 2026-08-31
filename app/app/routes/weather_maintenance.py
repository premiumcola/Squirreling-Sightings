"""Weather archive maintenance — rescan + bulk thumb regeneration.

Own module for the same reason as ``routes/weather_episodes.py`` and
``routes/weather_pin.py``: ``routes/weather.py`` was 746 lines against
a 500-line ceiling, and these two POST routes are an offline repair
concern rather than part of the live sighting pipeline. Nothing here
runs on the request path a user hits while browsing — both endpoints
walk the whole weather tree and are triggered by hand from the UI.

The manifest-synthesis helpers live here too because rescan is their
only caller. The thumb extractor itself stays in ``weather.py``: the
sighting-thumb route regenerates on demand as well, and a second copy
of the lock would defeat the serialisation it exists for.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

import cv2
from flask import Blueprint, jsonify

from .. import app_state
from .weather import _regenerate_weather_thumb, _weather_thumb_regen_lock

bp = Blueprint("weather_maintenance", __name__)

log = logging.getLogger(__name__)


# Canonical on-disk phase directory names. Walked in this order so
# orphan-mp4 synthesis prefers the per-phase folders introduced by
# the boot-time `migrate_sun_timelapse_layout` over the legacy shared
# "sun_timelapse/" dir. `event_timelapse/` is where _event_tl.py
# writes thunder/front/storm captures.
_WEATHER_PHASE_DIRS: tuple[str, ...] = (
    "sunrise_timelapse",
    "sunset_timelapse",
    "sun_timelapse",
    "event_timelapse",
)


def _cam_name_lookup(cam_id: str) -> str:
    """Resolve the display name for a camera id via settings_store.
    Falls back to cam_id when the camera isn't found (e.g. removed but
    media still on disk)."""
    try:
        store = app_state.store
        if store is None:
            return cam_id
        cams = (store.export_effective_config() or {}).get("cameras") or []
        for c in cams:
            if (c.get("id") or "") == cam_id:
                return c.get("name") or cam_id
    except Exception:
        pass
    return cam_id


def _phase_from_dir_and_stem(phase_dir: str, stem: str) -> tuple[str, str]:
    """Return (sun_phase, phase_suffix) inferred from the on-disk
    directory name and the filename stem. `phase_suffix` is "rise" or
    "set" (used in the canonical sighting id); `sun_phase` is the
    legacy "sunrise"/"sunset" string carried inside the manifest body.
    For event_timelapse/ both return empty strings — the caller treats
    those manifests separately."""
    if phase_dir == "sunrise_timelapse":
        return ("sunrise", "rise")
    if phase_dir == "sunset_timelapse":
        return ("sunset", "set")
    if phase_dir == "sun_timelapse":
        s = stem.lower()
        if "sunrise" in s or s.endswith("_rise"):
            return ("sunrise", "rise")
        if "sunset" in s or s.endswith("_set"):
            return ("sunset", "set")
        return ("sunrise", "rise")
    return ("", "")


def _synth_sun_manifest(cam_id: str, phase_dir: str, mp4_path: Path) -> dict:
    """Build a minimal sun-timelapse manifest from a found mp4 file.
    Used by rescan to register orphans — fields the live capture path
    fills (api_snapshot, sun_snapshot, fps) get sensible defaults."""
    stem = mp4_path.stem
    sun_phase, phase_suffix = _phase_from_dir_and_stem(phase_dir, stem)
    st = mp4_path.stat()
    started = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
    width = height = 0
    duration_s = 0
    try:
        cap = cv2.VideoCapture(str(mp4_path))
        if cap.isOpened():
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if fps > 0 and n > 0:
                duration_s = max(1, int(round(n / fps)))
            cap.release()
    except Exception:
        pass
    rel = f"weather/{cam_id}/{phase_dir}/{mp4_path.name}"
    thumb_rel = rel[: -len(".mp4")] + ".jpg"
    return {
        "id": f"{cam_id}__sun_timelapse_{phase_suffix}__{stem}",
        "cam_id": cam_id,
        "cam_name": _cam_name_lookup(cam_id),
        "event_type": "sun_timelapse",
        "sun_phase": sun_phase,
        "is_test": False,
        "started_at": started,
        "score": 0.6,
        "severity": 0.6,
        "window_min": 0,
        "window_seconds": 0,
        "interval_s": 0,
        "fps": 0,
        "api_snapshot": {},
        "clip_path": rel,
        "thumb_path": thumb_rel,
        "duration_s": duration_s,
        "file_size_bytes": st.st_size,
        "width": width,
        "height": height,
        "rescanned": True,
    }


def _synth_event_manifest(cam_id: str, mp4_path: Path) -> dict:
    """Minimal manifest for an orphan event_timelapse mp4."""
    stem = mp4_path.stem
    st = mp4_path.stat()
    started = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
    rel = f"weather/{cam_id}/event_timelapse/{mp4_path.name}"
    thumb_rel = rel[: -len(".mp4")] + ".jpg"
    return {
        "id": f"{cam_id}__event_timelapse__{stem}",
        "cam_id": cam_id,
        "cam_name": _cam_name_lookup(cam_id),
        "event_type": "event_timelapse",
        "is_test": False,
        "started_at": started,
        "score": 0.5,
        "severity": 0.5,
        "clip_path": rel,
        "thumb_path": thumb_rel,
        "file_size_bytes": st.st_size,
        "rescanned": True,
    }


def _atomic_write_json(path: Path, data: dict) -> None:
    """Same-directory tempfile + os.replace so a concurrent reader
    never sees a half-written manifest. Mirrors the helper in
    _consts.py without importing across packages."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _weather_root() -> Path | None:
    """Return `<storage_root>/weather` (the same dir the WeatherService
    writes into). Returns None when storage isn't configured yet."""
    sr = app_state.storage_root
    if sr is None:
        return None
    return Path(sr) / "weather"


@bp.post('/api/weather/rescan')
def api_weather_rescan():
    """Walk every weather cam dir + phase dir, synthesize manifest
    JSONs for orphan mp4s, regenerate any thumb that's missing while
    its clip is present, and mark manifests whose clip vanished. Safe
    to run repeatedly — orphans are detected by "mp4 with no matching
    .json"; manifests already on disk are left untouched (only their
    thumbs may be regenerated)."""
    root = _weather_root()
    if root is None or not root.exists():
        return jsonify(
            {
                "ok": True,
                "registered": 0,
                "missing": 0,
                "thumbs_regen": 0,
                "scanned": 0,
                "errors": 0,
                "note": "no weather storage root",
            }
        )
    registered = missing = thumbs_regen = scanned = errors = 0
    for cam_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if cam_dir.name.startswith(".") or cam_dir.name == "recaps":
            continue
        cam_id = cam_dir.name
        for phase in _WEATHER_PHASE_DIRS:
            phase_dir = cam_dir / phase
            if not phase_dir.exists() or not phase_dir.is_dir():
                continue
            mp4_stems: set[str] = set()
            json_stems: set[str] = set()
            for f in phase_dir.iterdir():
                if f.name.startswith("."):
                    continue
                if f.suffix == ".mp4":
                    mp4_stems.add(f.stem)
                elif f.suffix == ".json":
                    json_stems.add(f.stem)
                scanned += 1
            # Orphan mp4 → synthesize manifest.
            for stem in sorted(mp4_stems - json_stems):
                mp4_path = phase_dir / f"{stem}.mp4"
                try:
                    if phase == "event_timelapse":
                        m = _synth_event_manifest(cam_id, mp4_path)
                    else:
                        m = _synth_sun_manifest(cam_id, phase, mp4_path)
                    _atomic_write_json(phase_dir / f"{stem}.json", m)
                    registered += 1
                    log.info(
                        "[weather] rescan: registered orphan mp4 %s/%s/%s",
                        cam_id,
                        phase,
                        mp4_path.name,
                    )
                except Exception as e:
                    errors += 1
                    log.warning(
                        "[weather] rescan: synth manifest failed for %s/%s/%s: %s",
                        cam_id,
                        phase,
                        mp4_path.name,
                        e,
                    )
            # Manifest whose clip vanished → tag missing (don't delete —
            # the user may want to inspect or recover from backup).
            for stem in sorted(json_stems - mp4_stems):
                j_path = phase_dir / f"{stem}.json"
                try:
                    data = json.loads(j_path.read_text(encoding="utf-8"))
                    if not data.get("missing_clip"):
                        data["missing_clip"] = True
                        _atomic_write_json(j_path, data)
                        missing += 1
                        log.info(
                            "[weather] rescan: marked missing-clip %s/%s/%s",
                            cam_id,
                            phase,
                            j_path.name,
                        )
                except Exception as e:
                    errors += 1
                    log.warning("[weather] rescan: missing-clip mark failed %s: %s", j_path, e)
            # Thumb regen for every clip whose thumb is gone — covers
            # both newly registered orphans and pre-existing manifests
            # that lost their thumb (e.g. user-deleted jpgs).
            for stem in sorted(mp4_stems):
                jpg = phase_dir / f"{stem}.jpg"
                if jpg.exists():
                    continue
                mp4 = phase_dir / f"{stem}.mp4"
                if not mp4.exists():
                    continue
                with _weather_thumb_regen_lock:
                    if jpg.exists():
                        continue
                    if _regenerate_weather_thumb(mp4, jpg):
                        thumbs_regen += 1
                    else:
                        errors += 1
    return jsonify(
        {
            "ok": True,
            "registered": registered,
            "missing": missing,
            "thumbs_regen": thumbs_regen,
            "scanned": scanned,
            "errors": errors,
        }
    )


@bp.post('/api/weather/thumbs/regen')
def api_weather_thumbs_regen():
    """Force-rebuild every weather thumb whose clip exists. Used when
    a codec change or model rebuild has left the existing thumbs
    looking stale and the user wants a fresh middle-frame extract
    for the whole collection. Idempotent — overwriting an existing
    JPEG with a fresh decode is harmless."""
    root = _weather_root()
    if root is None or not root.exists():
        return jsonify(
            {
                "ok": True,
                "regenerated": 0,
                "skipped": 0,
                "errors": 0,
                "note": "no weather storage root",
            }
        )
    regenerated = skipped = errors = 0
    for cam_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if cam_dir.name.startswith(".") or cam_dir.name == "recaps":
            continue
        for phase in _WEATHER_PHASE_DIRS:
            phase_dir = cam_dir / phase
            if not phase_dir.exists() or not phase_dir.is_dir():
                continue
            for mp4 in sorted(phase_dir.glob("*.mp4")):
                if mp4.name.startswith("."):
                    continue
                jpg = phase_dir / (mp4.stem + ".jpg")
                with _weather_thumb_regen_lock:
                    if _regenerate_weather_thumb(mp4, jpg):
                        regenerated += 1
                    else:
                        errors += 1
            # Count orphan thumbs (no matching clip) — surfaced as
            # `skipped` in the response so the user knows there's
            # something to clean up, but we don't auto-delete because
            # the rescan endpoint is the right tool for re-pairing.
            for jpg in sorted(phase_dir.glob("*.jpg")):
                if jpg.name.startswith("."):
                    continue
                if not (phase_dir / (jpg.stem + ".mp4")).exists():
                    skipped += 1
    return jsonify(
        {
            "ok": True,
            "regenerated": regenerated,
            "skipped": skipped,
            "errors": errors,
        }
    )
