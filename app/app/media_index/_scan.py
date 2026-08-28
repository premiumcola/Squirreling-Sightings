"""One O(N) walk per camera, classified once.

``purge_orphans`` is the cautionary tale this module is written against:
it runs a full ``rglob`` *inside* a per-file loop, twice, which is why a
rescan blocks a Flask worker for seconds. Here every directory entry is
visited exactly once, sorted into name-keyed dicts, and every later
question ("is there a manifest for this mp4", "how big is that file")
is answered by a dict lookup — no filesystem access inside any loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ._types import size_lookup_fs

#: Trees that hold per-camera media. ``motion_detection`` and
#: ``timelapse`` are the two the Mediathek counts; the other three are
#: walked for their size only, because nothing in the UI shows them and
#: the operator has no way of knowing they are growing.
MEDIA_TREES = (
    "motion_detection",
    "timelapse",
    "timelapse_frames",
    "weather",
    "adhoc_clips",
)

#: The trees whose bytes the Mediathek camera card reports.
COUNTED_TREES = ("motion_detection", "timelapse")

_MEDIA_SUFFIXES = (".jpg", ".jpeg", ".mp4")


@dataclass
class CameraIndex:
    """Everything one camera owns on disk, classified by file name.

    Keys are event ids / timelapse stems; values are storage-relative
    posix paths, so they compare directly against the ``*_relpath``
    fields inside the event manifests.
    """

    camera_id: str
    sizes: dict = field(default_factory=dict)  # relpath -> bytes
    manifests: dict = field(default_factory=dict)  # event_id -> relpath
    tl_manifests: dict = field(default_factory=dict)  # tl_<stem> -> relpath
    tracks: dict = field(default_factory=dict)  # event_id -> relpath
    best_frames: dict = field(default_factory=dict)  # event_id -> relpath
    raws: dict = field(default_factory=dict)  # event_id -> relpath
    media: dict = field(default_factory=dict)  # event_id -> [relpath, …]
    tl_media: dict = field(default_factory=dict)  # stem -> relpath
    tl_sidecars: dict = field(default_factory=dict)  # stem -> relpath
    tree_bytes: dict = field(default_factory=dict)  # tree name -> bytes

    def size_of(self, relpath: str):
        """``SizeLookup`` answered from the walk — no stat, no I/O."""
        return self.sizes.get(relpath)

    def size_lookup(self, storage_root: Path):
        """``size_of`` with one ``stat`` for anything outside the walk.

        The badge route answered from the index and the grid route
        stat()ed the whole tree, so the two agreed only as long as no
        manifest pointed outside the walked trees — a single event whose
        clip lives under ``weather/`` would have produced a tile the
        badge did not count. Both routes take this lookup, so the
        fallback is part of the shared answer rather than one route's
        private generosity.
        """
        fs = size_lookup_fs(storage_root)

        def _size_of(relpath: str):
            size = self.sizes.get(relpath)
            return fs(relpath) if size is None else size

        return _size_of

    @property
    def counted_bytes(self) -> int:
        return sum(self.tree_bytes.get(t, 0) for t in COUNTED_TREES)

    @property
    def media_files(self) -> list:
        """Every media relpath under ``motion_detection/``, sorted."""
        return sorted(rel for rels in self.media.values() for rel in rels)

    @property
    def media_file_count(self) -> int:
        return sum(len(rels) for rels in self.media.values())


def _walk_sizes(root: Path, storage_root: Path) -> dict:
    """``relpath -> size`` for every file under ``root``. One pass."""
    out: dict = {}
    if not root.is_dir():
        return out
    for dirpath, _dirnames, filenames in os.walk(str(root)):
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            try:
                rel = path.relative_to(storage_root).as_posix()
            except ValueError:
                continue
            out[rel] = size
    return out


def _classify_motion(rel: str, index: CameraIndex) -> None:
    """Sort one file under ``motion_detection/<cam>/`` into its bucket.

    Order matters: ``<id>.tracks.json`` and ``<id>.best.jpg`` have to be
    recognised before the generic ``.json`` / ``.jpg`` rules, otherwise a
    sidecar is counted as an event — the defect that made ``stats_range``
    report twice the events it had.
    """
    name = PurePosixPath(rel).name
    if name.endswith(".tracks.json"):
        index.tracks[name[: -len(".tracks.json")]] = rel
        return
    if name.endswith(".best.jpg"):
        index.best_frames[name[: -len(".best.jpg")]] = rel
        return
    if name.endswith(".raw.mp4"):
        index.raws[name[: -len(".raw.mp4")]] = rel
        return
    if name.endswith(".json"):
        stem = name[: -len(".json")]
        if stem.startswith("tl_"):
            index.tl_manifests[stem] = rel
        else:
            index.manifests[stem] = rel
        return
    lower = name.lower()
    for suffix in _MEDIA_SUFFIXES:
        if lower.endswith(suffix):
            # A list, not a single relpath: `<id>.jpg` and `<id>.mp4`
            # share a stem, so keying one per stem lost a file — the
            # camera card reported 1 media file for a 2-file event, and
            # the same undercount decided whether an archived camera was
            # listed at all.
            index.media.setdefault(name[: -len(suffix)], []).append(rel)
            return


def _classify_timelapse(rel: str, index: CameraIndex) -> None:
    """Sort one file under ``timelapse/<cam>/``. Only the mp4s and their
    metadata sidecars matter; thumbnails and QA files ride along in
    ``sizes`` for the MB figure."""
    name = PurePosixPath(rel).name
    if name.endswith(".mp4"):
        index.tl_media[name[: -len(".mp4")]] = rel
    elif name.endswith(".json") and not name.endswith(".qa.json"):
        index.tl_sidecars[name[: -len(".json")]] = rel


def scan_camera(storage_root: Path, camera_id: str, trees=COUNTED_TREES) -> CameraIndex:
    """Build the on-disk picture for one camera.

    ``motion_detection/<cam>`` and ``timelapse/<cam>`` are walked fully
    and classified; any other tree in ``trees`` contributes its sizes
    without classification. The default deliberately excludes
    ``timelapse_frames`` (potentially gigabytes of raw jpgs) so the
    dashboard's per-load stats call stays cheap — the integrity check
    passes :data:`MEDIA_TREES` to see the whole disk.

    ``sizes`` covers every walked tree, not just the two counted ones.
    The mp4 container probe reads that dict, so restricting it meant
    "Keine echten Videos" never looked at ``weather/`` or
    ``adhoc_clips/`` even though the report already charged the operator
    for their bytes.
    """
    index = CameraIndex(camera_id=camera_id)
    for tree in trees:
        sizes = _walk_sizes(storage_root / tree / camera_id, storage_root)
        index.tree_bytes[tree] = sum(sizes.values())
        index.sizes.update(sizes)
        if tree == "motion_detection":
            for rel in sizes:
                _classify_motion(rel, index)
        elif tree == "timelapse":
            for rel in sizes:
                _classify_timelapse(rel, index)
    return index


def camera_dirs_on_disk(storage_root: Path) -> dict:
    """``camera_id -> [tree, …]`` for every per-camera directory found in
    any media tree. Used to answer "is there anything on disk that no
    configured camera claims" — the Werkstatt question — without
    guessing at id shapes."""
    found: dict = {}
    for tree in MEDIA_TREES:
        root = storage_root / tree
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir():
                found.setdefault(entry.name, []).append(tree)
    return found


def tree_size_bytes(storage_root: Path, tree: str) -> int:
    """Total bytes of a whole storage tree (all cameras)."""
    return sum(_walk_sizes(storage_root / tree, storage_root).values())
