"""The single media-existence test.

Before this module there were four independent answers to "does this
event have media": ``EventStore._filter_events(media_only=True)``,
``routes/media._has_media_file``, the badge path's ``snap_exists /
media_exists`` pair, and ``glob("*.mp4")``. Three of them tested only
that a *string* was non-empty; the fourth tested only that a *file
name* existed. None of them tested that the file had bytes in it, which
is how a 0-byte encode kept being counted as a clip.

Everything now routes through :func:`media_state`. A caller supplies a
``size_of(relpath) -> int | None`` lookup — backed by the filesystem for
one-off checks, or by an already-built index for a full sweep — so the
rule is stated once and the cost model stays the caller's choice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

#: An mp4 smaller than this cannot hold a moov atom plus a single coded
#: frame — it is a truncated encode, a placeholder, or a crash residue,
#: never something the operator can play. Deliberately generous: real
#: timelapse and motion clips are hundreds of KiB upwards.
MIN_VIDEO_BYTES = 1024

MEDIA_OK = "ok"
#: Only a URL, no relpath — legacy/remote reference we cannot stat.
#: Stays visible (hiding it would lose real archive entries) but is
#: listed in the integrity report so it can be repaired.
MEDIA_UNVERIFIED = "unverified"
MEDIA_NO_REF = "no_ref"
MEDIA_MISSING_VIDEO = "missing_video"
MEDIA_EMPTY_VIDEO = "empty_video"
MEDIA_MISSING_SNAPSHOT = "missing_snapshot"
MEDIA_EMPTY_SNAPSHOT = "empty_snapshot"

#: States that may produce a tile AND a badge count. Everything else is
#: excluded from both and surfaced in the integrity report instead —
#: silently hiding a broken entry is how the archive started lying.
VISIBLE_STATES = frozenset({MEDIA_OK, MEDIA_UNVERIFIED})

STATE_LABEL_DE = {
    MEDIA_OK: "in Ordnung",
    MEDIA_UNVERIFIED: "nur URL hinterlegt, keine Datei prüfbar",
    MEDIA_NO_REF: "kein Medienverweis im Manifest",
    MEDIA_MISSING_VIDEO: "Video fehlt auf der Platte",
    MEDIA_EMPTY_VIDEO: "Video ist leer oder abgeschnitten",
    MEDIA_MISSING_SNAPSHOT: "Bild fehlt auf der Platte",
    MEDIA_EMPTY_SNAPSHOT: "Bild ist leer",
}

SizeLookup = Callable[[str], Optional[int]]


def size_lookup_fs(storage_root: Path) -> SizeLookup:
    """``size_of`` backed by the filesystem — one ``stat`` per call.

    For single events (the grid path) that is cheaper than building an
    index; for a full sweep use :class:`~._scan.CameraIndex.size_of`,
    which answers from the walk that already happened.
    """

    def _size_of(relpath: str) -> Optional[int]:
        try:
            return (storage_root / relpath).stat().st_size
        except OSError:
            return None

    return _size_of


def media_state(event: dict, size_of: SizeLookup) -> str:
    """Classify what an event manifest actually points at.

    The video reference wins when present: an event that declares a clip
    must have that clip. A surviving thumbnail next to a deleted mp4 is
    exactly the "tile promises a video that is not there" case the
    operator hit, so it does NOT rescue the event.
    """
    vid_rel = event.get("video_relpath")
    if vid_rel:
        size = size_of(vid_rel)
        if size is None:
            return MEDIA_MISSING_VIDEO
        if size < MIN_VIDEO_BYTES:
            return MEDIA_EMPTY_VIDEO
        return MEDIA_OK
    snap_rel = event.get("snapshot_relpath")
    if snap_rel:
        size = size_of(snap_rel)
        if size is None:
            return MEDIA_MISSING_SNAPSHOT
        if size <= 0:
            return MEDIA_EMPTY_SNAPSHOT
        return MEDIA_OK
    if event.get("video_url") or event.get("snapshot_url"):
        return MEDIA_UNVERIFIED
    return MEDIA_NO_REF


def has_real_media(event: dict, size_of: SizeLookup) -> bool:
    """True when the event may appear in the grid and in the badges."""
    return media_state(event, size_of) in VISIBLE_STATES


def is_timelapse_event(event: dict) -> bool:
    """Timelapse entries are counted under their own badge, never as
    motion. ``type`` is what the writers set; the label check catches
    manifests written before ``type`` existed."""
    if event.get("type") == "timelapse":
        return True
    return "timelapse" in (event.get("labels") or [])
