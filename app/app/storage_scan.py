"""Register media files that have no event manifest — "Neu scannen".

Carved out of ``EventStore.scan_media_files`` (132 lines against an
80-line ceiling, inside a 772-line file against a 500-line ceiling).
The rules it encodes are unchanged:

* ``<id>.raw.mp4`` (the ffmpeg stream-copy intermediate) and
  ``<id>.best.jpg`` (the Telegram best-frame cache) belong to an event
  that already exists — registering them minted a ghost motion event
  per incident on every click.
* An mp4 below :data:`~.media_index.MIN_VIDEO_BYTES` is a crashed
  encode, not a clip. It is skipped, not registered as a tile that
  plays nothing.
* Everything under ``<day>/scrub/`` (filmstrips) and ``<day>/crops/``
  (person portraits) belongs to a clip rather than being one — see
  :func:`is_derived_media` for the ghost cards that cost.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .person_crops import CROP_DIR
from .scrub_sprite import SPRITE_DIR

log = logging.getLogger(__name__)

_MEDIA_SUFFIXES = (".jpg", ".jpeg", ".mp4")

#: Companions of an existing event. Their stems (``<id>.raw`` /
#: ``<id>.best``) never match an event id, so without this guard the
#: scan invents a second event for every clip it already knows.
_COMPANION_SUFFIXES = (".raw.mp4", ".best.jpg")

#: Directories holding files DERIVED from a clip rather than clips of
#: their own: the scrub filmstrip and the person crops. Both are named
#: after the event they belong to, so only the directory tells them apart
#: from a real snapshot — and a scan that walks into one invents a ghost
#: event per file. That has happened once already, with the filmstrip.
_DERIVED_DIRS = {SPRITE_DIR, CROP_DIR}


def media_url(base: str, relpath: str) -> str:
    """The ``/media/...`` URL for a storage-relative path. Public because
    :mod:`app.app.clip_recovery` republishes recovered clips and has to
    spell the URL exactly the way the recorder does."""
    return f"{base}/media/{relpath}" if base else f"/media/{relpath}"


def extract_thumb(video: Path, thumb: Path) -> bool:
    """Grab a middle frame so the freshly registered card has a preview.
    Returns True when ``thumb`` exists afterwards.

    Shared with :mod:`app.app.clip_recovery`, which needs a thumbnail
    for exactly the same reason: a clip that just gained a manifest
    entry and has no preview yet."""
    if thumb.exists():
        return True
    try:
        import cv2

        cap = cv2.VideoCapture(str(video))
        try:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total > 2:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok or frame is None:
            return False
        return bool(cv2.imwrite(str(thumb), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85]))
    except Exception as e:
        log.debug("[MediaScan] thumb extract failed for %s: %s", video.name, e)
        return False


def _build_event(store_root: Path, cam_id: str, media_file: Path, base: str) -> dict:
    """The synthetic manifest for one unregistered media file."""
    event_id = media_file.stem
    try:
        ts = datetime.strptime(event_id[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        ts = datetime.now()
    rel = media_file.relative_to(store_root).as_posix()
    event: dict = {
        "event_id": event_id,
        "camera_id": cam_id,
        "camera_name": cam_id,
        "time": ts.isoformat(timespec="seconds"),
        "labels": ["motion"],
        "top_label": "motion",
        "alarm_level": "info",
        "armed": True,
        "after_hours": False,
        "scanned": True,
    }
    if media_file.suffix.lower() != ".mp4":
        event["snapshot_relpath"] = rel
        event["snapshot_url"] = media_url(base, rel)
        event["video_url"] = None
        return event
    event["video_relpath"] = rel
    event["video_url"] = media_url(base, rel)
    event["snapshot_relpath"] = None
    event["snapshot_url"] = None
    thumb = media_file.with_suffix(".jpg")
    if extract_thumb(media_file, thumb):
        thumb_rel = thumb.relative_to(store_root).as_posix()
        event["snapshot_relpath"] = thumb_rel
        event["snapshot_url"] = media_url(base, thumb_rel)
    return event


def is_derived_media(media_file: Path) -> bool:
    """True for a file that BELONGS to an event rather than being one.

    Two shapes, one rule. The suffix companions (``<id>.raw.mp4`` /
    ``<id>.best.jpg``) sit beside the clip and are caught by name. The
    derived IMAGES sit one directory down — the scrub filmstrip in
    ``<day>/scrub/``, the person portraits in ``<day>/crops/`` — and are
    caught by that directory, because their FILE NAMES are
    indistinguishable from a real snapshot: same event id, same ``.jpg``.

    That indistinguishability is the whole bug. The scan walks the tree
    with ``rglob``, so it descended into ``scrub/`` and found a ``.jpg``
    whose stem no manifest claimed — the manifest having been deleted,
    trashed or aged out, while nothing has ever deleted the sprite — and
    dutifully registered it as a brand-new snapshot-only motion event.
    The card then rendered the sprite full-bleed: a contact sheet of
    forty postage stamps of the same frame, dated, with no duration and
    no size, and impossible to get rid of because the next scan invented
    it again. „Das sind diese gestapelten Bilder. Das sollte grundsätzlich
    nicht passieren."

    ``scrub_sprite.py``'s own docstring already argued that a separate
    directory was the safe place to put these ("a directory they do not
    walk cannot be got wrong"). This is the walk that did.
    """
    if media_file.name.endswith(_COMPANION_SUFFIXES):
        return True
    return bool(_DERIVED_DIRS & set(Path(media_file).parts))


def _candidates(cam_dir: Path, existing_ids: set) -> list:
    """Media files under ``cam_dir`` (any depth) with no manifest yet."""
    from .media_index import MIN_VIDEO_BYTES

    out = []
    files: list = []
    for pattern in ("*.jpg", "*.jpeg", "*.mp4"):
        files.extend(cam_dir.rglob(pattern))
    for media_file in sorted(files):
        if media_file.suffix.lower() not in _MEDIA_SUFFIXES:
            continue
        if is_derived_media(media_file):
            continue
        if media_file.stem in existing_ids:
            continue
        if media_file.suffix.lower() == ".mp4":
            try:
                if media_file.stat().st_size < MIN_VIDEO_BYTES:
                    log.warning(
                        "[MediaScan] %s ist kein abspielbares Video — übersprungen",
                        media_file.name,
                    )
                    continue
            except OSError:
                continue
        out.append(media_file)
    return out


def scan_media_files(store, camera_ids, public_base_url: str = "") -> int:
    """Register every unclaimed ``.jpg`` / ``.mp4`` under
    ``motion_detection/<cam>/`` as an event. Returns how many were added.

    ``media_index`` is imported inside :func:`_candidates` rather than at
    module scope: it reaches ``camera_runtime``, which reaches back into
    ``storage``. At call time every module is loaded, so the deferred
    import keeps the module graph acyclic while still using the ONE
    definition of "big enough to be a video".
    """
    base = (public_base_url or "").rstrip("/")
    scanned = 0
    for cam_id in camera_ids:
        cam_dir = store.camera_dir(cam_id)
        log.info("[MediaScan] checking cam_dir: %s exists=%s", cam_dir, cam_dir.exists())
        if not cam_dir.is_dir():
            continue
        existing_ids = {jf.stem for jf in cam_dir.rglob("*.json")}
        for media_file in _candidates(cam_dir, existing_ids):
            store.add_event(cam_id, _build_event(store.root, cam_id, media_file, base))
            existing_ids.add(media_file.stem)
            scanned += 1
    log.info("[MediaScan] %d neue Medien-Events registriert", scanned)
    orphans = store.purge_orphans()
    if orphans:
        log.info("[MediaScan] %d verwaiste Events bereinigt", orphans)
    return scanned
