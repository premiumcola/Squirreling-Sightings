"""Adopting clips whose producer died — the terminal transition nobody wrote.

``camera_runtime/_recording/_stages.py`` walks a clip
``recording → queued → encoding → ready``, and every one of those
transitions is written by the thread that is doing the work. So when
that thread stops existing — a container restart, an ffmpeg hang, a
power cut — the manifest keeps whatever stage it held at that moment
forever. ``annotate_stage`` then reports it stalled on every read and
the library renders "hängt · 5 h 51 min": honest about the symptom, but
``set_clip_stage`` is only ever called *forwards*, so nothing in the
codebase ever wrote the terminal state and there was no way out of it
except deleting the event by hand.

This module writes that missing transition, from the only two places
that can know the producer is gone:

* :func:`stamp_interrupted_clips` — on SIGTERM. Bounded to the last two
  day folders and to a handful of manifest rewrites, because Docker
  sends SIGKILL about ten seconds later and a running encode will not
  beat that clock. See the note in ``lifecycle.py``: this stamps, it
  does not drain.
* :func:`sweep_orphaned_clips` — at boot. Anything still in flight from
  *before this process started* is orphaned by definition: no thread in
  this process owns it.

Both halves share one vocabulary — :func:`needs_adoption`,
:data:`INTERRUPTED_AT`, :data:`INTERRUPTED_REASON_DE`.

Nothing is deleted. A stub carries detections, labels and often a
snapshot, so destroying records on every boot is not something to do
unasked. An adopted clip either becomes playable (:data:`STAGE_READY`,
which is a real recovery — ffmpeg often finished writing the mp4 before
the process died) or becomes honestly ``failed``. A failed clip with no
media on disk drops out of the grid, exactly like every other
media-less manifest, and is listed by the integrity report under
"Einträge ohne Medienverweis".
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from .camera_runtime._recording._stages import (
    STAGE_FAILED,
    STAGE_READY,
    STAGE_STATUS,
    is_pending,
    stage_age_s,
)
from .storage import _atomic_write_text, event_date_subdir

log = logging.getLogger(__name__)

#: "A process died on this clip and the next boot still has to decide
#: what became of it." Written by the shutdown stamp, cleared by the
#: boot sweep — which is what makes the sweep idempotent: after one
#: pass there are no candidates left for a second one.
INTERRUPTED_AT = "interrupted_at"

#: Operator-facing German, naming the real cause. ``_processing.js``
#: renders ``encode_error`` as the note on a failed tile.
INTERRUPTED_REASON_DE = (
    "Ein Neustart hat die Verarbeitung unterbrochen — das Video wurde nicht fertiggestellt."
)

#: How many day folders back the shutdown stamp looks. A clip in flight
#: is minutes old; two days covers a clip that spans midnight and keeps
#: the walk bounded to something that finishes inside Docker's stop
#: grace on an archive of any size.
_STAMP_DAYS = 2


def needs_adoption(event: dict) -> bool:
    """True when nothing is producing this clip any more.

    The one predicate both halves share. ``is_pending`` is the live
    case; ``interrupted_at`` is what the shutdown stamp left behind and
    it deliberately outlives that stamp's own ``failed``, so the next
    boot still gets to look for a finished mp4 next to the manifest
    before it believes the failure.
    """
    return bool(is_pending(event) or event.get(INTERRUPTED_AT))


def mark_interrupted(event: dict, now: datetime) -> bool:
    """Stamp one manifest "the process that owned this is gone".

    Terminal and honest immediately: the tile stops claiming work is
    happening. Returns True when the manifest actually changed, so a
    second signal costs no writes.
    """
    if event.get(INTERRUPTED_AT):
        return False
    event["stage"] = STAGE_FAILED
    event["status"] = STAGE_STATUS[STAGE_FAILED]
    event["stage_since"] = now.isoformat(timespec="seconds")
    event[INTERRUPTED_AT] = now.isoformat(timespec="seconds")
    event["encode_error"] = INTERRUPTED_REASON_DE
    return True


def _owned_by_this_process(event: dict, started_at: datetime) -> bool:
    """True while a thread in THIS process could still advance the clip.

    The boot sweep runs after ``rebuild_runtimes()`` has the cameras
    live, so a camera that fired motion two seconds ago already has a
    ``recording`` stub on disk and the sweep must not touch it. Age is
    measured against the process start with the same ``stage_age_s``
    the library uses: zero means the stamp is at or after boot, so it
    is ours; anything older was stamped by a process that no longer
    exists. A manifest with no parsable timestamp at all (``None``) is
    the permanently broken case and gets adopted.
    """
    if event.get(INTERRUPTED_AT):
        return False  # already known dead, whatever its clock says
    return stage_age_s(event, started_at) == 0


def _playable_clip(day_dir: Path, event_id: str) -> Optional[Path]:
    """The video an orphaned clip left behind, or ``None``.

    Both candidates are the ones the recorder itself publishes:
    ``<id>.mp4`` when the re-encode finished, ``<id>.raw.mp4`` when it
    did not — ``_reencode_motion_clip`` already falls back to the
    stream-copy on its own error path, so offering it here is that
    rule, not a new one.

    Validity is ``media_index.probe_container``: MIN_VIDEO_BYTES plus
    the ISO ``ftyp`` header, the archive's existing test for "is this
    an mp4 at all". It is a header check, not a decode — an encode
    killed after ffmpeg wrote ``ftyp`` but before it relocated the moov
    atom passes it and then shows up in the integrity report under
    "Keine echten Videos". A file the operator can inspect and delete
    still beats a tile that claims to be busy forever.
    """
    from .media_index import probe_container

    for name in (f"{event_id}.mp4", f"{event_id}.raw.mp4"):
        path = day_dir / name
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if probe_container(path, size) is None:
            return path
    return None


def _duration_s(video: Path) -> float:
    """Clip length in seconds, or 0.0 — the same frames/fps probe
    ``_reencode_motion_clip`` runs after a successful encode."""
    try:
        import cv2

        cap = cv2.VideoCapture(str(video))
        try:
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        finally:
            cap.release()
        return round(frames / fps, 2) if fps > 0 and frames > 0 else 0.0
    except Exception as e:
        log.debug("[migration] Dauer nicht messbar für %s: %s", video.name, e)
        return 0.0


def _recover(event: dict, event_id: str, video: Path, root: Path, public_base: str) -> None:
    """Point the manifest at the file that really is on disk and call it
    ready. The thumbnail comes from ``storage_scan.extract_thumb`` — the
    same middle-frame grab the media rescan uses — and only when the
    event has no usable snapshot yet."""
    from .storage_scan import extract_thumb, media_url

    rel = video.relative_to(root).as_posix()
    event["video_relpath"] = rel
    event["video_url"] = media_url(public_base, rel)
    event["file_size_bytes"] = video.stat().st_size
    event["duration_s"] = _duration_s(video)
    thumb = video.parent / f"{event_id}.jpg"
    if extract_thumb(video, thumb):
        thumb_rel = thumb.relative_to(root).as_posix()
        event["snapshot_relpath"] = thumb_rel
        event["snapshot_url"] = media_url(public_base, thumb_rel)
        event["thumb_url"] = event["snapshot_url"]
    event["stage"] = STAGE_READY
    event["status"] = STAGE_STATUS[STAGE_READY]
    event.pop("encode_error", None)


def _clip_dir(manifest: Path, event_id: str) -> Path:
    """Where this event's media lives. Normally the manifest's own date
    folder; for a legacy manifest still loose in the camera root the
    media is one level down, in the date folder its id names."""
    subdir = event_date_subdir(event_id)
    if subdir and (manifest.parent / subdir).is_dir():
        return manifest.parent / subdir
    return manifest.parent


def adopt_event(event: dict, manifest: Path, root: Path, public_base: str, now: datetime) -> str:
    """Give one orphaned clip its terminal state in place.

    Returns ``"recovered"`` or ``"failed"``. Clearing
    :data:`INTERRUPTED_AT` is what retires the event from the candidate
    set, so a second sweep finds nothing to do.
    """
    event_id = event.get("event_id") or manifest.stem
    video = _playable_clip(_clip_dir(manifest, event_id), event_id)
    event.pop(INTERRUPTED_AT, None)
    event["stage_since"] = now.isoformat(timespec="seconds")
    if video is None:
        event["stage"] = STAGE_FAILED
        event["status"] = STAGE_STATUS[STAGE_FAILED]
        event["encode_error"] = INTERRUPTED_REASON_DE
        return "failed"
    _recover(event, event_id, video, root, public_base)
    return "recovered"


def _load(path: Path) -> Optional[dict]:
    """Parsed manifest, or ``None`` with one warning. An unreadable file
    must never abort the sweep — it is the single most likely thing to
    be lying around after the crash we are cleaning up after."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("[migration] Ereignis-Manifest nicht lesbar: %s (%s)", path, e)
        return None
    return payload if isinstance(payload, dict) else None


def _write(path: Path, event: dict) -> None:
    """Atomic in-place manifest rewrite — the same writer ``EventStore``
    uses, so a crash during the sweep cannot tear a manifest in half."""
    if not path.exists():
        # `relocate_root_event_jsons` runs in a sibling boot thread and
        # may have moved this manifest into its date subfolder between
        # our read and this write. Recreating it here would mint a
        # duplicate; the next boot adopts it where it now lives.
        log.debug("[migration] Manifest während des Laufs verschoben: %s", path)
        return
    _atomic_write_text(path, json.dumps(event, ensure_ascii=False, indent=2))


def _camera_dirs(storage_root: Path) -> Iterator[Path]:
    events_root = storage_root / "motion_detection"
    if not events_root.is_dir():
        return
    for cam_dir in sorted(events_root.iterdir()):
        if cam_dir.is_dir():
            yield cam_dir


def _all_manifests(storage_root: Path) -> Iterator[Path]:
    """Every motion-event manifest, any depth. ``.tracks.json`` sidecars
    describe an existing event and are not events."""
    for cam_dir in _camera_dirs(storage_root):
        for path in sorted(cam_dir.rglob("*.json")):
            if not path.name.endswith(".tracks.json"):
                yield path


def _recent_manifests(storage_root: Path, now: datetime, days: int) -> Iterator[Path]:
    """Manifests from the last ``days`` day folders, plus whatever is
    still loose in a camera root. Bounded on purpose — the shutdown path
    has a SIGKILL behind it, so it may not rglob a full archive."""
    wanted = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(max(1, days))]
    for cam_dir in _camera_dirs(storage_root):
        for name in wanted:
            day_dir = cam_dir / name
            if day_dir.is_dir():
                yield from sorted(day_dir.glob("*.json"))
        for path in sorted(cam_dir.glob("*.json")):
            if not path.name.endswith(".tracks.json"):
                yield path


def sweep_orphaned_clips(
    storage_root, *, started_at: datetime, public_base: str = "", now: datetime = None
) -> dict:
    """Boot half: adopt every clip left in flight by a dead process.

    Returns ``{"recovered": n, "failed": n}``. Idempotent — the second
    run over the same tree finds no candidates and writes nothing.
    """
    root = Path(storage_root)
    now = now or datetime.now()
    result = {"recovered": 0, "failed": 0}
    for path in _all_manifests(root):
        event = _load(path)
        if event is None or not needs_adoption(event):
            continue
        if _owned_by_this_process(event, started_at):
            continue
        result[adopt_event(event, path, root, public_base, now)] += 1
        _write(path, event)
    return result


def stamp_interrupted_clips(storage_root, *, days: int = _STAMP_DAYS, now: datetime = None) -> int:
    """Shutdown half: stamp every in-flight clip interrupted. Returns how
    many manifests changed."""
    root = Path(storage_root)
    now = now or datetime.now()
    stamped = 0
    for path in _recent_manifests(root, now, days):
        event = _load(path)
        if event is None or not needs_adoption(event):
            continue
        if not mark_interrupted(event, now):
            continue
        _write(path, event)
        stamped += 1
    return stamped
