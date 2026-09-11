"""Das Sichtungsbuch — die Erkennung muss ihr Video überleben.

Bis zu diesem Modul stand eine Art an genau einer Stelle: im Feld
`bird_species` der Ereignis-Datei. `trash.move_to_trash` räumt genau
diese Datei weg, und weil Zeitleiste, Statistik und Abzeichenraster
dieselben Dateien zählen, nahm das Löschen eines Clips die Sichtung
mit — wann, welche Art, welche Kamera.

    „wichtig auch wenn ich die video lösche die ereignisse wann welcher
    vogel / spezies erkannt wurde ich noch separat zum video in einer
    art erkennungs-datenbank auch für die statistik gespeichert??"

Festgenagelt wird hier deshalb vor allem EINE Zusage — dass eine
Löschung keine Zeile aus dem Buch nimmt — und die drei Eigenschaften,
ohne die sie nichts wert wäre: dass dieselbe Sichtung nicht zweimal
zählt, dass ein Widerruf (Artkorrektur) sehr wohl durchschlägt, und dass
der Nachtrag aus dem Archiv konvergiert statt bei jedem Lauf zu wachsen.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import app_state, trash as _trash
from app.sightings_ledger import (
    backfill_from_archive,
    daily_counts,
    folded,
    ledger_path,
    record_sighting,
    species_totals,
)

CAM = "reolink_cx810_futterhaus_172"


def _event(event_id: str, species: str | None, *, time: str, cam: str = CAM) -> dict:
    """Eine Ereignis-Datei in ihrer Plattenform, auf das Nötige gekürzt."""
    return {
        "event_id": event_id,
        "camera_id": cam,
        "time": time,
        "labels": ["bird"],
        "top_label": "bird",
        "bird_species": species,
        "whole_clip": {
            "species": [
                {"species": species, "species_latin": "Pica pica", "best_score": 0.8123},
            ]
        }
        if species
        else None,
    }


def _rows(storage_root: Path) -> list[dict]:
    """Jede Zeile im Buch, roh und in Dateireihenfolge."""
    path = ledger_path(storage_root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _archive(storage_root: Path, event: dict) -> Path:
    """Die Ereignis-Datei ins Archiv legen, wie der Aufnahmepfad es tut."""
    day = str(event["time"])[:10]
    ev_dir = storage_root / "motion_detection" / event["camera_id"] / day
    ev_dir.mkdir(parents=True, exist_ok=True)
    path = ev_dir / f"{event['event_id']}.json"
    path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_storage_root: Path, monkeypatch):
    """Der Store-Stub, den `trash` und der Nachtrag anfassen: eine
    Wurzel und das Archivverzeichnis, mehr liest keiner von beiden."""
    stub = SimpleNamespace(
        root=str(tmp_storage_root),
        events_dir=tmp_storage_root / "motion_detection",
    )
    monkeypatch.setattr(app_state, "store", stub, raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(data={"trash": {"grace_days": 7}}), raising=False
    )
    return stub


# ── Schreiben ────────────────────────────────────────────────────────────


def test_a_sighting_is_booked_with_its_time_camera_and_score(tmp_storage_root: Path):
    assert record_sighting(tmp_storage_root, _event("ev1", "Elster", time="2026-09-01T07:30:00"))
    (row,) = _rows(tmp_storage_root)
    assert row["event_id"] == "ev1"
    assert row["cam_id"] == CAM
    assert row["species"] == "Elster"
    assert row["time"] == "2026-09-01T07:30:00"
    # Ohne die Zahl ist die Zeile nicht nachprüfbar — sie ist der einzige
    # Rest der Messung, wenn der Clip weg ist.
    assert row["score"] == 0.8123
    assert row["species_latin"] == "Pica pica"


def test_the_same_event_twice_does_not_count_twice(tmp_storage_root: Path):
    event = _event("ev1", "Elster", time="2026-09-01T07:30:00")
    assert record_sighting(tmp_storage_root, event) is True
    assert record_sighting(tmp_storage_root, event) is False
    assert len(_rows(tmp_storage_root)) == 1
    assert species_totals(tmp_storage_root)["Elster"]["count"] == 1


def test_an_event_without_a_species_is_not_booked(tmp_storage_root: Path):
    assert (
        record_sighting(tmp_storage_root, _event("ev1", None, time="2026-09-01T07:30:00")) is False
    )
    assert _rows(tmp_storage_root) == []


def test_a_correction_supersedes_the_guess_without_erasing_it(tmp_storage_root: Path):
    record_sighting(tmp_storage_root, _event("ev1", "Elster", time="2026-09-01T07:30:00"))
    corrected = _event("ev1", "Eichelhäher", time="2026-09-01T07:30:00")
    assert record_sighting(tmp_storage_root, corrected, source="web_species") is True

    # Angehängt, nicht überschrieben: die ursprüngliche Entscheidung des
    # Modells bleibt lesbar.
    rows = _rows(tmp_storage_root)
    assert [r["species"] for r in rows] == ["Elster", "Eichelhäher"]
    # Gezählt wird trotzdem nur einmal, und zwar die Korrektur.
    totals = species_totals(tmp_storage_root)
    assert set(totals) == {"Eichelhäher"}
    assert totals["Eichelhäher"]["count"] == 1


def test_a_retraction_drops_it_from_the_statistics(tmp_storage_root: Path):
    """„War doch kein Vogel" ist etwas anderes als „Video gelöscht"."""
    record_sighting(tmp_storage_root, _event("ev1", "Elster", time="2026-09-01T07:30:00"))
    retracted = _event("ev1", None, time="2026-09-01T07:30:00")
    assert record_sighting(tmp_storage_root, retracted, source="web_labels") is True
    assert species_totals(tmp_storage_root) == {}
    # Und der Widerruf hängt sich nicht bei jedem weiteren Lauf erneut an.
    assert record_sighting(tmp_storage_root, retracted, source="web_labels") is False
    assert len(_rows(tmp_storage_root)) == 2


# ── Die eigentliche Zusage ───────────────────────────────────────────────


def test_deleting_the_clip_does_not_remove_the_sighting(store, tmp_storage_root: Path):
    """Der Grund, warum es dieses Modul gibt.

    „Beim löschen der elemente bitte nicht die statistik leeren also die
    events bleiben drin." Nach der Löschung ist die Ereignis-Datei aus
    dem Archiv verschwunden — und die Sichtung steht noch.
    """
    event = _event("ev_del", "Elster", time="2026-09-01T07:30:00")
    manifest = _archive(tmp_storage_root, event)

    result = _trash.move_to_trash(CAM, "ev_del")

    assert result["json_deleted"] is True
    assert not manifest.exists()
    assert folded(tmp_storage_root)["ev_del"]["species"] == "Elster"
    totals = species_totals(tmp_storage_root)
    assert totals["Elster"]["count"] == 1
    assert totals["Elster"]["cameras"] == [CAM]
    assert daily_counts(tmp_storage_root) == {"2026-09-01": 1}


def test_the_backfill_never_retracts_a_deleted_clip(store, tmp_storage_root: Path):
    """Abwesenheit im Archiv darf nichts bedeuten — sonst räumte der
    nächtliche Nachtrag genau das weg, was er sichern soll."""
    _archive(tmp_storage_root, _event("ev_del", "Elster", time="2026-09-01T07:30:00"))
    _trash.move_to_trash(CAM, "ev_del")

    assert backfill_from_archive(store, tmp_storage_root) == {"examined": 0, "added": 0}
    assert species_totals(tmp_storage_root)["Elster"]["count"] == 1


def test_a_clip_deleted_before_the_ledger_existed_is_still_rescued(store, tmp_storage_root: Path):
    """Der Live-Pfad kann die Zeile nie geschrieben haben (Altbestand,
    ausgefallene Schreibung). Die Löschung ist der letzte Moment, in dem
    die Art überhaupt noch irgendwo steht."""
    _archive(tmp_storage_root, _event("ev_old", "Amsel", time="2026-08-14T06:05:00"))
    assert _rows(tmp_storage_root) == []

    _trash.move_to_trash(CAM, "ev_old")

    assert species_totals(tmp_storage_root)["Amsel"]["count"] == 1


# ── Nachtrag aus dem Archiv ──────────────────────────────────────────────


def test_the_backfill_seeds_history_and_converges(store, tmp_storage_root: Path):
    _archive(tmp_storage_root, _event("ev1", "Elster", time="2026-09-01T07:30:00"))
    _archive(tmp_storage_root, _event("ev2", "Amsel", time="2026-09-02T08:00:00"))
    _archive(tmp_storage_root, _event("ev3", "Elster", time="2026-09-02T09:15:00"))

    first = backfill_from_archive(store, tmp_storage_root)
    assert first == {"examined": 3, "added": 3}
    # Ein zweiter Lauf über ein unverändertes Archiv fügt NICHTS hinzu.
    assert backfill_from_archive(store, tmp_storage_root) == {"examined": 3, "added": 0}
    assert len(_rows(tmp_storage_root)) == 3

    totals = species_totals(tmp_storage_root)
    assert totals["Elster"]["count"] == 2
    assert totals["Elster"]["days"] == 2
    assert totals["Elster"]["first"] == "2026-09-01T07:30:00"
    assert totals["Elster"]["last"] == "2026-09-02T09:15:00"
    assert totals["Amsel"]["count"] == 1


def test_the_backfill_does_not_overwrite_a_live_measurement(store, tmp_storage_root: Path):
    """Die Archivzeile kennt keinen Messwert. Sie darf die reichere
    Live-Zeile deshalb nicht ersetzen."""
    event = _event("ev1", "Elster", time="2026-09-01T07:30:00")
    _archive(tmp_storage_root, event)
    record_sighting(tmp_storage_root, event)

    assert backfill_from_archive(store, tmp_storage_root)["added"] == 0
    assert folded(tmp_storage_root)["ev1"]["score"] == 0.8123


def test_no_archive_directory_is_not_an_empty_archive(tmp_path: Path, tmp_storage_root: Path):
    missing = SimpleNamespace(events_dir=tmp_path / "nirgends")
    assert backfill_from_archive(missing, tmp_storage_root) == {"examined": 0, "added": 0}


# ── Lesen ────────────────────────────────────────────────────────────────


def test_a_range_is_inclusive_at_both_ends(tmp_storage_root: Path):
    for i, day in enumerate(("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03")):
        record_sighting(tmp_storage_root, _event(f"ev{i}", "Elster", time=f"{day}T07:00:00"))

    days = daily_counts(tmp_storage_root, since="2026-09-01", until="2026-09-02")
    assert days == {"2026-09-01": 1, "2026-09-02": 1}
    assert species_totals(tmp_storage_root, since="2026-09-01", until="2026-09-02") == {
        "Elster": {
            "count": 2,
            "days": 2,
            "first": "2026-09-01T07:00:00",
            "last": "2026-09-02T07:00:00",
            "cameras": [CAM],
            "species_latin": "Pica pica",
        }
    }


def test_a_species_filter_answers_only_for_that_species(tmp_storage_root: Path):
    record_sighting(tmp_storage_root, _event("ev1", "Elster", time="2026-09-01T07:00:00"))
    record_sighting(tmp_storage_root, _event("ev2", "Amsel", time="2026-09-01T08:00:00"))
    assert daily_counts(tmp_storage_root, species="Amsel") == {"2026-09-01": 1}
    assert set(species_totals(tmp_storage_root, species="Amsel")) == {"Amsel"}


def test_a_sighting_without_a_date_stays_out_of_a_bounded_query(tmp_storage_root: Path):
    """Sie kann weder drinnen noch draußen belegt werden — und eine
    Monatsstatistik mit Zeilen ohne Monat ist keine."""
    record_sighting(tmp_storage_root, _event("ev1", "Elster", time=""))
    assert species_totals(tmp_storage_root)["Elster"]["count"] == 1
    assert species_totals(tmp_storage_root, since="2026-09-01") == {}
    assert daily_counts(tmp_storage_root) == {}


# ── Die Leseschnittstelle ────────────────────────────────────────────────


def test_the_api_answers_from_the_ledger_not_from_the_clips(store, tmp_storage_root: Path):
    flask = pytest.importorskip("flask")
    from app.routes import sichtungen as sichtungen_routes

    _archive(tmp_storage_root, _event("ev1", "Elster", time="2026-09-01T07:30:00"))
    _trash.move_to_trash(CAM, "ev1")

    app = flask.Flask(__name__)
    app.register_blueprint(sichtungen_routes.bp)
    resp = app.test_client().get("/api/sightings/ledger?since=2026-09-01&until=2026-09-01")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["total"] == 1
    assert body["species_totals"]["Elster"]["count"] == 1
    assert body["per_day"] == {"2026-09-01": 1}
