"""Two reference photos have to be two different photographs.

„vögel sollen aus einer unterschiedlichen perspektive sein! … das ist
grad nicht so und vögel nicht abschneiden!" — the Mehlschwalbe's dossier
showed one identical picture twice, because the same Commons file
arrives under two names: the summary endpoint serves a scaled
``320px-Delichon_urbicum.jpg`` and the media list the original
``Delichon_urbicum.jpg``. Comparing raw basenames called those two
different files.

The second half of that message is a CSS matter and is pinned in
test_bird_hero_frame.py.
"""

from __future__ import annotations

from app.bird_dossiers_fetch import (
    _seed_variant,
    photo_identity,
    photo_variant_key,
    select_photo_urls,
)

COMMONS = "https://upload.wikimedia.org/wikipedia/commons"
THUMB = f"{COMMONS}/thumb/9/9a/Delichon_urbicum.jpg/320px-Delichon_urbicum.jpg"
ORIGINAL = f"{COMMONS}/9/9a/Delichon_urbicum.jpg"


def _items(*urls: str) -> list[dict]:
    return [{"type": "image", "original": {"source": u}} for u in urls]


# ── identity: one file, however it is served ─────────────────────────


def test_thumbnail_and_original_are_one_file():
    """The exact Mehlschwalbe case."""
    assert photo_identity(THUMB) == photo_identity(ORIGINAL) == "delichon_urbicum.jpg"


def test_render_prefixes_are_stripped():
    for prefix in ("320px-", "1024px-", "lossy-page1-800px-", "thumbnail-64px-"):
        url = f"{COMMONS}/x/{prefix}Parus_caeruleus.jpg"
        assert photo_identity(url) == "parus_caeruleus.jpg", prefix


def test_percent_encoding_does_not_split_a_file():
    a = f"{COMMONS}/x/Erithacus%20rubecula.jpg"
    b = f"{COMMONS}/x/Erithacus rubecula.jpg"
    assert photo_identity(a) == photo_identity(b)


def test_identity_keeps_genuinely_different_files_apart():
    assert photo_identity(f"{COMMONS}/x/Delichon_urbicum_flight.jpg") != photo_identity(ORIGINAL)


# ── variant: one shot, several derivatives ───────────────────────────


def test_crop_and_original_are_the_same_shot():
    assert photo_variant_key(f"{COMMONS}/x/Parus_caeruleus_2_(cropped).jpg") == photo_variant_key(
        f"{COMMONS}/x/Parus_caeruleus.jpg"
    )


def test_sequence_numbers_collapse():
    keys = {
        photo_variant_key(f"{COMMONS}/x/Carduelis_carduelis{suffix}.jpg")
        for suffix in ("", "_1", "_2", "-03", " (4)")
    }
    assert len(keys) == 1, f"same shoot split into {keys}"


def test_a_different_pose_is_not_a_variant():
    """The rule must not be so eager that it throws away real views."""
    assert photo_variant_key(f"{COMMONS}/x/Carduelis_carduelis_flight.jpg") != photo_variant_key(
        f"{COMMONS}/x/Carduelis_carduelis.jpg"
    )


# ── the selector, end to end ─────────────────────────────────────────


def test_the_primary_photo_is_never_offered_twice():
    seen = {photo_identity(THUMB)}
    _seed_variant(seen, THUMB)
    picked = select_photo_urls(_items(ORIGINAL), seen, 2)
    assert picked == [], "the media list's original repeated the summary thumbnail"


def test_the_second_slot_is_a_different_perspective():
    seen = {photo_identity(THUMB)}
    _seed_variant(seen, THUMB)
    picked = select_photo_urls(
        _items(
            ORIGINAL,  # same file
            f"{COMMONS}/x/Delichon_urbicum_2.jpg",  # same shoot
            f"{COMMONS}/x/Delichon_urbicum_flight.jpg",  # a real second view
            f"{COMMONS}/x/Delichon_urbicum_nest.jpg",
        ),
        seen,
        2,
    )
    names = [u.rsplit("/", 1)[-1] for u in picked]
    assert names == ["Delichon_urbicum_flight.jpg", "Delichon_urbicum_nest.jpg"]


def test_skip_words_still_apply():
    """The new keys must not have loosened the map/spectrogram filter."""
    picked = select_photo_urls(
        _items(
            f"{COMMONS}/x/Delichon_urbicum_distribution_map.jpg",
            f"{COMMONS}/x/Delichon_urbicum_spectrogram.png",
            f"{COMMONS}/x/Delichon_urbicum_perched.jpg",
        ),
        set(),
        3,
    )
    assert [u.rsplit("/", 1)[-1] for u in picked] == ["Delichon_urbicum_perched.jpg"]


def test_identity_and_variant_keys_cannot_collide():
    """Both live in one set; an identity keeps its extension, a variant
    never has one, so they occupy disjoint namespaces."""
    url = f"{COMMONS}/x/Parus_caeruleus.jpg"
    assert photo_identity(url).endswith(".jpg")
    assert "." not in photo_variant_key(url)


# ── repairing what is already on disk ────────────────────────────────


def _store_with(tmp_path, dossier: dict):
    """A dossier store on disk, loaded through the real service."""
    import json

    from app.bird_dossiers import BirdDossierService

    path = tmp_path / "bird_dossiers.json"
    path.write_text(
        json.dumps({"schema": 1, "dossiers": {dossier["latin"]: dossier}}),
        encoding="utf-8",
    )
    return BirdDossierService(path)


def test_a_stored_duplicate_is_collapsed_on_load(tmp_path):
    """The fix must reach dossiers written BEFORE it.

    Every dossier in the operator's store already holds the thumbnail
    and the original of one file. Waiting for the backfill sweep to
    reach each species would leave the same bird shown twice for days.
    """
    svc = _store_with(
        tmp_path,
        {
            "latin": "Delichon urbicum",
            "photo_urls": [THUMB, ORIGINAL],
            "wikipedia_thumb_url": THUMB,
            "wikipedia_thumb_url_2": ORIGINAL,
            "wikipedia_fetched_at": "2026-09-01T10:00:00",
        },
    )
    d = svc.data["dossiers"]["Delichon urbicum"]
    assert d["photo_urls"] == [THUMB], "the duplicate survived the load"
    assert d["wikipedia_thumb_url_2"] is None, (
        "the legacy mirror still points at the dropped duplicate — the "
        "frontend falls back to it and would show the pair again"
    )


def test_the_repair_makes_the_species_a_backfill_candidate(tmp_path):
    """Collapsing 2→1 has to be followed by fetching a real second view,
    or the fix trades a duplicate for a missing photo."""
    svc = _store_with(
        tmp_path,
        {
            "latin": "Delichon urbicum",
            "photo_urls": [THUMB, ORIGINAL],
            "wikipedia_fetched_at": "2026-09-01T10:00:00",
        },
    )
    assert "Delichon urbicum" in svc.photo_backfill_candidates()


def test_distinct_photos_are_left_alone(tmp_path):
    """The repair must not touch a dossier that is already correct."""
    good = [f"{COMMONS}/x/A_perched.jpg", f"{COMMONS}/x/A_flight.jpg"]
    svc = _store_with(tmp_path, {"latin": "A b", "photo_urls": list(good)})
    assert svc.data["dossiers"]["A b"]["photo_urls"] == good
