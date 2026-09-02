"""Reference-photo selection + backfill for the species dossier.

The operator's report: the second photo slot showed the app's generic
bird silhouette instead of a photograph ("irgend 'n random roter Vogel,
macht keinen Sinn"). Two halves to the fix — the frontend never renders
a placeholder box (see sichtungen/_tests/hero-overlay.test.js), and this
side actually finds two to three real photographs per species.

`select_photo_urls` is pure (it takes an already-fetched media-list
array), so every filtering rule is tested here without a network stub.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.bird_dossiers import BirdDossierService
from app.bird_dossiers_fetch import PHOTO_TARGET, select_photo_urls


def _img(name: str, *, kind: str = "image") -> dict:
    return {"type": kind, "original": {"source": f"https://upload.invalid/x/{name}"}}


# ── select_photo_urls ────────────────────────────────────────────────────


def test_picks_photos_in_order_up_to_want():
    items = [_img("a.jpg"), _img("b.jpg"), _img("c.jpg"), _img("d.jpg")]
    got = select_photo_urls(items, set(), 3)
    assert got == [
        "https://upload.invalid/x/a.jpg",
        "https://upload.invalid/x/b.jpg",
        "https://upload.invalid/x/c.jpg",
    ]


def test_skips_svgs_and_non_photo_formats():
    items = [_img("range.svg"), _img("clip.ogv"), _img("frame.tif"), _img("real.jpg")]
    assert select_photo_urls(items, set(), 3) == ["https://upload.invalid/x/real.jpg"]


def test_skips_maps_icons_and_housekeeping_graphics():
    items = [
        _img("Verbreitung_Rotkehlchen.png"),
        _img("Distribution_map.jpg"),
        _img("Commons-logo.png"),
        _img("Speaker_Icon.png"),
        _img("real_bird.jpg"),
    ]
    assert select_photo_urls(items, set(), 3) == ["https://upload.invalid/x/real_bird.jpg"]


def test_skips_spectrograms_which_are_ordinary_pngs():
    """A xeno-canto spectrogram is a real .png and would otherwise pass
    every format check — it is a picture of a SOUND, not of the bird."""
    items = [_img("Erithacus_spectrogram.png"), _img("Erithacus_perched.jpg")]
    assert select_photo_urls(items, set(), 3) == ["https://upload.invalid/x/Erithacus_perched.jpg"]


def test_skips_names_already_seen_and_records_its_own_picks():
    """`skip_names` is threaded through several media lists, so a picked
    file must be added to it — otherwise the EN article contributes the
    same photo the DE one already did."""
    seen = {"primary.jpg"}
    items = [_img("primary.jpg"), _img("second.jpg")]
    got = select_photo_urls(items, seen, 3)
    assert got == ["https://upload.invalid/x/second.jpg"]
    assert "second.jpg" in seen


def test_non_image_items_are_ignored():
    items = [_img("song.mp3", kind="audio"), _img("bird.jpg")]
    assert select_photo_urls(items, set(), 3) == ["https://upload.invalid/x/bird.jpg"]


def test_protocol_relative_urls_are_made_absolute():
    items = [{"type": "image", "original": {"source": "//upload.invalid/x/bird.jpg"}}]
    assert select_photo_urls(items, set(), 1) == ["https://upload.invalid/x/bird.jpg"]


def test_falls_back_to_the_largest_srcset_entry():
    items = [
        {
            "type": "image",
            "srcset": [{"src": "//u.invalid/small.jpg"}, {"src": "//u.invalid/large.jpg"}],
        }
    ]
    assert select_photo_urls(items, set(), 1) == ["https://u.invalid/large.jpg"]


def test_wants_zero_returns_nothing():
    assert select_photo_urls([_img("a.jpg")], set(), 0) == []


# ── storing + mirroring ──────────────────────────────────────────────────


def _blank(latin: str = "Erithacus rubecula") -> dict:
    return BirdDossierService._blank_dossier(
        latin,
        "Rotkehlchen",
        first_seen_at=None,
        first_seen_event_id=None,
        first_seen_camera_id=None,
        sighting_count=0,
    )


_WIKI = {
    "extract": "Das Rotkehlchen ist ein Singvogel.",
    "content_urls": {"desktop": {"page": "https://de.wikipedia.invalid/wiki/Rotkehlchen"}},
}


def test_apply_wikipedia_stores_the_list_and_mirrors_two_scalars():
    d = _blank()
    BirdDossierService._apply_wikipedia(
        d, _WIKI, ["a.jpg", "b.jpg", "c.jpg"], "2026-09-02T10:00:00"
    )
    assert d["photo_urls"] == ["a.jpg", "b.jpg", "c.jpg"]
    assert d["wikipedia_thumb_url"] == "a.jpg"
    assert d["wikipedia_thumb_url_2"] == "b.jpg"


def test_a_single_photo_leaves_the_second_mirror_empty_not_a_placeholder():
    d = _blank()
    BirdDossierService._apply_wikipedia(d, _WIKI, ["only.jpg"], "2026-09-02T10:00:00")
    assert d["photo_urls"] == ["only.jpg"]
    assert d["wikipedia_thumb_url_2"] is None


def test_a_thinner_refetch_never_shrinks_an_already_complete_dossier():
    """A transient media-list miss must not cost a dossier photos it
    already had — the backfill sweep re-fetches these repeatedly."""
    d = _blank()
    BirdDossierService._apply_wikipedia(d, _WIKI, ["a.jpg", "b.jpg"], "2026-09-02T10:00:00")
    BirdDossierService._apply_wikipedia(d, _WIKI, [], "2026-09-03T10:00:00")
    assert d["photo_urls"] == ["a.jpg", "b.jpg"]
    assert d["wikipedia_thumb_url"] == "a.jpg"


# ── backfill candidate selection ─────────────────────────────────────────


def _service(tmp_path: Path, dossiers: dict) -> BirdDossierService:
    p = tmp_path / "bird_dossiers.json"
    p.write_text(json.dumps({"schema": 1, "dossiers": dossiers}), encoding="utf-8")
    return BirdDossierService(p)


def _cached(latin: str, photos: list, fetched_at: str | None) -> dict:
    d = _blank(latin)
    d["photo_urls"] = photos
    d["wikipedia_fetched_at"] = fetched_at
    return d


def test_backfill_picks_dossiers_short_of_the_photo_target(tmp_path):
    svc = _service(
        tmp_path,
        {
            "A a": _cached("A a", ["1", "2", "3"], "2026-09-01T00:00:00"),
            "B b": _cached("B b", ["1"], "2026-09-01T00:00:00"),
        },
    )
    assert svc.photo_backfill_candidates() == ["B b"]


def test_backfill_skips_dossiers_that_were_never_fetched_at_all(tmp_path):
    """`wikipedia_fetched_at is None` already means the normal fetch path
    owes this one a try — re-spawning here would just double up."""
    svc = _service(tmp_path, {"A a": _cached("A a", [], None)})
    assert svc.photo_backfill_candidates() == []


def test_backfill_drains_oldest_fetch_first(tmp_path):
    svc = _service(
        tmp_path,
        {
            "New n": _cached("New n", ["1"], "2026-09-05T00:00:00"),
            "Old o": _cached("Old o", ["1"], "2026-01-01T00:00:00"),
            "Mid m": _cached("Mid m", ["1"], "2026-05-01T00:00:00"),
        },
    )
    assert svc.photo_backfill_candidates() == ["Old o", "Mid m", "New n"]


def test_backfill_respects_its_budget(tmp_path, monkeypatch):
    svc = _service(
        tmp_path,
        {f"S{i} s": _cached(f"S{i} s", ["1"], f"2026-01-0{i}T00:00:00") for i in range(1, 5)},
    )
    spawned: list[str] = []
    monkeypatch.setattr(svc, "_spawn_fetch", spawned.append)
    assert svc.sweep_photo_backfill(budget=2) == {"pending": 2}
    assert spawned == ["S1 s", "S2 s"]


def test_a_dossier_cached_before_photo_urls_existed_is_a_candidate(tmp_path):
    """The real migration case: entries on disk carry the two legacy
    scalar fields and no `photo_urls` key at all."""
    legacy = _blank("Legacy l")
    legacy.pop("photo_urls")
    legacy["wikipedia_thumb_url"] = "one.jpg"
    legacy["wikipedia_fetched_at"] = "2026-08-01T00:00:00"
    svc = _service(tmp_path, {"Legacy l": legacy})
    assert svc.photo_backfill_candidates() == ["Legacy l"]


def test_photo_target_is_what_the_panel_can_show():
    assert PHOTO_TARGET == 3
