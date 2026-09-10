"""Der Filmstreifen ist kein Ereignis.

„Das sind diese gestapelten Bilder. Für die Thumbs werden in der
Mediathek angezeigt. Das sollte grundsätzlich nicht passieren."

Auf einer Karte lag ein Kontaktbogen: dasselbe Kamerabild vierzig Mal in
einem Raster, mit Datum, ohne Länge, ohne Größe, nicht abspielbar. Das
war der Filmstreifen des Abspielbalkens, und er stand dort, weil er
einem Schnappschuss zum Verwechseln ähnlich sieht — dieselbe
Ereignis-ID, dieselbe Endung, nur ein Verzeichnis tiefer. Der
„Neu scannen"-Lauf ging mit `rglob` durch den ganzen Baum, fand ihn ohne
Manifest (weil das Manifest gelöscht, im Papierkorb oder ausgelaufen war
— den Filmstreifen hat nie jemand mitgenommen) und trug ihn als neues
Bewegungsereignis ein.

Der Kreis schloss sich selbst: ab dann existierte ein Manifest, dessen
„Schnappschuss" wirklich auf der Platte liegt, also ließ auch
`purge_orphans` die Karte stehen. Drei Riegel, hier je einer:

* der Lauf steigt nicht mehr in den Ordner (`is_derived_media`),
* das Löschen nimmt den Filmstreifen mit, statt ihn zur Waise zu machen,
* und die Karten, die schon da sind, räumt ein einmaliger Lauf weg.
"""

from __future__ import annotations

import json

from app.migrations_scrub import purge_scrub_ghost_events
from app.scrub_sprite import SPRITE_DIR
from app.storage import EventStore
from app.storage_scan import is_derived_media


def _clip(root, cam="cam_a", day="2026-09-05", eid="20260905-143900-000"):
    """Ein Clip mit allem, was zu ihm gehört — inklusive Filmstreifen."""
    d = root / "motion_detection" / cam / day
    (d / SPRITE_DIR).mkdir(parents=True, exist_ok=True)
    (d / f"{eid}.mp4").write_bytes(b"x" * 4096)
    (d / f"{eid}.jpg").write_bytes(b"snap")
    (d / SPRITE_DIR / f"{eid}.jpg").write_bytes(b"sheet")
    (d / f"{eid}.json").write_text(
        json.dumps(
            {
                "event_id": eid,
                "camera_id": cam,
                "labels": ["motion"],
                "video_relpath": f"motion_detection/{cam}/{day}/{eid}.mp4",
                "snapshot_relpath": f"motion_detection/{cam}/{day}/{eid}.jpg",
            }
        ),
        encoding="utf-8",
    )
    return d, eid


# ── Riegel 1: der Lauf steigt nicht in den Ordner ───────────────────────


def test_der_filmstreifen_ist_abgeleitete_datei_kein_fund(tmp_path):
    d, eid = _clip(tmp_path)
    assert is_derived_media(d / SPRITE_DIR / f"{eid}.jpg") is True
    # Die beiden schon bekannten Begleiter bleiben erkannt…
    assert is_derived_media(d / f"{eid}.raw.mp4") is True
    assert is_derived_media(d / f"{eid}.best.jpg") is True
    # …und ein echter Schnappschuss NICHT. Er heißt genauso wie der
    # Filmstreifen; nur das Verzeichnis unterscheidet die beiden.
    assert is_derived_media(d / f"{eid}.jpg") is False
    assert is_derived_media(d / f"{eid}.mp4") is False


def test_neu_scannen_traegt_den_filmstreifen_nicht_als_ereignis_ein(tmp_path):
    d, eid = _clip(tmp_path)
    # Der gemessene Zustand: das Manifest ist weg, der Filmstreifen liegt
    # noch da. Genau so entsteht die Geisterkarte.
    (d / f"{eid}.json").unlink()
    (d / f"{eid}.mp4").unlink()
    (d / f"{eid}.jpg").unlink()
    store = EventStore(str(tmp_path))

    added = store.scan_media_files([d.parent.parent.name])

    assert added == 0, "ein Filmstreifen ist kein Ereignis"
    assert list((tmp_path / "motion_detection").rglob("*.json")) == []
    # Und er liegt noch da: er gehört seinem Clip, nicht diesem Lauf.
    assert (d / SPRITE_DIR / f"{eid}.jpg").exists()


def test_ein_echter_unbeanspruchter_schnappschuss_wird_weiter_eingetragen(tmp_path):
    """Die Gegenprobe: der Riegel darf nicht einfach alle .jpg
    aussperren, sonst nimmt er dem Lauf seine eigentliche Aufgabe."""
    d, eid = _clip(tmp_path)
    (d / f"{eid}.json").unlink()
    (d / f"{eid}.mp4").unlink()
    store = EventStore(str(tmp_path))

    assert store.scan_media_files(["cam_a"]) == 1
    written = json.loads((d / f"{eid}.json").read_text(encoding="utf-8"))
    assert SPRITE_DIR not in written["snapshot_relpath"]


# ── Riegel 2: gelöscht heißt auch der Filmstreifen ──────────────────────


def test_loeschen_nimmt_den_filmstreifen_mit(tmp_path):
    d, eid = _clip(tmp_path)
    store = EventStore(str(tmp_path))

    store.delete_event("cam_a", eid)

    assert not (
        d / SPRITE_DIR / f"{eid}.jpg"
    ).exists(), "ein überlebender Filmstreifen ist die Geisterkarte von morgen"
    assert not (d / f"{eid}.mp4").exists()
    assert not (d / f"{eid}.json").exists()


def test_der_filmstreifen_geht_auch_ohne_lesbares_manifest(tmp_path):
    """Er hängt nicht am Inhalt des Manifests: liegt das kaputt auf der
    Platte, wird der Clip trotzdem gelöscht — und der Filmstreifen darf
    dann erst recht nicht zurückbleiben."""
    d, eid = _clip(tmp_path)
    (d / f"{eid}.json").write_text("{kaputt", encoding="utf-8")
    store = EventStore(str(tmp_path))

    store.delete_event("cam_a", eid)

    assert not (d / SPRITE_DIR / f"{eid}.jpg").exists()


# ── Riegel 3: was schon auf der Platte liegt ────────────────────────────


def test_der_einmallauf_raeumt_die_geisterkarten_weg(tmp_path):
    d, eid = _clip(tmp_path)
    ghost = "20260905-143900-999"
    (d / f"{ghost}.json").write_text(
        json.dumps(
            {
                "event_id": ghost,
                "camera_id": "cam_a",
                "labels": ["motion"],
                "scanned": True,
                "snapshot_relpath": f"motion_detection/cam_a/2026-09-05/{SPRITE_DIR}/{ghost}.jpg",
            }
        ),
        encoding="utf-8",
    )

    assert purge_scrub_ghost_events(storage_root=tmp_path) == 1

    assert not (d / f"{ghost}.json").exists()
    # Der echte Clip bleibt unangetastet — sein Schnappschuss liegt nicht
    # im Filmstreifen-Ordner.
    assert (d / f"{eid}.json").exists()


def test_der_einmallauf_laeuft_zweimal_ohne_etwas_zu_aendern(tmp_path):
    _clip(tmp_path)
    assert purge_scrub_ghost_events(storage_root=tmp_path) == 0
    assert purge_scrub_ghost_events(storage_root=tmp_path) == 0


def test_ohne_archiv_passiert_nichts(tmp_path):
    assert purge_scrub_ghost_events(storage_root=tmp_path / "gibtsnicht") == 0
