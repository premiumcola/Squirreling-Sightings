"""Das Sichtungs-Raster ist eine Frage ans Archiv, keine Sperrklinke.

Zwei Fehler, ein Modul. Der erste: „Wieso werden erkannte Vogelarten
trotz viel Media dazu nicht eingetragen???" — es gab die Art auf zwei
Wegen und nur einer trug ein. Der zweite, und der teurere: eingetragen
wurde für immer. Keine der Stellen, die eine Art nachträglich ÄNDERN —
die Korrektur von Hand, die Neuentscheidung nach der Feinanalyse, das
Löschen eines Clips — hat die Datei je angefasst, also blieb jede
Fehlerkennung freigeschaltet, nachdem der Clip längst etwas anderes
hieß: „Aktuell sind jetzt dann durch die Fehlerkennungen von Videos eben
Dinge freigeschalten, die faktisch nicht freigeschalten sind."

Die Antwort auf beides ist dieselbe: die Kachel zählt, was im Archiv
steht — nicht, was einmal darin stand.
"""

from __future__ import annotations

import json

from app.species_board import (
    proof_event_ids,
    resync_species_board,
    species_losing_last_proof,
    tally_species,
)
from app.species_unlock import achievement_id_for, apply_species_tally, unlock_species


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


def _store(root) -> _Store:
    return _Store(root / "motion_detection")


# ── Der Live-Weg: eine Art im Moment ihrer Erkennung ────────────────────


def test_eine_neue_art_wird_eingetragen(tmp_path):
    assert unlock_species(tmp_path, "Kohlmeise", camera_id="cam_a") is True
    entry = _unlocked(tmp_path)["kohlmeise"]
    assert entry["species"] == "Kohlmeise"
    assert entry["camera_id"] == "cam_a"
    assert entry["date"]
    # Die untere Schranke, bis der Abgleich die echte Zahl kennt — die
    # Kachel soll nicht „1×" raten müssen.
    assert entry["count"] == 1


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


# ── Der Lauf über das Archiv: was steht dort JETZT ──────────────────────


def test_der_abgleich_holt_benannte_arten_aus_dem_archiv(tmp_path):
    # DER GEMESSENE ZUSTAND: benannt im Ereignis, gesperrt im Raster.
    for i in range(6):
        _event(tmp_path, "cam_a", f"evt_{i}", bird_species="Kohlmeise")
    _event(tmp_path, "cam_a", "evt_x", bird_species=None)
    _event(tmp_path, "cam_b", "evt_y", bird_species="Blaumeise")

    out = resync_species_board(_store(tmp_path), tmp_path)

    assert out == {"unlocked": 2, "revoked": 0, "species": 2}
    assert sorted(_unlocked(tmp_path)) == ["blaumeise", "kohlmeise"]


def test_die_kachel_zaehlt_die_clips_und_nicht_bis_eins(tmp_path):
    # Der Zähler stand nie auf der Platte — jede freigeschaltete Kachel
    # zeigte den Notnagel „1× gesehen" der Oberfläche, egal wie viele
    # Aufnahmen es gab.
    for i in range(6):
        _event(tmp_path, "cam_a", f"evt_{i}", bird_species="Kohlmeise")

    resync_species_board(_store(tmp_path), tmp_path)

    assert _unlocked(tmp_path)["kohlmeise"]["count"] == 6


def test_eine_art_die_aus_dem_archiv_verschwindet_verliert_ihr_abzeichen(tmp_path):
    # GENAU DER FEHLER: der Clip trug „Amsel", die Kachel ging auf.
    _event(tmp_path, "cam_a", "evt_0", bird_species="Graureiher")
    _event(tmp_path, "cam_a", "evt_1", bird_species="Amsel")
    resync_species_board(_store(tmp_path), tmp_path)
    assert "amsel" in _unlocked(tmp_path)

    # Die Feinanalyse entscheidet denselben Clip neu — ab hier hat die
    # Amsel keinen einzigen Beleg mehr im Archiv.
    _event(tmp_path, "cam_a", "evt_1", bird_species="Elster")
    out = resync_species_board(_store(tmp_path), tmp_path)

    assert out["revoked"] == 1
    assert "amsel" not in _unlocked(tmp_path)
    # „Graureiher" steht im Katalog gar nicht — nichts freizuschalten,
    # also auch nichts zurückzunehmen.
    assert sorted(_unlocked(tmp_path)) == ["elster"]


def test_das_erstsichtungsdatum_ueberlebt_jeden_abgleich(tmp_path):
    _event(tmp_path, "cam_a", "evt_0", bird_species="Elster", time="2026-09-06T08:00:00")
    resync_species_board(_store(tmp_path), tmp_path)
    first = _unlocked(tmp_path)["elster"]["date"]

    _event(tmp_path, "cam_b", "evt_1", bird_species="Elster", time="2026-09-07T09:00:00")
    resync_species_board(_store(tmp_path), tmp_path)

    entry = _unlocked(tmp_path)["elster"]
    assert entry["date"] == first == "2026-09-06T08:00:00"
    assert entry["count"] == 2


def test_der_abgleich_ruehrt_die_quests_nicht_an(tmp_path):
    # In derselben Datei wohnen die Quest-Blöcke. Ein Abgleich, der über
    # sie hinwegräumt, kostet den Fortschritt, den niemand beanstandet
    # hat.
    (tmp_path / "achievements.json").write_text(
        json.dumps({"quests": {"woche": 3}, "quests_archive": {"a": 1}, "amsel": {"count": 9}}),
        encoding="utf-8",
    )
    _event(tmp_path, "cam_a", "evt_0", bird_species="Elster")

    resync_species_board(_store(tmp_path), tmp_path)

    data = _unlocked(tmp_path)
    assert data["quests"] == {"woche": 3}
    assert data["quests_archive"] == {"a": 1}
    assert "amsel" not in data


def test_der_abgleich_laeuft_zweimal_ohne_etwas_zu_aendern(tmp_path):
    _event(tmp_path, "cam_a", "evt_0", bird_species="Rotkehlchen")
    resync_species_board(_store(tmp_path), tmp_path)
    before = _unlocked(tmp_path)

    assert resync_species_board(_store(tmp_path), tmp_path) == {
        "unlocked": 0,
        "revoked": 0,
        "species": 1,
    }
    assert _unlocked(tmp_path) == before


def test_zwei_schreibweisen_derselben_art_zaehlen_zusammen(tmp_path):
    # „Grünfink" und „gruenfink" zeigen auf dieselbe Abzeichen-ID. Ohne
    # Addition entschiede die Reihenfolge des Verzeichnisdurchlaufs, wie
    # oft ein Grünfink gesehen wurde.
    _event(tmp_path, "cam_a", "evt_0", bird_species="Grünfink")
    _event(tmp_path, "cam_a", "evt_1", bird_species="gruenfink")

    resync_species_board(_store(tmp_path), tmp_path)

    assert _unlocked(tmp_path)["gruenfink"]["count"] == 2


def test_der_abgleich_stolpert_nicht_ueber_spuren_sidecars(tmp_path):
    _event(tmp_path, "cam_a", "evt_0", bird_species="Amsel")
    d = tmp_path / "motion_detection" / "cam_a" / "2026-09-06"
    (d / "evt_0.tracks.json").write_text('{"tracks": []}', encoding="utf-8")
    (d / "kaputt.json").write_text("nicht json", encoding="utf-8")

    assert resync_species_board(_store(tmp_path), tmp_path) == {
        "unlocked": 1,
        "revoked": 0,
        "species": 1,
    }


def test_eine_kaputte_datei_bricht_den_abgleich_ab_statt_sie_zu_ueberschreiben(tmp_path):
    (tmp_path / "achievements.json").write_text("{kaputt", encoding="utf-8")
    _event(tmp_path, "cam_a", "evt_0", bird_species="Amsel")

    assert resync_species_board(_store(tmp_path), tmp_path) == {
        "unlocked": 0,
        "revoked": 0,
        "species": 0,
    }
    assert (tmp_path / "achievements.json").read_text(encoding="utf-8") == "{kaputt"


def test_ohne_archiv_wird_nichts_zurueckgenommen(tmp_path):
    # DER GEFÄHRLICHSTE FALL. „Kein Archiv gefunden" und „Archiv gefunden,
    # keine Art darin" sehen als Zählung identisch aus — und der zweite
    # nimmt zu Recht jedes Abzeichen zurück. Würde der erste genauso
    # behandelt, räumte ein beim Start noch nicht eingehängter
    # Datenträger das ganze Raster ab, aus einem Grund, der mit Arten
    # nichts zu tun hat.
    unlock_species(tmp_path, "Amsel", camera_id="cam_a")
    before = _unlocked(tmp_path)

    assert tally_species(tmp_path / "gibtsnicht") == {}
    assert tally_species(None) == {}
    for store in (_Store(tmp_path / "gibtsnicht"), _Store(None)):
        assert resync_species_board(store, tmp_path) == {
            "unlocked": 0,
            "revoked": 0,
            "species": 0,
        }
    assert apply_species_tally(None, {}) == {"unlocked": 0, "revoked": 0, "species": 0}
    assert _unlocked(tmp_path) == before


def test_ein_leergeraeumtes_archiv_nimmt_sehr_wohl_zurueck(tmp_path):
    # Die Gegenprobe zum Test darüber: das Verzeichnis IST da und enthält
    # keine Art mehr — jeder Beleg gelöscht, also auch kein Abzeichen.
    _event(tmp_path, "cam_a", "evt_0", bird_species="Elster")
    resync_species_board(_store(tmp_path), tmp_path)
    (tmp_path / "motion_detection" / "cam_a" / "2026-09-06" / "evt_0.json").unlink()

    assert resync_species_board(_store(tmp_path), tmp_path)["revoked"] == 1
    assert _unlocked(tmp_path) == {}


# ── Kein Abzeichen ohne Beleg ───────────────────────────────────────────
#
# Seit das Raster Abzeichen ZURÜCKNIMMT, hat jede Löschung eine
# Nebenwirkung, die sie vorher nicht hatte: mit der letzten Aufnahme
# einer Art geht auch ihre Erkennung. „kein spezies unlock ohne
# beweisvideo!"


def _clips(root, species, n, cam="cam_a", day="2026-09-06", first=0):
    for i in range(n):
        _event(
            root,
            cam,
            f"{species.lower()}_{first + i}",
            bird_species=species,
            time=f"2026-09-{6 + (first + i) % 20:02d}T08:00:00",
        )


def test_die_zehn_neuesten_aufnahmen_je_art_sind_unantastbar(tmp_path):
    _clips(tmp_path, "Elster", 25)
    _clips(tmp_path, "Amsel", 3)

    proof = proof_event_ids(tmp_path / "motion_detection")

    # 10 von 25 Elstern, und alle drei Amseln — eine Art mit weniger als
    # zehn Aufnahmen behält schlicht alle.
    assert sum(1 for i in proof if i.startswith("elster_")) == 10
    assert sum(1 for i in proof if i.startswith("amsel_")) == 3


def test_die_neuesten_bleiben_nicht_die_aeltesten(tmp_path):
    for i, day in enumerate(("06", "07", "08")):
        _event(tmp_path, "cam_a", f"e{i}", bird_species="Elster", time=f"2026-09-{day}T08:00:00")

    assert proof_event_ids(tmp_path / "motion_detection", keep=1) == {"e2"}


def test_eine_loeschung_die_eine_art_restlos_traefe_wird_gemeldet(tmp_path):
    _clips(tmp_path, "Elster", 12)
    _clips(tmp_path, "Amsel", 2)
    events_dir = tmp_path / "motion_detection"

    # Beide Amseln weg, eine einzelne Elster weg.
    losing = species_losing_last_proof(events_dir, ["amsel_0", "amsel_1", "elster_0"])

    assert losing == {"Amsel": 2}, "nur die Art, die JEDEN Beleg verliert"


def test_ohne_treffer_wird_nicht_gefragt(tmp_path):
    _clips(tmp_path, "Elster", 12)
    events_dir = tmp_path / "motion_detection"
    assert species_losing_last_proof(events_dir, []) == {}
    assert species_losing_last_proof(events_dir, ["elster_0", "elster_1"]) == {}
    # Eine ID, die es gar nicht gibt, betrifft niemanden.
    assert species_losing_last_proof(events_dir, ["gibtsnicht"]) == {}
