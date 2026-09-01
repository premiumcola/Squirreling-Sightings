"""Retroactive bird-species classification for already-archived events.

The live pipeline (camera_runtime/_main_loop.py) only ever attempts
BirdSpeciesClassifier once per detection per frame, at capture time. An
event whose classifier crop failed then — model not yet installed,
classifier momentarily unavailable, low-confidence miss — carries
`bird_species: null` forever, and nothing revisits it. The operator's
own framing: since the bounding box is already known, classification
doesn't have to be live — it can run as a bounded, non-realtime sweep
over the archive.

Two triggers call into this module (see maintenance.py and
routes/sichtungen.py):
  * a bounded per-tick sweep piggybacked on the existing daily-cleanup
    timer (maintenance.py::_run_daily_cleanup) — passive catch-up,
    costs one boolean check when the classifier is unavailable.
  * a manual "Vogelarten nachträglich bestimmen" trigger
    (POST /api/bird-species/backfill), mirroring routes/tracking.py's
    reindex-all button, for an operator who just installed the model
    and doesn't want to wait for the next daily tick.

Persistence reuses the same read-modify-write pattern every other
retroactive stamp in this codebase already uses (see
tracking_worker/_achievement.py::update_event_achievement): read the
event, mutate only the fields this pass owns, write the whole object
back via EventStore.update_event. Only already-archived (finalized)
events are touched — the live loop never revisits a closed event once
recorded, so there is no writer to race with.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

#: Candidate events examined per automatic daily-sweep call. Bounded so
#: a large archive never turns one maintenance tick into a multi-minute
#: scan — mirrors weather_episodes/_consts.py::FOOTAGE_BACKFILL_PER_SWEEP,
#: scaled up because this sweep runs once a day rather than every 5 min.
DEFAULT_SWEEP_BUDGET = 50

#: Budget for the operator-triggered manual pass — generous, since the
#: operator explicitly asked for it and is watching the response.
MANUAL_BACKFILL_BUDGET = 500


def dossier_hook_for(bird_dossiers_svc) -> Callable[[str, str | None, str, str], None] | None:
    """Adapt an (optional) BirdDossierService into the `dossier_hook`
    shape `sweep_bird_species_backfill` expects — `on_new_species`'s
    own signature already matches it exactly, so this only exists to
    give both call sites (maintenance.py's daily sweep, routes/
    sichtungen.py's manual trigger) one shared None-guard instead of
    two copies of the same three-line check."""
    return bird_dossiers_svc.on_new_species if bird_dossiers_svc is not None else None


def build_backfill_classifier(effective_cfg: dict):
    """Instantiate BirdSpeciesClassifier from `processing.bird_species`
    the same way the archive-facing paths already do — see
    routes/_coral_pipeline.py::build_classifiers_for_mode's `bird_eff`
    pattern. Unlike that test-panel helper, `enabled` is NOT forced on:
    an operator who switched bird classification off does not want a
    background sweep quietly running inference anyway."""
    from .detectors import BirdSpeciesClassifier

    bird_cfg = (effective_cfg.get("processing") or {}).get("bird_species") or {}
    return BirdSpeciesClassifier(dict(bird_cfg))


def _needs_backfill(event: dict) -> bool:
    """An event is a backfill candidate when it carries no top-level
    `bird_species` yet AND at least one bird detection is missing its
    per-detection `species`. Mirrors the aggregate
    camera_runtime/_motion.py::_build_event_meta computes live:
    `next(d.species for d in detections if d.label == "bird" and d.species)`.

    Idempotency guard: an event that already has `bird_species` is
    never reconsidered, even if a later bird detection in the same
    event is still unclassified — the field exists, the dossier/quest
    readers already have something to show.
    """
    if event.get("bird_species"):
        return False
    dets = event.get("detections") or []
    return any(d.get("label") == "bird" and not d.get("species") for d in dets)


def _crop_bbox(frame: np.ndarray, bbox: dict) -> np.ndarray | None:
    """Crop `bbox` (an event JSON detection's x1/y1/x2/y2 dict) out of
    `frame`.

    Detection bboxes are stamped in the ORIGINAL capture-resolution
    pixel space — detectors/_types.py::Detection.to_dict emits the raw
    proc_frame coordinates, never resized (detect_setup.py::
    apply_bottom_crop only truncates rows, it never rescales). The
    recorded video preserves that same resolution — ffmpeg records
    with `-c copy` (camera_runtime/_recording/__init__.py), no `-vf
    scale`. The archived snapshot JPEG does NOT: _loop_stages.py::
    _write_snapshot_jpeg downscales to max width 1280 whenever the
    native frame is wider. A bbox that overshoots the frame we loaded
    means we picked a downscaled snapshot for an event whose native
    resolution was wider than 1280 — cropping it anyway would silently
    classify the wrong patch of the image, so this refuses instead of
    guessing a scale factor no stored field gives us.
    """
    if frame is None or not bbox:
        return None
    h, w = frame.shape[:2]
    try:
        x1 = int(bbox.get("x1", 0))
        y1 = int(bbox.get("y1", 0))
        x2 = int(bbox.get("x2", 0))
        y2 = int(bbox.get("y2", 0))
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    # +2 px tolerance for rounding at the exact frame edge.
    if x2 > w + 2 or y2 > h + 2:
        return None
    x1c, y1c = max(0, x1), max(0, y1)
    x2c, y2c = min(w, x2), min(h, y2)
    crop = frame[y1c:y2c, x1c:x2c]
    return crop if crop.size > 0 else None


def _first_video_frame(video_path: Path) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def load_frame_for_event(storage_root: Path, event: dict) -> np.ndarray | None:
    """Best available frame for re-cropping: the recorded video's first
    frame when there is one (native resolution, matches bbox space
    exactly), else the archived snapshot JPEG (may be downscaled —
    `_crop_bbox` refuses a bbox that no longer fits)."""
    video_rel = event.get("video_relpath")
    if video_rel:
        vid_path = Path(storage_root) / video_rel
        if vid_path.exists():
            frame = _first_video_frame(vid_path)
            if frame is not None:
                return frame
    snap_rel = event.get("snapshot_relpath")
    if snap_rel:
        snap_path = Path(storage_root) / snap_rel
        if snap_path.exists():
            frame = cv2.imread(str(snap_path))
            if frame is not None:
                return frame
    return None


def backfill_event_species(
    event: dict,
    classifier,
    frame_loader: Callable[[dict], np.ndarray | None],
) -> bool:
    """Stamp species onto every bird detection in `event` missing one,
    and recompute the event-level `bird_species` aggregate. Mutates
    `event` in place. Returns True when anything changed.

    Never raises — a missing file, an unreadable video, a corrupt crop,
    or a classifier exception all degrade to "leave it unset, log a
    warning, move on" so a caller sweeping many events never has one
    bad file abort the rest of the pass.
    """
    if not _needs_backfill(event):
        return False
    if classifier is None or not getattr(classifier, "available", False):
        return False

    event_id = event.get("event_id")
    dets = event.get("detections") or []
    bird_dets = [d for d in dets if d.get("label") == "bird" and not d.get("species")]
    if not bird_dets:
        return False

    try:
        frame = frame_loader(event)
    except Exception as e:
        log.warning("[det] bird backfill: frame load failed for event=%s: %s", event_id, e)
        return False
    if frame is None:
        log.warning("[det] bird backfill: no usable frame for event=%s", event_id)
        return False

    stamped_any = False
    for d in bird_dets:
        crop = _crop_bbox(frame, d.get("bbox") or {})
        if crop is None:
            log.warning(
                "[det] bird backfill: bbox unusable for event=%s (empty crop or "
                "resolution mismatch against the loaded frame)",
                event_id,
            )
            continue
        try:
            species, species_latin, species_score = classifier.classify_crop(crop)
        except Exception as e:
            log.warning("[det] bird backfill: classify failed for event=%s: %s", event_id, e)
            continue
        if not species:
            continue
        d["species"] = species
        d["species_latin"] = species_latin
        d["species_score"] = round(float(species_score), 4) if species_score is not None else None
        stamped_any = True

    if not stamped_any:
        return False

    # Same aggregate rule the live path uses: first bird detection (in
    # stored order) that carries a species.
    event["bird_species"] = next(
        (d.get("species") for d in dets if d.get("label") == "bird" and d.get("species")), None
    )
    return True


def find_backfill_candidates(
    store, cam_ids: list[str] | None = None
) -> Iterator[tuple[str, str, dict]]:
    """Yield (camera_id, event_id, event_dict) for every archived event
    under `store.events_dir` that `_needs_backfill`. Mirrors
    routes/tracking.py::api_tracking_reindex_all's directory walk —
    same tree, same `.tracks.json` sidecar skip."""
    events_dir = getattr(store, "events_dir", None)
    if events_dir is None:
        return
    events_dir = Path(events_dir)
    if not events_dir.exists():
        return
    if cam_ids:
        cam_dirs = [events_dir / cid for cid in cam_ids if (events_dir / cid).exists()]
    else:
        cam_dirs = [d for d in events_dir.iterdir() if d.is_dir()]
    for cam_dir in cam_dirs:
        camera_id = cam_dir.name
        for jf in cam_dir.rglob("*.json"):
            if jf.name.endswith(".tracks.json"):
                continue
            try:
                event = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as e:
                log.debug("[det] bird backfill: skip malformed %s: %s", jf, e)
                continue
            if not _needs_backfill(event):
                continue
            yield camera_id, event.get("event_id") or jf.stem, event


def _run_dossier_hook(dossier_hook, event: dict, event_id: str, camera_id: str) -> None:
    """Fire `dossier_hook(latin, common_de, event_id, camera_id)` once
    per distinct species_latin newly present on `event` — mirrors
    camera_runtime/_recording/_publish.py::_publish_dossiers's own
    per-event dedupe."""
    seen_latin: set[str] = set()
    for det in event.get("detections") or []:
        latin = (det.get("species_latin") or "").strip()
        if not latin or latin in seen_latin:
            continue
        seen_latin.add(latin)
        try:
            dossier_hook(latin, det.get("species") or None, event_id, camera_id)
        except Exception as e:
            log.debug("[det] bird backfill: dossier hook failed for %s: %s", event_id, e)


def sweep_bird_species_backfill(
    store,
    storage_root: Path,
    classifier,
    cam_ids: list[str] | None = None,
    *,
    budget: int = DEFAULT_SWEEP_BUDGET,
    dossier_hook: Callable[[str, str | None, str, str], None] | None = None,
) -> dict:
    """Bounded catch-up pass over the archive.

    Examines at most `budget` candidate events per call — the hard
    bound that keeps one maintenance tick from turning into a scan of
    the whole archive, mirroring weather_episodes/_archive.py::
    _stamp_footage's per-sweep cap. Unlike that precedent, a single
    event's failure never ends the batch here — only a globally
    unavailable classifier does, checked once up front so an
    unavailable model costs one attribute read rather than a walk of
    the archive to discover it does nothing.

    `dossier_hook(latin, common_de, event_id, camera_id)`, when given,
    is called once per newly-stamped species per event — mirrors
    camera_runtime/_recording/_publish.py::_publish_dossiers, so a
    backfilled species actually grows the Vogel-Dossiers field guide
    instead of only updating the raw event JSON.
    """
    if classifier is None or not getattr(classifier, "available", False):
        return {"examined": 0, "changed": 0, "reason": "classifier_unavailable"}

    def frame_loader(ev: dict) -> np.ndarray | None:
        return load_frame_for_event(storage_root, ev)

    examined = 0
    changed = 0
    for camera_id, event_id, event in find_backfill_candidates(store, cam_ids):
        if examined >= budget:
            break
        examined += 1
        try:
            did_change = backfill_event_species(event, classifier, frame_loader)
        except Exception as e:
            log.warning("[det] bird backfill: event=%s errored, skipping: %s", event_id, e)
            did_change = False
        if not did_change:
            continue
        try:
            store.update_event(camera_id, event_id, event)
        except Exception as e:
            log.warning("[det] bird backfill: write failed for event=%s: %s", event_id, e)
            continue
        changed += 1
        if dossier_hook:
            _run_dossier_hook(dossier_hook, event, event_id, camera_id)
    return {"examined": examined, "changed": changed}
