"""Personen-Ausschnitte aus dem Clip, nicht aus dem Schnappschuss.

„kannst du fotos der personen aus allen videos extrahieren damit ich die
dann auf individuen branden kann?"

Der bestehende Registrierungsweg schneidet aus dem gespeicherten
Schnappschuss mit einem Rechteck aus dem Ereignis — und die beiden liegen
nicht im selben Pixelraum (der Schnappschuss ist herunterskaliert, bei
Clips sogar nur das ≤640er Vorschaubild). Für Clip-Ereignisse antwortet
er deshalb meist mit „Crop leer".

Die Rechtecke in `<clip>.tracks.json` stammen dagegen aus genau dem MP4,
das danebenliegt. Darauf beruht dieses Modul, und darauf beruhen diese
Tests.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.person_crops import (
    CROP_DIR,
    best_sample,
    crop_relpath_for,
    crops_of,
    extract_person_crops,
    needs_crops,
    observed_samples,
    person_tracks,
)
from app.storage_scan import is_derived_media

cv2 = pytest.importorskip("cv2")


def _sample(f, *, source="detect", score=0.8, box=(10, 10, 90, 190)):
    x1, y1, x2, y2 = box
    return {
        "f": f,
        "t": round(f / 25.0, 3),
        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "score": score,
        "source": source,
        "label": "person",
    }


def _track(track_id, *, label="person", best_frame=None, samples=None):
    return {
        "track_id": track_id,
        "label": label,
        "best_frame": best_frame,
        "best_score": 0.9,
        "samples": samples if samples is not None else [_sample(25)],
    }


# ── Welche Spuren, welche Stichproben ────────────────────────────────────


def test_nur_personenspuren():
    side = {"tracks": [_track(1), _track(2, label="cat"), {"nope": True}, None]}
    assert [t["track_id"] for t in person_tracks(side)] == [1]
    assert person_tracks({}) == []
    assert person_tracks({"tracks": "kaputt"}) == []


def test_nur_beobachtete_stichproben():
    """In einem vorhergesagten Rechteck steht mit einiger
    Wahrscheinlichkeit niemand mehr — als Portrait wertlos, als
    Erkennungsprobe schädlich."""
    t = _track(
        1,
        samples=[
            _sample(25),
            _sample(50, source="track"),
            _sample(75, source="predicted"),
            {"f": 100, "source": "detect"},  # ohne bbox
        ],
    )
    assert [s["f"] for s in observed_samples(t)] == [25]


def test_die_spur_zeigt_selbst_auf_ihr_bestes_bild():
    t = _track(
        1,
        best_frame=50,
        samples=[_sample(25, score=0.9), _sample(50, score=0.4)],
    )
    assert best_sample(t)["f"] == 50, "die Spur weiß es besser als der Score"


def test_ist_das_beste_bild_keine_messung_gewinnt_die_beste_messung():
    t = _track(
        1,
        best_frame=50,
        samples=[_sample(25, score=0.4), _sample(50, source="predicted"), _sample(75, score=0.9)],
    )
    assert best_sample(t)["f"] == 75


def test_eine_spur_ohne_messung_liefert_nichts():
    assert best_sample(_track(1, samples=[_sample(25, source="predicted")])) is None
    assert best_sample(_track(1, samples=[])) is None


# ── Wo die Ausschnitte liegen ────────────────────────────────────────────


def test_der_ausschnitt_liegt_im_eigenen_verzeichnis():
    rel = crop_relpath_for("motion_detection/cam_a/2026-09-11/evt_1.mp4", 3)
    assert rel == f"motion_detection/cam_a/2026-09-11/{CROP_DIR}/evt_1-3.jpg"


def test_der_medienlauf_haelt_den_ausschnitt_fuer_abgeleitet(tmp_path):
    """Sonst erfindet „Neu scannen" je Ausschnitt ein Geisterereignis —
    genau der Fehler, den der Filmstreifen schon einmal gekostet hat."""
    d = tmp_path / "motion_detection" / "cam_a" / "2026-09-11"
    assert is_derived_media(d / CROP_DIR / "evt_1-3.jpg") is True
    # Ein echter Schnappschuss heißt fast genauso und muss weiter zählen.
    assert is_derived_media(d / "evt_1.jpg") is False


# ── Der Schnitt selbst ───────────────────────────────────────────────────


def _write_clip(path, *, frames=60, w=320, h=240):
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(path), fourcc, 25.0, (w, h))
    for i in range(frames):
        frame = np.full((h, w, 3), 20, dtype=np.uint8)
        # Ein heller Block, der über das Bild wandert — so ist an der
        # Farbe erkennbar, ob der richtige Frame geschnitten wurde.
        frame[40:200, 10:90] = (i * 4) % 255
        vw.write(frame)
    vw.release()
    return path


def _event_with_clip(tmp_path, tracks, *, cam="cam_a", day="2026-09-11", eid="evt_1"):
    rel = f"motion_detection/{cam}/{day}/{eid}.mp4"
    clip = _write_clip(tmp_path / rel)
    (clip.with_name(clip.stem + ".tracks.json")).write_text(
        json.dumps({"schema": 4, "tracks": tracks}), encoding="utf-8"
    )
    return {"event_id": eid, "camera_id": cam, "video_relpath": rel}


def test_je_personenspur_ein_ausschnitt(tmp_path):
    event = _event_with_clip(
        tmp_path,
        [
            _track(1, best_frame=25),
            _track(2, best_frame=30, samples=[_sample(30, box=(120, 20, 220, 200))]),
            _track(3, label="cat"),
        ],
    )

    out = extract_person_crops(tmp_path, event)

    assert [c["track_id"] for c in out] == [1, 2], "die Katze gehört nicht dazu"
    for c in out:
        assert (tmp_path / c["relpath"]).exists()
    # Zwei Personen ergeben zwei Portraits, nicht einen Kompromiss.
    assert len({c["relpath"] for c in out}) == 2


def test_ein_zu_kleiner_ausschnitt_wird_verworfen(tmp_path):
    """Eine Person, die 20 px hoch durchs Bild läuft, taugt weder zum
    Ansehen noch als Erkennungsprobe."""
    event = _event_with_clip(tmp_path, [_track(1, samples=[_sample(25, box=(10, 10, 28, 30))])])
    assert extract_person_crops(tmp_path, event) == []


def test_ein_uebergrosses_rechteck_wird_abgelehnt_statt_geraten(tmp_path):
    """Genau der Fehler des alten Weges: lieber nichts als still das
    falsche Stück Bild."""
    event = _event_with_clip(tmp_path, [_track(1, samples=[_sample(25, box=(10, 10, 9000, 9000))])])
    assert extract_person_crops(tmp_path, event) == []


def test_ohne_personen_ohne_spurendatei_ohne_video_passiert_nichts(tmp_path):
    assert extract_person_crops(tmp_path, {}) == []
    assert extract_person_crops(tmp_path, {"video_relpath": "gibts/nicht.mp4"}) == []
    event = _event_with_clip(tmp_path, [_track(1, label="cat")], eid="evt_2")
    assert extract_person_crops(tmp_path, event) == []


# ── Wann ein Clip noch dran ist ──────────────────────────────────────────


def test_beide_haelften_muessen_stimmen(tmp_path):
    """Ein Ausschnitt auf der Platte, dessen Verweis das Ereignis nie
    erreicht hat, ist für die Galerie unsichtbar — und würde ohne diese
    Prüfung trotzdem für immer übersprungen."""
    assert needs_crops({}, tmp_path) is True
    ev = {"person_crops": [{"relpath": "motion_detection/cam_a/2026-09-11/crops/evt_1-1.jpg"}]}
    assert needs_crops(ev, tmp_path) is True, "Verweis da, Datei fehlt"
    p = tmp_path / ev["person_crops"][0]["relpath"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    assert needs_crops(ev, tmp_path) is False
    assert crops_of(ev) == ev["person_crops"]
    assert crops_of({"person_crops": "kaputt"}) == []


# ── Der Nachlauf ─────────────────────────────────────────────────────────


class _Store:
    def __init__(self, root):
        self.root = root
        self.events_dir = root / "motion_detection"
        self.written = []

    def update_event(self, cam_id, event_id, payload):
        self.written.append((cam_id, event_id))
        for jf in (self.events_dir / cam_id).rglob(f"{event_id}.json"):
            jf.write_text(json.dumps(payload), encoding="utf-8")
        return True


def _put_event(tmp_path, event, *, cam="cam_a", day="2026-09-11"):
    d = tmp_path / "motion_detection" / cam / day
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{event['event_id']}.json").write_text(json.dumps(event), encoding="utf-8")


def test_der_nachlauf_zieht_fehlende_ausschnitte_nach(tmp_path):
    from app.person_crops import sweep_person_crops

    ev = _event_with_clip(tmp_path, [_track(1, best_frame=25)])
    ev["labels"] = ["motion", "person"]
    _put_event(tmp_path, ev)
    store = _Store(tmp_path)

    out = sweep_person_crops(store, tmp_path)

    assert out["clips"] == 1 and out["crops"] == 1
    written = json.loads(
        (tmp_path / "motion_detection/cam_a/2026-09-11/evt_1.json").read_text(encoding="utf-8")
    )
    assert written["person_crops"], "der Verweis gehört auf das Ereignis"
    assert (tmp_path / written["person_crops"][0]["relpath"]).exists()


def test_der_nachlauf_laeuft_zweimal_ohne_doppelte_arbeit(tmp_path):
    from app.person_crops import sweep_person_crops

    ev = _event_with_clip(tmp_path, [_track(1, best_frame=25)])
    ev["labels"] = ["person"]
    _put_event(tmp_path, ev)
    store = _Store(tmp_path)
    sweep_person_crops(store, tmp_path)

    again = sweep_person_crops(store, tmp_path)

    assert again["clips"] == 0 and again["skipped"] == 1


def test_clips_ohne_person_kosten_nichts(tmp_path):
    from app.person_crops import sweep_person_crops

    ev = _event_with_clip(tmp_path, [_track(1)], eid="evt_9")
    ev["labels"] = ["motion"]
    _put_event(tmp_path, ev)

    out = sweep_person_crops(_Store(tmp_path), tmp_path)

    assert out == {"clips": 0, "crops": 0, "skipped": 0, "remaining": 0}


def test_das_budget_schneidet_ehrlich_ab(tmp_path):
    from app.person_crops import sweep_person_crops

    for i in range(3):
        ev = _event_with_clip(tmp_path, [_track(1, best_frame=25)], eid=f"evt_{i}")
        ev["labels"] = ["person"]
        _put_event(tmp_path, ev)

    out = sweep_person_crops(_Store(tmp_path), tmp_path, budget=2)

    assert out["clips"] == 2
    assert out["remaining"] == 1, "ein abgeschnittener Lauf darf sich nicht fertig nennen"


def test_ohne_archiv_passiert_nichts(tmp_path):
    from app.person_crops import sweep_person_crops

    assert sweep_person_crops(_Store(tmp_path / "nichts"), tmp_path)["clips"] == 0
