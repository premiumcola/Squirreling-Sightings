"""Read-only integrity report — "Integrität prüfen".

Deletes nothing, writes nothing, registers nothing. Every finding is a
diagnosis with the relative path attached, so the operator decides what
happens next. That restraint is deliberate: three of the categories
below (``raw_reste``, ``ereignis_ohne_verweis`` on a live recording,
judged events past retention) are files that must NOT be deleted, and a
"alles bereinigen" button next to them would be the next data-loss
incident in a repo that has already had one.

The whole pass is O(N) — the walk from :mod:`._scan` plus one JSON parse
per manifest. No ``rglob`` inside a loop anywhere.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ._scan import MEDIA_TREES, CameraIndex, camera_dirs_on_disk, scan_camera, tree_size_bytes
from ._types import (
    MEDIA_NO_REF,
    MEDIA_OK,
    MEDIA_UNVERIFIED,
    MIN_VIDEO_BYTES,
    STATE_LABEL_DE,
    is_timelapse_event,
    media_state,
)
from ._visible import visible_media_events

log = logging.getLogger(__name__)

#: Findings are a diagnosis, not a work queue — a full listing of a
#: broken archive would be megabytes of JSON nobody reads.
MAX_ENTRIES = 50

#: ISO base media files start with a size field followed by ``ftyp``.
#: Checking those four bytes costs one 12-byte read and catches every
#: truncated / placeholder / not-actually-a-video file without decoding.
_FTYP_OFFSET = 4


def _mb(num_bytes: int) -> float:
    return round(num_bytes / 1024 / 1024, 1)


def _finding(code: str, titel: str, hinweis: str, eintraege: list, schwere: str = "warn") -> dict:
    return {
        "code": code,
        "titel": titel,
        "hinweis": hinweis,
        "schwere": schwere,
        "anzahl": len(eintraege),
        "gekuerzt": len(eintraege) > MAX_ENTRIES,
        "eintraege": eintraege[:MAX_ENTRIES],
    }


def probe_container(path: Path, size: int):
    """German reason why this mp4 is not a real video, or ``None``.

    Header check only — it proves the file is an MP4 container with a
    plausible size, not that every frame decodes. That is the honest
    limit of an O(1)-per-file check, and it already catches the 0-byte
    and half-written-encode cases the operator meant by "Fake-Dateien".
    """
    if size <= 0:
        return "0 Byte — leere Datei"
    if size < MIN_VIDEO_BYTES:
        return f"nur {size} Byte — abgeschnittene Aufnahme"
    try:
        with open(path, "rb") as handle:
            head = handle.read(12)
    except OSError as exc:
        return f"nicht lesbar ({exc.strerror or exc})"
    if len(head) < 12 or head[_FTYP_OFFSET : _FTYP_OFFSET + 4] != b"ftyp":
        return "kein MP4-Container (ftyp fehlt)"
    return None


def _load_manifests(storage_root: Path, index: CameraIndex) -> dict:
    """``event_id -> payload`` for every manifest, motion and timelapse.
    Unreadable files map to ``None`` so they get their own finding."""
    out: dict = {}
    for event_id, rel in list(index.manifests.items()) + list(index.tl_manifests.items()):
        try:
            payload = json.loads((storage_root / rel).read_text(encoding="utf-8"))
        except Exception:
            out[event_id] = None
            continue
        out[event_id] = payload if isinstance(payload, dict) else None
    return out


def _media_findings(index: CameraIndex, manifests: dict) -> list:
    """Findings derived purely from set arithmetic over the index."""
    ohne_medien, ohne_verweis, unlesbar = [], [], []
    for event_id, payload in manifests.items():
        rel = index.manifests.get(event_id) or index.tl_manifests.get(event_id)
        if payload is None:
            unlesbar.append({"pfad": rel, "detail": "JSON nicht lesbar"})
            continue
        state = media_state(payload, index.size_of)
        if state in (MEDIA_OK, MEDIA_UNVERIFIED):
            continue
        entry = {"pfad": rel, "detail": STATE_LABEL_DE.get(state, state)}
        (ohne_verweis if state == MEDIA_NO_REF else ohne_medien).append(entry)

    known = set(manifests)
    medien_ohne_eintrag = [
        {"pfad": rel, "detail": f"{_mb(index.size_of(rel) or 0)} MB"}
        for event_id, rel in sorted(index.media.items())
        if event_id not in known
    ]
    verwaist = [
        {"pfad": rel, "detail": "kein zugehöriges Ereignis"}
        for bucket in (index.tracks, index.best_frames)
        for event_id, rel in sorted(bucket.items())
        if event_id not in known
    ]
    return [
        _finding(
            "ereignis_ohne_medien",
            "Einträge ohne Datei",
            "Das Manifest verweist auf ein Video oder Bild, das nicht mehr auf der "
            "Platte liegt. Diese Einträge werden weder angezeigt noch gezählt.",
            ohne_medien,
        ),
        _finding(
            "ereignis_ohne_verweis",
            "Einträge ohne Medienverweis",
            "Manifest ohne Video- und Bildpfad — meist ein abgebrochener Aufnahme-Stub. "
            "Nicht löschen, solange eine Aufnahme laufen kann.",
            ohne_verweis,
            schwere="info",
        ),
        _finding(
            "manifest_unlesbar",
            "Beschädigte Manifeste",
            "JSON lässt sich nicht parsen.",
            unlesbar,
        ),
        _finding(
            "medien_ohne_eintrag",
            "Dateien ohne Eintrag",
            "Video oder Bild ohne Manifest — „Neu scannen“ registriert sie nach.",
            medien_ohne_eintrag,
        ),
        _finding(
            "verwaiste_zusatzdateien",
            "Verwaiste Zusatzdateien",
            "tracks.json / best.jpg ohne zugehöriges Ereignis.",
            verwaist,
            schwere="info",
        ),
    ]


def _video_findings(storage_root: Path, index: CameraIndex, manifests: dict) -> list:
    """ "Es muss ein echtes Video abliegen" — container check over every
    mp4 in both trees, plus the timelapse badge/grid reconciliation."""
    defekt = []
    for rel, size in sorted(index.sizes.items()):
        if not rel.endswith(".mp4"):
            continue
        grund = probe_container(storage_root / rel, size)
        if grund:
            defekt.append({"pfad": rel, "detail": grund})
    leer = [
        {"pfad": rel, "detail": "0 Byte"}
        for rel, size in sorted(index.sizes.items())
        if size == 0 and not rel.endswith(".mp4")
    ]
    registrierte_stems = {event_id[3:] for event_id in manifests if event_id.startswith("tl_")}
    tl_ohne_eintrag = [
        {"pfad": rel, "detail": f"{_mb(index.size_of(rel) or 0)} MB"}
        for stem, rel in sorted(index.tl_media.items())
        if stem not in registrierte_stems
    ]
    tl_ohne_video = [
        {"pfad": index.tl_manifests[f"tl_{stem}"], "detail": "MP4 fehlt"}
        for stem in sorted(registrierte_stems)
        if stem not in index.tl_media and f"tl_{stem}" in index.tl_manifests
    ]
    return [
        _finding(
            "defekte_videos",
            "Keine echten Videos",
            "Datei ist leer, abgeschnitten oder kein MP4-Container — nicht abspielbar. "
            "Geprüft wird der Container-Header, nicht jedes Einzelbild.",
            defekt,
        ),
        _finding(
            "leere_dateien",
            "Leere Dateien",
            "0 Byte auf der Platte.",
            leer,
        ),
        _finding(
            "timelapse_ohne_eintrag",
            "Timelapse ohne Eintrag",
            "MP4 liegt unter timelapse/, ist im Archiv aber nicht registriert — genau "
            "diese Lücke ließ die Kachel fehlen, während der Zähler mitzählte. "
            "„Neu scannen“ holt sie nach.",
            tl_ohne_eintrag,
        ),
        _finding(
            "timelapse_ohne_video",
            "Timelapse-Eintrag ohne Video",
            "Registrierte Timelapse, deren MP4 verschwunden ist.",
            tl_ohne_video,
        ),
        _finding(
            "roh_clips",
            "Roh-Clips (.raw.mp4)",
            "Zwischendatei der Aufnahme. Sie bleibt absichtlich liegen, wenn die "
            "Nachbearbeitung scheitert — dann ist sie die einzige Kopie. Niemals "
            "automatisch löschen.",
            [
                {"pfad": rel, "detail": f"{_mb(index.size_of(rel) or 0)} MB"}
                for rel in sorted(index.raws.values())
            ],
            schwere="info",
        ),
    ]


def build_camera_report(storage_root: Path, store, cam_id: str, name: str, aktiv: bool) -> dict:
    """Full per-camera report. One walk, one parse per manifest."""
    index = scan_camera(storage_root, cam_id, trees=MEDIA_TREES)
    manifests = _load_manifests(storage_root, index)
    visible = visible_media_events(store, index.size_of, cam_id)
    grid_tl = sum(1 for ev in visible if is_timelapse_event(ev))
    grid_motion = len(visible) - grid_tl
    befunde = _media_findings(index, manifests) + _video_findings(storage_root, index, manifests)
    return {
        "camera_id": cam_id,
        "name": name or cam_id,
        "aktiv": aktiv,
        "zaehler": {
            "ereignisse": grid_motion,
            "timelapse": grid_tl,
            "timelapse_dateien": len(index.tl_media),
            "abweichung": len(index.tl_media) - grid_tl,
        },
        "groessen": {
            "aufnahmen_mb": _mb(index.tree_bytes.get("motion_detection", 0)),
            "timelapse_mb": _mb(index.tree_bytes.get("timelapse", 0)),
            "timelapse_frames_mb": _mb(index.tree_bytes.get("timelapse_frames", 0)),
            "wetter_mb": _mb(index.tree_bytes.get("weather", 0)),
            "adhoc_mb": _mb(index.tree_bytes.get("adhoc_clips", 0)),
        },
        "befunde": [f for f in befunde if f["anzahl"]],
    }


def _unclaimed_section(storage_root: Path, configured: set) -> list:
    """Per-camera directories no configured camera claims — the check
    that answers "liegt bei Werkstatt vielleicht doch etwas ab?" without
    guessing at id shapes and without deleting anything."""
    out = []
    for cam_id, trees in sorted(camera_dirs_on_disk(storage_root).items()):
        if cam_id in configured:
            continue
        index = scan_camera(storage_root, cam_id, trees=MEDIA_TREES)
        total = sum(index.tree_bytes.values())
        out.append(
            {
                "camera_id": cam_id,
                "verzeichnisse": trees,
                "groesse_mb": _mb(total),
                "dateien": len(index.sizes),
            }
        )
    return out


def _unswept_section(storage_root: Path) -> list:
    """Trees the nightly sweep never touches, with who (if anyone) owns
    them. Reported, never auto-deleted — see the module docstring."""
    rows = [
        ("timelapse", "nur manuell (Timelapse löschen)"),
        ("weather", "nur manuell (Wetter-Sichtung löschen)"),
        ("adhoc_clips", None),
        ("timelapse_frames", "Encode-Schleife nach dem Rendern"),
        (".trash", "trash.cleanup_expired (täglich)"),
    ]
    out = []
    for tree, swept in rows:
        root = storage_root / tree
        if not root.is_dir():
            continue
        out.append(
            {
                "pfad": tree,
                "groesse_mb": _mb(tree_size_bytes(storage_root, tree)),
                "gefegt_von": swept,
            }
        )
    return out


def build_report(storage_root: Path, store, cameras: list) -> dict:
    """The whole ``GET /api/media/integrity`` payload."""
    configured = {c["id"] for c in cameras}
    per_camera = [
        build_camera_report(storage_root, store, c["id"], c.get("name") or c["id"], True)
        for c in cameras
    ]
    unclaimed = _unclaimed_section(storage_root, configured)
    for row in unclaimed:
        per_camera.append(
            build_camera_report(storage_root, store, row["camera_id"], row["camera_id"], False)
        )
    return {
        "ok": True,
        "kameras": per_camera,
        "fremde_verzeichnisse": unclaimed,
        "ungefegte_verzeichnisse": _unswept_section(storage_root),
    }
