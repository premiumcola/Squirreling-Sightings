"""Die Frist darf einer Art nicht ihr Abzeichen nehmen.

Seit `species_board` das Sichtungs-Raster aus dem Archiv ableitet, hat
`retention_days` eine Nebenwirkung, die es vorher nicht hatte: läuft die
letzte Aufnahme einer Art ab, verschwindet mit ihr die Erkennung — ohne
dass jemand etwas falsch gemacht hätte. „Sorge dafür auch in den lösch
timern dass mindestens die letzten 10 erkennungen der spezies als video
erhalten bleiben."
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

from app.storage import EventStore
from app.storage_retention import cleanup_old


def _old_event(root, eid, *, days_old, species=None, cam="cam_a"):
    d = root / "motion_detection" / cam / "2026-08-01"
    d.mkdir(parents=True, exist_ok=True)
    payload = {"event_id": eid, "camera_id": cam, "labels": ["motion"]}
    if species:
        payload["bird_species"] = species
        payload["time"] = f"2026-08-01T{int(eid[-2:]) % 24:02d}:00:00"
    jf = d / f"{eid}.json"
    jf.write_text(json.dumps(payload), encoding="utf-8")
    snap = d / f"{eid}.jpg"
    snap.write_bytes(b"x")
    old = time.time() - days_old * 86400
    for p in (jf, snap):
        os.utime(p, (old, old))
    return jf


def _surviving(root) -> set:
    return {p.stem for p in (root / "motion_detection").rglob("*.json")}


def test_die_letzten_belege_einer_art_ueberleben_die_frist(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage_retention.keep_judged_events_enabled", lambda: False)
    # Zwölf uralte Elstern und ein ebenso altes reines Bewegungsereignis.
    for i in range(12):
        _old_event(tmp_path, f"elster_{i:02d}", days_old=90, species="Elster")
    _old_event(tmp_path, "motion_00", days_old=90)
    store = EventStore(str(tmp_path))

    cleanup_old(store, retention_days=7)

    left = _surviving(tmp_path)
    # Zehn Belege bleiben, die zwei ältesten Elstern und das
    # Bewegungsereignis gehen wie vorgesehen.
    assert len([e for e in left if e.startswith("elster_")]) == 10
    assert "motion_00" not in left


def test_eine_art_mit_wenigen_aufnahmen_behaelt_alle(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage_retention.keep_judged_events_enabled", lambda: False)
    for i in range(3):
        _old_event(tmp_path, f"amsel_{i:02d}", days_old=400, species="Amsel")
    store = EventStore(str(tmp_path))

    cleanup_old(store, retention_days=7)

    assert len(_surviving(tmp_path)) == 3, "drei Aufnahmen sind weniger als zehn — alle bleiben"


def test_ereignisse_ohne_art_raeumt_die_frist_weiter_ab(tmp_path, monkeypatch):
    """Die Gegenprobe: der Schutz darf die Frist nicht aushebeln."""
    monkeypatch.setattr("app.storage_retention.keep_judged_events_enabled", lambda: False)
    for i in range(5):
        _old_event(tmp_path, f"motion_{i:02d}", days_old=90)
    store = EventStore(str(tmp_path))

    cleanup_old(store, retention_days=7)

    assert _surviving(tmp_path) == set()


def test_frische_aufnahmen_bleiben_ohnehin(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage_retention.keep_judged_events_enabled", lambda: False)
    _old_event(tmp_path, "motion_00", days_old=1)
    store = EventStore(str(tmp_path))

    cleanup_old(store, retention_days=7)

    assert _surviving(tmp_path) == {"motion_00"}
    assert datetime.now() - timedelta(days=7) < datetime.now()
