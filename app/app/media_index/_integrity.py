"""Read-only integrity report — "Integrität prüfen".

Deletes nothing, writes nothing, registers nothing — and, since the
report stopped reaching through ``store.list_events``, creates nothing
either: that path mkdir'd ``motion_detection/<id>/`` for every id it
inspected, so the second run reported a directory the first had
fabricated. Every finding is a diagnosis with the relative path
attached, so the operator decides what happens next. That restraint is
deliberate: three of the categories below (``roh_clips``,
``ereignis_ohne_verweis`` on a live recording, judged events past
retention) are files that must NOT be deleted, and an "alles bereinigen"
button next to them would be the next data-loss incident in a repo that
has already had one.

The whole pass is O(N) and each tree is walked ONCE: the per-camera
index is built a single time and handed to every section, including the
unclaimed-directory and unswept-tree summaries that used to re-walk it.
No ``rglob`` inside a loop anywhere. It still costs minutes on a large
archive — see ``routes/media.py``, which runs it on a background thread
rather than on the request worker.
"""

from __future__ import annotations

import json
from pathlib import Path

from ._scan import MEDIA_TREES, CameraIndex, camera_dirs_on_disk, scan_camera, tree_size_bytes
from ._timelapse import is_rolling_preview
from ._types import (
    MEDIA_NO_REF,
    MEDIA_OK,
    MEDIA_UNVERIFIED,
    MIN_VIDEO_BYTES,
    STATE_LABEL_DE,
    is_timelapse_event,
    media_state,
)
from ._visible import filter_visible

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
        for event_id, rels in sorted(index.media.items())
        if event_id not in known
        for rel in sorted(rels)
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


def _video_findings(storage_root: Path, index: CameraIndex) -> list:
    """ "Es muss ein echtes Video abliegen" — container check over every
    mp4 the walk saw.

    That is every walked tree, not just the two counted ones: the probe
    read ``index.sizes``, so restricting it meant "Keine echten Videos"
    never looked at ``weather/`` or ``adhoc_clips/`` although the report
    already charged the operator for their bytes.
    """
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


def _timelapse_findings(index: CameraIndex, manifests: dict) -> list:
    """The timelapse badge/grid reconciliation, plus the previews that
    are deliberately outside it."""
    registrierte_stems = {event_id[3:] for event_id in manifests if event_id.startswith("tl_")}
    # Rolling previews are ephemeral by design and never registered, so
    # they are not a gap — listing them under "Timelapse ohne Eintrag"
    # would make the report permanently red for working behaviour.
    tl_ohne_eintrag = [
        {"pfad": rel, "detail": f"{_mb(index.size_of(rel) or 0)} MB"}
        for stem, rel in sorted(index.tl_media.items())
        if stem not in registrierte_stems and not is_rolling_preview(stem)
    ]
    rolling = [
        {"pfad": rel, "detail": f"{_mb(index.size_of(rel) or 0)} MB"}
        for stem, rel in sorted(index.tl_media.items())
        if is_rolling_preview(stem)
    ]
    tl_ohne_video = [
        {"pfad": index.tl_manifests[f"tl_{stem}"], "detail": "MP4 fehlt"}
        for stem in sorted(registrierte_stems)
        if stem not in index.tl_media and f"tl_{stem}" in index.tl_manifests
    ]
    return [
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
            "rolling_vorschauen",
            "Rolling-Vorschauen",
            "„Letzte N Minuten“ — auf Knopfdruck gebaut und bewusst nicht im Archiv "
            "registriert. Sie liegen unter timelapse/ und werden von keiner "
            "Bereinigung erfasst; löschen entscheidest du.",
            rolling,
            schwere="info",
        ),
    ]


def build_camera_report(
    storage_root: Path, cam_id: str, name: str, aktiv: bool, index: CameraIndex = None
) -> dict:
    """Full per-camera report. One walk, one parse per manifest.

    ``index`` lets the caller hand in a walk it already did — the
    unclaimed-directory section builds the same index, and walking
    ``timelapse_frames`` ("potentially gigabytes of raw jpgs") three
    times for one report was most of its cost.
    """
    if index is None:
        index = scan_camera(storage_root, cam_id, trees=MEDIA_TREES)
    manifests = _load_manifests(storage_root, index)
    # The manifests are already parsed; running them back through
    # `store.list_events` parsed every one of them a second time.
    payloads = sorted(
        (p for p in manifests.values() if p),
        key=lambda p: p.get("time", ""),
        reverse=True,
    )
    visible = filter_visible(payloads, index.size_lookup(storage_root))
    grid_tl = sum(1 for ev in visible if is_timelapse_event(ev))
    grid_motion = len(visible) - grid_tl
    archiv_dateien = sum(1 for stem in index.tl_media if not is_rolling_preview(stem))
    befunde = (
        _media_findings(index, manifests)
        + _video_findings(storage_root, index)
        + _timelapse_findings(index, manifests)
    )
    return {
        "camera_id": cam_id,
        "name": name or cam_id,
        "aktiv": aktiv,
        # Rolling previews are never registered on purpose, so counting
        # their files here would report permanent drift for behaviour
        # that is working as designed. They get their own finding.
        "zaehler": {
            "ereignisse": grid_motion,
            "timelapse": grid_tl,
            "timelapse_dateien": archiv_dateien,
            "abweichung": archiv_dateien - grid_tl,
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


def _unclaimed_section(unclaimed: list) -> list:
    """Per-camera directories no configured camera claims — the check
    that answers "liegt bei Werkstatt vielleicht doch etwas ab?" without
    guessing at id shapes and without deleting anything.

    Takes the already-built ``(cam_id, trees, index)`` triples so no tree
    is walked a second time for the summary row."""
    return [
        {
            "camera_id": cam_id,
            "verzeichnisse": trees,
            "groesse_mb": _mb(sum(index.tree_bytes.values())),
            "dateien": len(index.sizes),
        }
        for cam_id, trees, index in unclaimed
    ]


#: Trees outside ``motion_detection/`` and who, if anyone, sweeps them.
_UNSWEPT_TREES = (
    ("timelapse", "nur manuell (Timelapse löschen)"),
    ("weather", "nur manuell (Wetter-Sichtung löschen)"),
    ("adhoc_clips", None),
    ("timelapse_frames", "Encode-Schleife nach dem Rendern"),
)


def _unswept_section(storage_root: Path, indexes: list) -> list:
    """Trees the nightly sweep never touches, with who (if anyone) owns
    them. Reported, never auto-deleted — see the module docstring.

    Byte totals come from the per-camera walks that already happened;
    only ``.trash`` (not a per-camera tree) needs a walk of its own."""
    per_tree: dict = {}
    for index in indexes:
        for tree, size in index.tree_bytes.items():
            per_tree[tree] = per_tree.get(tree, 0) + size
    out = []
    for tree, swept in _UNSWEPT_TREES:
        if not (storage_root / tree).is_dir():
            continue
        out.append({"pfad": tree, "groesse_mb": _mb(per_tree.get(tree, 0)), "gefegt_von": swept})
    if (storage_root / ".trash").is_dir():
        out.append(
            {
                "pfad": ".trash",
                "groesse_mb": _mb(tree_size_bytes(storage_root, ".trash")),
                "gefegt_von": "trash.cleanup_expired (täglich)",
            }
        )
    return out


def build_report(storage_root: Path, store, cameras: list) -> dict:
    """The whole ``/api/media/integrity`` payload.

    ``store`` is accepted for call-site compatibility and deliberately
    unused: reaching through it was what made this read-only report
    create directories.
    """
    del store
    configured = {c["id"] for c in cameras}
    indexes = {c["id"]: scan_camera(storage_root, c["id"], trees=MEDIA_TREES) for c in cameras}
    unclaimed = [
        (cam_id, trees, scan_camera(storage_root, cam_id, trees=MEDIA_TREES))
        for cam_id, trees in sorted(camera_dirs_on_disk(storage_root).items())
        if cam_id not in configured
    ]
    per_camera = [
        build_camera_report(
            storage_root, c["id"], c.get("name") or c["id"], True, index=indexes[c["id"]]
        )
        for c in cameras
    ]
    per_camera.extend(
        build_camera_report(storage_root, cam_id, cam_id, False, index=index)
        for cam_id, _trees, index in unclaimed
    )
    all_indexes = list(indexes.values()) + [index for _c, _t, index in unclaimed]
    return {
        "ok": True,
        "kameras": per_camera,
        "fremde_verzeichnisse": _unclaimed_section(unclaimed),
        "ungefegte_verzeichnisse": _unswept_section(storage_root, all_indexes),
    }
