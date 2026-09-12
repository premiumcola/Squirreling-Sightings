"""„Wie gut ist das Profil schon?" — die Messung und ihre drei Fallen.

„Vielleicht das Halbieren, die Menge, und die eine Menge mit der anderen
erkennen und sagen, wie gut Du's schon erkennst."

Die Rechnung selbst ist einfach. Was sie wertlos macht, wenn man es
falsch baut, ist es nicht, und genau das steht hier:

  * geteilt wird nach CLIP, nicht nach Probe — sonst prüft man zwei
    Ausschnitte derselben Sekunde gegeneinander und meldet 100 %;
  * geprüft wird gegen ALLE Profile — sonst hat ein Profil, das auf
    jeden zeigt, eine perfekte Quote;
  * ein Profil, das noch nicht geprüft werden KANN, bekommt keine Zahl —
    eine erfundene 0 % sähe aus wie ein schlechtes statt wie ein
    ungeprüftes Profil.
"""

from __future__ import annotations

from app.cat_identity import REGIONS, crop_region, region_hashes, sample_hash
from app.identity_quality import MIN_EVENTS, compare_regions, evaluate, split_by_event

#: Zwei Hash-Familien, die weit auseinanderliegen. Innerhalb einer
#: Familie kippt jeweils ein Bit — Abstand 1 bis 2, also klar unter jeder
#: sinnvollen Schwelle; zwischen den Familien sind es 32.
_A = ["0000000000000000", "0000000000000001", "0000000000000002", "0000000000000004"]
_B = ["ffffffff00000000", "ffffffff00000001", "ffffffff00000002", "ffffffff00000004"]


def _profile(name, hashes, events, *, anonymous=False):
    return {
        "name": name,
        "anonymous": anonymous,
        "samples": [
            {"h": h, "event_id": e, "relpath": f"{e}-{i}.jpg"}
            for i, (h, e) in enumerate(zip(hashes, events))
        ],
    }


# ── die Aufteilung ──────────────────────────────────────────────────────


def test_the_split_runs_along_clips_not_along_samples():
    """DIE Falle. Zwei Ausschnitte aus demselben Clip sind derselbe
    Mensch in derselben Sekunde — landen sie in verschiedenen Hälften,
    misst die Prüfung sich selbst."""
    samples = [
        {"h": _A[0], "event_id": "e1"},
        {"h": _A[1], "event_id": "e1"},
        {"h": _A[2], "event_id": "e2"},
        {"h": _A[3], "event_id": "e2"},
    ]
    memory, probe = split_by_event(samples)
    assert {s["event_id"] for s in memory} == {"e1"}
    assert {s["event_id"] for s in probe} == {"e2"}


def test_one_clip_alone_cannot_be_split():
    samples = [{"h": h, "event_id": "e1"} for h in _A]
    memory, probe = split_by_event(samples)
    assert probe == []
    assert len(memory) == len(_A)


def test_samples_without_a_clip_count_as_one_appearance():
    """Altbestand ohne Herkunft. Vorsichtige Lesart: sie könnten alle aus
    demselben Auftritt stammen, also wird daraus nichts gemessen."""
    samples = [{"h": h, "event_id": ""} for h in _A]
    assert split_by_event(samples)[1] == []


def test_clips_alternate_between_the_halves():
    """Nicht vorne/hinten geschnitten: die Proben stehen nach Zeit, und
    ein glatter Schnitt legte alle alten Auftritte ins Gedächtnis und
    alle neuen in die Prüfung — dann misst man den Kleiderwechsel."""
    samples = [{"h": _A[0], "event_id": f"e{i}"} for i in range(4)]
    memory, probe = split_by_event(samples)
    assert [s["event_id"] for s in memory] == ["e0", "e2"]
    assert [s["event_id"] for s in probe] == ["e1", "e3"]


# ── die Auswertung ──────────────────────────────────────────────────────


def test_a_profile_that_recognises_itself_scores_full_marks():
    p = _profile("Anna", _A, ["e1", "e1", "e2", "e2"])
    out = evaluate([p], threshold=10)["profiles"]["Anna"]
    assert out["state"] == "gemessen"
    assert out["checked"] == 2
    assert out["hits"] == 2
    assert out["rate"] == 1.0
    assert out["confused"] == 0


def test_a_profile_with_one_clip_gets_no_number_at_all():
    """Keine erfundene 0 %: das Profil ist nicht schlecht, es ist
    ungeprüft — und die Oberfläche sagt dann, was zu tun ist."""
    p = _profile("Anna", _A, ["e1"] * 4)
    out = evaluate([p], threshold=10)["profiles"]["Anna"]
    assert out["state"] == "zu-wenig"
    assert "rate" not in out


def test_a_confusion_with_another_person_is_counted_as_such():
    """Die zweite Hälfte der Frage: erkennt das Profil seine Bilder NUR
    wieder? Hier trägt „Bo" Proben aus Annas Familie, also zeigt der
    nächste Nachbar auf den Falschen."""
    anna = _profile("Anna", _A[:2], ["e1", "e2"])
    bo = _profile("Bo", [_A[2], _A[3]], ["e3", "e4"])
    out = evaluate([anna, bo], threshold=10)["profiles"]
    assert out["Anna"]["confused"] + out["Bo"]["confused"] > 0


def test_two_genuinely_different_people_do_not_confuse_each_other():
    anna = _profile("Anna", _A, ["e1", "e1", "e2", "e2"])
    bo = _profile("Bo", _B, ["e3", "e3", "e4", "e4"])
    out = evaluate([anna, bo], threshold=10)["profiles"]
    assert out["Anna"]["rate"] == 1.0
    assert out["Bo"]["rate"] == 1.0
    assert out["Anna"]["confused"] == 0
    assert out["Bo"]["confused"] == 0


def test_a_sample_nobody_recognises_is_neither_hit_nor_confusion():
    """Über der Schwelle erkennt das Verfahren schlicht nichts wieder.
    Das als Verwechslung zu zählen wäre falsch — es hat ja auf niemanden
    gezeigt."""
    anna = {
        "name": "Anna",
        "samples": [
            {"h": _A[0], "event_id": "e1"},
            {"h": _B[0], "event_id": "e2"},
        ],
    }
    out = evaluate([anna], threshold=4)["profiles"]["Anna"]
    assert out["checked"] == 1
    assert out["hits"] == 0
    assert out["confused"] == 0


def test_the_total_adds_up_across_profiles():
    anna = _profile("Anna", _A, ["e1", "e1", "e2", "e2"])
    bo = _profile("Bo", _B, ["e3", "e3", "e4", "e4"])
    total = evaluate([anna, bo], threshold=10)["total"]
    assert total["checked"] == 4
    assert total["hits"] == 4
    assert total["rate"] == 1.0


def test_nothing_to_measure_reports_no_rate_rather_than_zero():
    total = evaluate([], threshold=10)["total"]
    assert total["checked"] == 0
    assert total["rate"] is None


def test_legacy_profiles_without_samples_still_evaluate():
    """Profile aus der Zeit vor den Proben haben nur eine flache
    `hashes`-Liste. Sie dürfen die Auswertung nicht sprengen — sie sind
    nur nicht messbar."""
    out = evaluate([{"name": "Alt", "hashes": _A}], threshold=10)["profiles"]["Alt"]
    assert out["state"] == "zu-wenig"


def test_the_minimum_is_two_appearances():
    assert MIN_EVENTS == 2


# ── ganze Person / Oberkörper / Kopf ────────────────────────────────────


def test_the_head_is_a_geometric_slice_not_a_detection():
    """Es gibt in diesem Projekt kein Gesichtsmodell — „Kopf" ist das
    obere Viertel des Personen-Rechtecks, horizontal eingezogen. Das
    festzuhalten ist wichtiger als die Zahlen: wer es für Erkennung
    hält, erwartet etwas, das nicht geliefert wird."""
    import numpy as np

    img = np.zeros((200, 80, 3), dtype=np.uint8)
    assert crop_region(img, "full").shape[:2] == (200, 80)
    assert crop_region(img, "upper").shape[:2] == (90, 80)
    head = crop_region(img, "head")
    assert head.shape[0] < 60 and head.shape[1] < 80, "Kopf ist oben UND schmaler"


def test_a_crop_too_small_for_a_region_yields_no_hash_for_it():
    """Ein 9×8-Gradient über zwölf Pixel ist Rauschen. Lieber keine Zahl
    als eine erfundene."""
    import numpy as np

    rng = np.random.default_rng(3)
    tiny = rng.integers(0, 255, size=(30, 20, 3), dtype=np.uint8)
    out = region_hashes(tiny)
    assert "full" in out
    assert "head" not in out


def test_the_full_region_keeps_living_under_its_old_key():
    """`h` ist der Schlüssel, auf dem der Abgleich seit jeher läuft. Ihn
    umzubenennen hätte jede bestehende Registry entwertet, ohne etwas zu
    verbessern."""
    sample = {"h": "aaaa", "hr": {"head": "bbbb"}}
    assert sample_hash(sample, "full") == "aaaa"
    assert sample_hash(sample, "head") == "bbbb"
    assert sample_hash(sample, "upper") is None


def test_a_region_without_hashes_is_reported_as_unmeasured_not_as_zero():
    """Proben von vor der Umstellung haben nur den vollen Hash. Für Kopf
    und Oberkörper gibt es dann nichts zu rechnen — und eine 0 % wäre
    eine Aussage über den Bereich, die niemand gemessen hat."""
    p = _profile("Anna", _A, ["e1", "e1", "e2", "e2"])
    out = compare_regions([p], threshold=10)
    assert out["full"]["checked"] == 2
    assert out["head"]["checked"] == 0
    assert out["head"]["rate"] is None


def test_each_region_is_measured_on_its_own_hashes():
    anna = {
        "name": "Anna",
        "samples": [
            {"h": _A[0], "hr": {"head": _B[0]}, "event_id": "e1"},
            {"h": _A[1], "hr": {"head": _B[1]}, "event_id": "e2"},
        ],
    }
    out = compare_regions([anna], threshold=10)
    assert out["full"]["checked"] == 1 and out["full"]["hits"] == 1
    assert out["head"]["checked"] == 1 and out["head"]["hits"] == 1


def test_every_region_is_named_in_the_comparison():
    out = compare_regions([], threshold=10)
    assert set(out) == set(REGIONS)
