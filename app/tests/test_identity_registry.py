"""Umbenennen, Zusammenführen, Vergessen — und wovon ein Profil ein
Gesicht bekommt.

„Dort würde ich auch die Personen dann benennen und neue Gesichter
vorhandenen Personen zuordnen."

Die Registry hielt bis hierher nur Namen und dHashes. Wer Gesichter
einzeln benennt, legt zwangsläufig zweimal dieselbe Person an — also
braucht es einen Weg zurück, und der ist das Umbenennen AUF einen schon
vergebenen Namen. Dass das zusammenführt statt abzulehnen, ist der Kern
dieser Datei.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.cat_identity import MAX_PROFILE_CROPS, IdentityRegistry


def _crop(seed: int) -> np.ndarray:
    """Ein Bild, dessen Hash sich von jedem anderen Seed unterscheidet."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(48, 32, 3), dtype=np.uint8)


@pytest.fixture()
def registry(tmp_path):
    return IdentityRegistry(tmp_path / "person_registry.json")


def test_the_first_crop_creates_the_profile(registry):
    """Es gibt bewusst kein „Person anlegen" davor — ein Name entsteht,
    indem man ihn benutzt."""
    assert registry.register_crop("Anna", _crop(1))
    assert [p["name"] for p in registry.list_profiles()] == ["Anna"]
    assert len(registry.get_profile("Anna")["hashes"]) == 1


def test_the_profile_keeps_the_picture_the_hash_came_from(registry):
    """Ohne Verweis ist ein Profil ein Name und sechzehn Hexziffern —
    nichts, woran man eine Person wiedererkennt."""
    registry.register_crop("Anna", _crop(1), relpath="a/1.jpg")
    assert registry.get_profile("Anna")["crops"] == ["a/1.jpg"]


def test_the_newest_picture_leads_and_the_stack_stays_short(registry):
    """Der erste Verweis ist das Avatar, also muss der neueste vorn
    stehen. Und die Registry ist eine Hash-Liste, kein Album."""
    for i in range(MAX_PROFILE_CROPS + 3):
        registry.register_crop("Anna", _crop(i), relpath=f"a/{i}.jpg")
    crops = registry.get_profile("Anna")["crops"]
    assert crops[0] == f"a/{MAX_PROFILE_CROPS + 2}.jpg"
    assert len(crops) == MAX_PROFILE_CROPS


def test_the_same_picture_twice_does_not_grow_the_stack(registry):
    registry.register_crop("Anna", _crop(1), relpath="a/1.jpg")
    registry.register_crop("Anna", _crop(2), relpath="a/1.jpg")
    assert registry.get_profile("Anna")["crops"] == ["a/1.jpg"]


def test_renaming_onto_a_free_name_is_just_a_rename(registry):
    registry.register_crop("Ana", _crop(1), relpath="a/1.jpg")
    assert registry.rename_profile("Ana", "Anna")
    assert registry.get_profile("Ana") is None
    assert registry.get_profile("Anna")["crops"] == ["a/1.jpg"]


def test_renaming_onto_a_taken_name_MERGES(registry):
    """Zwei Profile für eine Person ist das normale Ergebnis davon,
    Gesichter einzeln zu benennen. Das Zusammenführen ist kein
    Nebeneffekt, es ist der Zweck."""
    registry.register_crop("Anna", _crop(1), relpath="a/1.jpg")
    registry.register_crop("Anna B", _crop(2), relpath="b/2.jpg")
    assert registry.rename_profile("Anna B", "Anna")
    assert [p["name"] for p in registry.list_profiles()] == ["Anna"]
    merged = registry.get_profile("Anna")
    assert len(merged["hashes"]) == 2
    assert set(merged["crops"]) == {"a/1.jpg", "b/2.jpg"}


def test_a_merge_keeps_the_whitelist_if_either_side_had_it(registry):
    """Die Whitelist unterdrückt Alarme. Sie beim Zusammenführen zu
    verlieren wäre ein stiller Rückfall in Meldungen, die der Betreiber
    abgestellt hat."""
    registry.register_crop("Anna", _crop(1))
    registry.register_crop("Anna B", _crop(2), whitelisted=True)
    registry.rename_profile("Anna B", "Anna")
    assert registry.get_profile("Anna")["whitelisted"] is True


def test_a_merge_keeps_the_stack_short(registry):
    for i in range(MAX_PROFILE_CROPS):
        registry.register_crop("Anna", _crop(i), relpath=f"a/{i}.jpg")
    for i in range(MAX_PROFILE_CROPS):
        registry.register_crop("Anna B", _crop(100 + i), relpath=f"b/{i}.jpg")
    registry.rename_profile("Anna B", "Anna")
    assert len(registry.get_profile("Anna")["crops"]) == MAX_PROFILE_CROPS


def test_renaming_refuses_the_cases_that_would_lose_a_profile(registry):
    registry.register_crop("Anna", _crop(1))
    assert not registry.rename_profile("Anna", "")
    assert not registry.rename_profile("Anna", "   ")
    assert not registry.rename_profile("Anna", "Anna")
    assert not registry.rename_profile("Unbekannt", "Anna")
    assert [p["name"] for p in registry.list_profiles()] == ["Anna"]


def test_forgetting_a_profile_leaves_the_others_alone(registry):
    registry.register_crop("Anna", _crop(1))
    registry.register_crop("Bo", _crop(2))
    assert registry.delete_profile("Anna")
    assert [p["name"] for p in registry.list_profiles()] == ["Bo"]
    assert not registry.delete_profile("Anna")


def test_every_change_survives_a_reload(registry, tmp_path):
    """Alles hier schreibt sofort — sonst wäre eine Zuordnung nach einem
    Neustart weg, und genau das ist die Arbeit, die niemand zweimal
    machen will."""
    registry.register_crop("Ana", _crop(1), relpath="a/1.jpg")
    registry.rename_profile("Ana", "Anna")
    again = IdentityRegistry(tmp_path / "person_registry.json")
    assert again.get_profile("Anna")["crops"] == ["a/1.jpg"]
