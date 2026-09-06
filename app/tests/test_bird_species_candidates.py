"""Die Zweit- und Drittkandidaten überleben die Klassifikation.

„Frage Vogel und dann wenn ja: Nachfrage Vogel 'Elster' oder 2.xxx
3.zzz???"

Beide Backends holten schon immer die besten DREI Kandidaten und liefen
sie durch, um den ersten mit deutschem Namen zu finden — und warfen die
anderen beiden dann weg. Die Nachfrage kostet also keine einzige
zusätzliche Inferenz; sie hört nur auf, das Ergebnis zu verkleinern.
"""

from __future__ import annotations

from app.camera_runtime._motion import _resolve_species_candidates
from app.detectors._types import Detection
from app.detectors.bird_species import stamp_species


class _Ranked:
    """Ein Klassifikator, der die neue Form kann."""

    available = True

    def __init__(self, ranked):
        self._ranked = ranked

    def classify_crop_ranked(self, _crop):
        return list(self._ranked)


class _Legacy:
    """Einer, der nur das alte Tripel kann — jeder Stub im Testbestand."""

    available = True

    def __init__(self, triple):
        self._triple = triple

    def classify_crop(self, _crop):
        return self._triple


def _det() -> Detection:
    return Detection(label="bird", score=0.57, bbox=(0, 0, 10, 10))


ELSTER = [
    {"name": "Elster", "latin": "Pica pica", "score": 0.77},
    {"name": "Rabenkrähe", "latin": "Corvus corone", "score": 0.11},
    {"name": "Eichelhäher", "latin": "Garrulus glandarius", "score": 0.04},
]


def test_der_beste_kandidat_wird_wie_bisher_gestempelt():
    det = _det()
    out = stamp_species(_Ranked(ELSTER), object(), det)
    assert out[0] == "Elster"
    assert det.species == "Elster"
    assert det.species_latin == "Pica pica"
    assert round(det.species_score, 2) == 0.77


def test_die_zweit_und_drittkandidaten_bleiben_erhalten():
    det = _det()
    stamp_species(_Ranked(ELSTER), object(), det)
    assert [c["name"] for c in det.species_candidates] == [
        "Elster",
        "Rabenkrähe",
        "Eichelhäher",
    ]


def test_ein_alter_klassifikator_funktioniert_unveraendert():
    # DIE FALLE, vor der die Kartierung gewarnt hat: fünf Aufrufer
    # entpacken ein 3-Tupel, und vier davon fangen jede Exception
    # wortlos ab — eine geänderte Rückgabeform hätte die Artbestimmung
    # still abschalten können statt zu krachen.
    det = _det()
    out = stamp_species(_Legacy(("Kohlmeise", "Parus major", 0.63)), object(), det)
    assert out[0] == "Kohlmeise"
    assert det.species == "Kohlmeise"
    # Ein einzelner Kandidat ist eine Liste mit einem Eintrag, keine leere.
    assert [c["name"] for c in det.species_candidates] == ["Kohlmeise"]


def test_ohne_treffer_wird_nichts_gestempelt():
    det = _det()
    assert stamp_species(_Ranked([]), object(), det) is None
    assert det.species is None
    assert det.species_candidates == []


def test_das_ereignis_nimmt_die_kandidaten_des_besten_vogels():
    # Zwei Vögel im Bild: die Auswahl gehört zu DEM, der den Kopf-Namen
    # geliefert hat. Drei Kandidaten von drei verschiedenen Vögeln wären
    # eine Wahl, die niemand treffen kann.
    stark = _det()
    stamp_species(_Ranked(ELSTER), object(), stark)
    schwach = _det()
    stamp_species(
        _Ranked([{"name": "Buchfink", "latin": "Fringilla coelebs", "score": 0.31}]),
        object(),
        schwach,
    )
    got = _resolve_species_candidates([schwach, stark])
    assert [c["name"] for c in got] == ["Elster", "Rabenkrähe", "Eichelhäher"]


def test_ein_ereignis_ohne_vogel_hat_keine_kandidaten():
    assert _resolve_species_candidates([_det()]) == []
    assert _resolve_species_candidates([]) == []


def test_die_kandidaten_stehen_NICHT_im_erkennungs_vertrag():
    # `to_dict()` ist das Ereignis-JSON, und archivierte Ereignisse
    # behalten es Byte für Byte — derselbe Grund, aus dem `track_id`
    # dort fehlt. Die Kandidaten reisen auf Ereignis-Ebene.
    det = _det()
    stamp_species(_Ranked(ELSTER), object(), det)
    assert "species_candidates" not in det.to_dict()
    assert det.to_dict()["species"] == "Elster"
