"""Die Vogelstimme im Artensteckbrief — warum sie beim Operator nie kam.

Gebaut war der ganze Weg schon: `fetch_xeno_canto` holt Aufnahmen,
`_apply_xeno_canto` legt sie ab, `_hero-overlay.js` malt den Play-Knopf
auf das Hero-Foto. Trotzdem hatte der Hausrotschwanz (Phoenicurus
ochruros) keinen Knopf — `recordings` war leer. Drei Ursachen, jede
einzeln hier festgenagelt:

  1. Die Abfrage schickte den nackten Binomialnamen (`query=Phoenicurus
     ochruros`). API v3 dokumentiert die Suche über Tags
     (`gen:… sp:…`); der nackte Name ist keine dokumentierte v3-Form.
  2. Die eine Abfrage war zusätzlich hart auf `q:A len:5-15` gefiltert.
     Eine Art ohne kurze Qualitäts-A-Aufnahme bekam nie etwas — es gab
     keine Stufe darunter.
  3. Ein Fehlschlag war ENDGÜLTIG. Kein Sweep hat je nachgefasst:
     `sweep_prebuild` legt nur fehlende Steckbriefe an, der Foto-Sweep
     schaut nur auf die Fotozahl, und `on_new_species` holt nur bei der
     ERSTEN Sichtung. Ein einziges leeres Ergebnis (fehlender Key,
     Netzhänger) hat die Art dauerhaft stumm gestellt.

Dazu die ehrliche Leerstelle im Panel: ohne Aufnahme verschwand der
Audioblock spurlos — genau das, was wie „die Funktion gibt es nicht"
aussieht statt wie „für diese Art noch keine Aufnahme".

Kein Test fasst das echte Netz an: `_rate_limited_get` wird gestubbt
(wie in test_bird_dossiers_fetch.py), der Service bekommt gefälschte
Fetch-Funktionen.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.bird_dossiers import BirdDossierService
from app.bird_dossiers_fetch import fetch_xeno_canto, xc_query_urls

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_KEY = "testkey123"


@pytest.fixture(autouse=True)
def _with_api_key(monkeypatch):
    """Jeder Test hier setzt den Key explizit — sonst hinge das Ergebnis
    an der Umgebung, in der die Suite gerade läuft."""
    monkeypatch.setenv("XENO_CANTO_API_KEY", _KEY)
    monkeypatch.setattr("app.bird_dossiers_fetch._xc_key_warned", [False])


# ── Die Abfrageform (rein, ohne Netz) ────────────────────────────────────


def test_query_uses_the_v3_genus_species_tags_not_a_bare_name():
    """Der Fehler, der den Hausrotschwanz stumm hielt: `query=` bekam den
    nackten Namen. v3 sucht über Tags."""
    urls = xc_query_urls("Phoenicurus ochruros", _KEY)
    assert urls
    for url in urls:
        assert "query=gen:Phoenicurus%20sp:ochruros" in url
        assert f"key={_KEY}" in url
    # Der nackte Name darf nirgends mehr als Suchbegriff auftauchen.
    assert not any("query=Phoenicurus%20ochruros" in u for u in urls)


def test_a_subspecies_never_reaches_the_api():
    """Trinomiale („Erithacus rubecula rubecula") liefern bei xeno-canto
    unter dem dritten Namen nichts. Früher kostete das eine eigene,
    garantiert leere Runde; der gen:/sp:-Split lässt ihn einfach weg."""
    urls = xc_query_urls("Erithacus rubecula rubecula", _KEY)
    assert urls
    for url in urls:
        assert "gen:Erithacus%20sp:rubecula" in url
        assert url.count("rubecula") == 1


def test_the_filter_ladder_relaxes_instead_of_giving_up():
    """Strengste Stufe zuerst, dann ohne Längenfenster, dann ohne jeden
    Filter — damit eine Art ohne kurze A-Aufnahme trotzdem klingt."""
    urls = xc_query_urls("Turdus merula", _KEY)
    assert len(urls) == 3
    assert "q:A%20len:5-15" in urls[0]
    assert "q:A" in urls[1] and "len:" not in urls[1]
    assert "q:A" not in urls[2] and "len:" not in urls[2]


def test_a_genus_only_name_still_produces_a_query():
    urls = xc_query_urls("Anas", _KEY)
    assert urls and all("gen:Anas" in u and "sp:" not in u for u in urls)


def test_a_blank_name_produces_no_request_at_all():
    assert xc_query_urls("", _KEY) == []
    assert xc_query_urls("   ", _KEY) == []


# ── fetch_xeno_canto gegen einen gestubbten Netzrand ─────────────────────


def _router(monkeypatch, routes: dict):
    """URL-Teilstring → Antwort. Kein Treffer = fehlgeschlagene Abfrage."""
    seen: list[str] = []

    def _get(url: str):
        seen.append(url)
        for needle, payload in routes.items():
            if needle in url:
                return payload
        return None

    monkeypatch.setattr("app.bird_dossiers_fetch._rate_limited_get", _get)
    return seen


def _rec(rid: str, typ: str) -> dict:
    return {
        "id": rid,
        "file": f"https://xc.invalid/{rid}.mp3",
        "type": typ,
        "rec": "M. Mustermann",
        "lic": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "length": "0:11",
    }


def test_a_species_without_a_short_quality_a_clip_still_gets_audio(monkeypatch):
    """Der zweite Grund für einen leeren Steckbrief: die einzige Abfrage
    war auf `q:A len:5-15` verengt. Hier antwortet nur die ungefilterte
    Stufe — vorher blieb es dabei still."""
    seen = _router(
        monkeypatch, {"query=gen:Turdus%20sp:merula&": {"recordings": [_rec("1", "song")]}}
    )
    out = fetch_xeno_canto("Turdus merula")
    assert [r["file_url"] for r in out] == ["https://xc.invalid/1.mp3"]
    assert out[0]["type_de"] == "Gesang"
    assert len(seen) == 3  # alle drei Stufen wurden gebraucht


def test_the_strict_rung_wins_when_it_answers(monkeypatch):
    """Die gute Aufnahme zuerst: antwortet `q:A len:5-15`, wird keine
    Sekunde am Rate-Limit für die lockereren Stufen verbraucht."""
    seen = _router(monkeypatch, {"q:A%20len:5-15": {"recordings": [_rec("9", "song")]}})
    out = fetch_xeno_canto("Turdus merula")
    assert [r["id"] for r in out] == ["9"]
    assert len(seen) == 1


def test_recordings_are_picked_by_call_type_diversity(monkeypatch):
    """Ein Gesang + ein Ruf sagen mehr als drei Gesänge."""
    _router(
        monkeypatch,
        {
            "q:A%20len:5-15": {
                "recordings": [_rec("1", "song"), _rec("2", "song"), _rec("3", "call")]
            }
        },
    )
    out = fetch_xeno_canto("Turdus merula", max_recordings=2)
    assert [r["type_de"] for r in out] == ["Gesang", "Ruf"]


def test_an_entry_without_a_playable_file_is_dropped(monkeypatch):
    _router(
        monkeypatch,
        {"q:A%20len:5-15": {"recordings": [{"id": "1", "type": "song"}, _rec("2", "call")]}},
    )
    assert [r["id"] for r in fetch_xeno_canto("Turdus merula")] == ["2"]


def test_a_missing_api_key_is_reported_once_not_swallowed(monkeypatch, caplog):
    """Ohne Key liefert v3 nichts — das war bisher ein wortloses
    `return []`. Genau eine Meldung pro Prozess: die Prebuild-Sweep geht
    über Hunderte Arten, ein Log-Sturm hilft niemandem.

    Die Stufe ist jetzt INFO, nicht WARNING, und das ist der Punkt: der
    fehlende Key macht die Vogelstimme nicht mehr kaputt. Sie kommt von
    Wikimedia Commons und braucht überhaupt keine Zugangsdaten
    (bird_audio_commons.py); xeno-canto liefert nur noch zusätzliche
    Aufnahmen. Eine WARNING würde behaupten, dass etwas nicht geht, was
    geht — und genau diese Fehlinformation hat den Betreiber wochenlang
    „Keine Vogelstimme verfügbar" lesen lassen."""
    monkeypatch.delenv("XENO_CANTO_API_KEY", raising=False)
    _router(monkeypatch, {"xeno-canto": {"recordings": [_rec("1", "song")]}})
    with caplog.at_level(logging.INFO, logger="app.bird_dossiers"):
        assert fetch_xeno_canto("Turdus merula") == []
        assert fetch_xeno_canto("Erithacus rubecula") == []
    hits = [r for r in caplog.records if "XENO_CANTO_API_KEY" in r.getMessage()]
    assert len(hits) == 1, "genau einmal, nicht je Art"
    assert hits[0].levelno == logging.INFO
    # Und die Meldung muss sagen, wo die Stimme HERKOMMT — sonst sucht
    # der nächste Leser wieder nach einem Key, den er nicht braucht.
    assert "Commons" in hits[0].getMessage()


# ── Der Nachfass-Sweep ───────────────────────────────────────────────────


def _service(tmp_path: Path, dossiers: dict) -> BirdDossierService:
    p = tmp_path / "bird_dossiers.json"
    p.write_text(json.dumps({"schema": 1, "dossiers": dossiers}), encoding="utf-8")
    return BirdDossierService(p)


def _cached(latin: str, *, recordings: list, checked: str | None = None) -> dict:
    d = BirdDossierService._blank_dossier(
        latin,
        None,
        first_seen_at=None,
        first_seen_event_id=None,
        first_seen_camera_id=None,
        sighting_count=0,
    )
    d["photo_urls"] = ["1", "2", "3"]  # fotoseitig fertig — nur der Ton fehlt
    d["wikipedia_fetched_at"] = "2026-09-01T00:00:00"
    d["recordings"] = recordings
    d["audio_checked_at"] = checked
    return d


def test_a_silent_dossier_is_retried_although_its_photos_are_complete(tmp_path, monkeypatch):
    """Der Kern des Dauerschadens: fotoseitig vollständig, tonseitig leer
    — und damit für JEDEN Sweep unsichtbar. Ein einziges leeres
    xeno-canto-Ergebnis war endgültig."""
    svc = _service(
        tmp_path, {"Phoenicurus ochruros": _cached("Phoenicurus ochruros", recordings=[])}
    )
    assert svc.photo_backfill_candidates() == []  # der Fotoblick sieht nichts
    assert svc.audio_backfill_candidates() == ["Phoenicurus ochruros"]

    spawned: list[str] = []
    monkeypatch.setattr(svc, "_spawn_fetch", spawned.append)
    assert svc.sweep_photo_backfill(budget=10) == {"pending": 1}
    assert spawned == ["Phoenicurus ochruros"]


def test_a_dossier_that_already_sings_is_left_alone(tmp_path, monkeypatch):
    svc = _service(
        tmp_path,
        {"Turdus merula": _cached("Turdus merula", recordings=[{"file_url": "x.mp3"}])},
    )
    assert svc.audio_backfill_candidates() == []
    spawned: list[str] = []
    monkeypatch.setattr(svc, "_spawn_fetch", spawned.append)
    assert svc.sweep_photo_backfill(budget=10) == {"pending": 0}
    assert spawned == []


def test_the_audio_backfill_rotates_longest_unchecked_first(tmp_path):
    """Sonst mahlt jeder Tick auf denselben paar Namen herum."""
    svc = _service(
        tmp_path,
        {
            "B b": _cached("B b", recordings=[], checked="2026-09-03T00:00:00"),
            "A a": _cached("A a", recordings=[], checked="2026-01-01T00:00:00"),
            "N n": _cached("N n", recordings=[], checked=None),
        },
    )
    assert svc.audio_backfill_candidates() == ["N n", "A a", "B b"]


def test_a_never_fetched_dossier_stays_with_the_normal_path(tmp_path):
    """`wikipedia_fetched_at is None` heißt: der reguläre Fetch schuldet
    diesem Eintrag noch einen Versuch — hier doppelt nachzufassen würde
    ihn nur zweimal anstoßen (gleiche Regel wie beim Foto-Sweep)."""
    d = _cached("A a", recordings=[])
    d["wikipedia_fetched_at"] = None
    assert _service(tmp_path, {"A a": d}).audio_backfill_candidates() == []


def test_a_missed_fetch_records_that_it_was_asked(tmp_path, monkeypatch):
    """„nie gefragt" und „gefragt, nichts bekommen" sind verschiedene
    Zustände — das Panel formuliert sie verschieden, und der Sweep
    sortiert danach. Vorher wurde nur ein TREFFER gestempelt."""
    svc = BirdDossierService(tmp_path / "bird_dossiers.json")
    monkeypatch.setattr("app.bird_dossiers._fetch_wikipedia", lambda latin: None)
    monkeypatch.setattr("app.bird_dossiers._fetch_photos", lambda wiki, latin, want=3: [])
    monkeypatch.setattr("app.bird_dossiers._fetch_bird_audio", lambda wiki, latin: [])
    monkeypatch.setattr(svc, "_spawn_fetch", lambda latin: None)

    svc._create_placeholder("Phoenicurus ochruros", "Hausrotschwanz")
    svc._fetch_worker("Phoenicurus ochruros")

    d = svc.get_dossier("Phoenicurus ochruros")
    assert d["recordings"] == []
    assert d["audio_fetched_at"] is None  # kein Treffer
    assert d["audio_checked_at"]  # aber gefragt wurde


# ── Die ehrliche Leerstelle im Panel ─────────────────────────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_panel_says_which_kind_of_silence_this_is():
    """Ohne Aufnahme lieferte `audioListHtml` einen leeren String — der
    Block verschwand spurlos, und genau das las der Operator als „die
    Funktion gibt es nicht". Kein Play-Knopf (das wäre eine tote
    Schaltfläche), aber eine Zeile, die den Zustand benennt."""
    out = _js(
        """
        const h = await import(JS + '/sichtungen/_hero-overlay.js');
        const base = { common_name_de: 'Hausrotschwanz', latin: 'Phoenicurus ochruros' };
        console.log(JSON.stringify({
          pending: h.audioListHtml(base),
          checked: h.audioListHtml({ ...base, audio_checked_at: '2026-09-04T00:00:00' }),
          withAudio: h.audioListHtml({ ...base, audio_url: 'https://x.invalid/song.mp3' }),
        }));
        """
    )
    assert "noch nicht geladen" in out["pending"]
    assert "sd-audio-el" not in out["pending"]  # kein toter Player
    assert "Keine Vogelstimme verfügbar" in out["checked"]
    # Mit Aufnahme bleibt alles wie gehabt: Player-Zeile plus Quellenangabe.
    assert "sd-audio-el" in out["withAudio"]
    assert "xeno-canto.org" in out["withAudio"]
    assert "noch nicht geladen" not in out["withAudio"]
