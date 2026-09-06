"""Beide Erkennungswege tragen die Art ins Sichtungs-Raster ein.

„Wieso werden erkannte Vogelarten trotz viel Media dazu nicht
eingetragen???" — weil es sie auf zwei Wegen gab und nur einer eintrug.
Sechs Aufnahmen trugen `bird_species: Kohlmeise`, der Steckbrief zählte
sie, und das Raster stand auf „2 von 27 gesichtet": genau die zwei Arten,
die LIVE bestimmt worden waren.
"""

from __future__ import annotations

import json

from app.bird_species_backfill import reconcile_species_unlocks
from app.species_unlock import achievement_id_for, unlock_species


class _Store:
    def __init__(self, events_dir):
        self.events_dir = events_dir


def _event(root, cam, name, **fields):
    d = root / "motion_detection" / cam / "2026-09-06"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps({"event_id": name, **fields}), encoding="utf-8")


def _unlocked(root) -> dict:
    p = root / "achievements.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def test_eine_neue_art_wird_eingetragen(tmp_path):
    assert unlock_species(tmp_path, "Kohlmeise", camera_id="cam_a") is True
    entry = _unlocked(tmp_path)["kohlmeise"]
    assert entry["species"] == "Kohlmeise"
    assert entry["camera_id"] == "cam_a"
    assert entry["date"]


def test_die_zweite_sichtung_ueberschreibt_die_erste_nicht(tmp_path):
    unlock_species(tmp_path, "Elster", camera_id="cam_a")
    first = _unlocked(tmp_path)["elster"]
    # Das Abzeichen sagt „seit wann". Dieselbe Art am Dienstag darf den
    # Sonntag nicht überschreiben, an dem sie zuerst da war.
    assert unlock_species(tmp_path, "Elster", camera_id="cam_b") is False
    assert _unlocked(tmp_path)["elster"] == first


def test_eine_unbekannte_art_traegt_nichts_ein(tmp_path):
    assert unlock_species(tmp_path, "Wellensittich") is False
    assert unlock_species(tmp_path, "") is False
    assert _unlocked(tmp_path) == {}


def test_umlaut_und_umschrift_zeigen_auf_dieselbe_id():
    assert achievement_id_for("Grünfink") == achievement_id_for("gruenfink") == "gruenfink"
    assert achievement_id_for("  ELSTER ") == "elster"


def test_eine_kaputte_datei_kostet_die_quests_nicht(tmp_path):
    (tmp_path / "achievements.json").write_text("{kaputt", encoding="utf-8")
    # Bei leer anzufangen wäre der teurere Fehler: das schriebe die
    # Quest-Blöcke weg. Lieber gar nichts eintragen.
    assert unlock_species(tmp_path, "Amsel") is False
    assert (tmp_path / "achievements.json").read_text(encoding="utf-8") == "{kaputt"


def test_der_nachtrag_holt_benannte_arten_aus_dem_archiv(tmp_path):
    # DER GEMESSENE ZUSTAND: benannt im Ereignis, gesperrt im Raster.
    for i in range(6):
        _event(tmp_path, "cam_a", f"evt_{i}", bird_species="Kohlmeise")
    _event(tmp_path, "cam_a", "evt_x", bird_species=None)
    _event(tmp_path, "cam_b", "evt_y", bird_species="Blaumeise")
    store = _Store(tmp_path / "motion_detection")

    out = reconcile_species_unlocks(store, tmp_path)

    assert out == {"seen": 2, "unlocked": 2}
    assert sorted(_unlocked(tmp_path)) == ["blaumeise", "kohlmeise"]


def test_der_nachtrag_laeuft_zweimal_ohne_etwas_zu_aendern(tmp_path):
    _event(tmp_path, "cam_a", "evt_0", bird_species="Rotkehlchen")
    store = _Store(tmp_path / "motion_detection")
    reconcile_species_unlocks(store, tmp_path)
    before = _unlocked(tmp_path)

    assert reconcile_species_unlocks(store, tmp_path) == {"seen": 1, "unlocked": 0}
    assert _unlocked(tmp_path) == before


def test_der_nachtrag_stolpert_nicht_ueber_spuren_sidecars(tmp_path):
    _event(tmp_path, "cam_a", "evt_0", bird_species="Amsel")
    d = tmp_path / "motion_detection" / "cam_a" / "2026-09-06"
    (d / "evt_0.tracks.json").write_text('{"tracks": []}', encoding="utf-8")
    (d / "kaputt.json").write_text("nicht json", encoding="utf-8")
    store = _Store(tmp_path / "motion_detection")

    assert reconcile_species_unlocks(store, tmp_path) == {"seen": 1, "unlocked": 1}


def test_ohne_archiv_passiert_nichts(tmp_path):
    assert reconcile_species_unlocks(_Store(tmp_path / "gibtsnicht"), tmp_path) == {
        "seen": 0,
        "unlocked": 0,
    }
    assert reconcile_species_unlocks(_Store(None), tmp_path) == {"seen": 0, "unlocked": 0}
