"""`fetch_photos` — how the dossier's reference photos are ASSEMBLED
across sources (bird_dossiers_fetch.py). Stubs `_rate_limited_get` so no
real network call happens, mirroring test_bird_dossiers.py's own
monkeypatch-the-network-boundary approach.

The per-item filtering rules (maps, icons, SVGs, spectrograms, dupes)
live in the pure `select_photo_urls` and are covered exhaustively in
test_bird_dossier_photos.py. What this module covers is the orchestration
around it: the summary thumbnail leads, the article's media list fills up
the rest, and the EN article for the same taxon is pulled in as a second
source when the first one can't reach the target — which is what turned a
one-photo dossier into a two-or-three-photo one.
"""

from __future__ import annotations

from app.bird_dossiers_fetch import fetch_photos

_WIKI = {
    "title": "Rotkehlchen",
    "thumbnail": {"source": "https://upload.example.invalid/thumb/robin-front.jpg"},
    "content_urls": {"desktop": {"page": "https://de.wikipedia.org/wiki/Rotkehlchen"}},
}

_EN_SUMMARY = {
    "title": "European robin",
    "thumbnail": {"source": "https://upload.example.invalid/thumb/robin-en.jpg"},
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/European_robin"}},
}


def _img(url: str) -> dict:
    return {"type": "image", "original": {"source": url}}


def _router(monkeypatch, routes: dict):
    """Stub the network boundary with a substring→payload table. Any URL
    that matches no key resolves to None, i.e. "that fetch failed"."""

    def _get(url: str):
        for needle, payload in routes.items():
            if needle in url:
                return payload
        return None

    monkeypatch.setattr("app.bird_dossiers_fetch._rate_limited_get", _get)


def test_the_summary_thumbnail_leads_and_the_media_list_follows(monkeypatch):
    _router(
        monkeypatch,
        {
            "de.wikipedia.org/api/rest_v1/page/media-list": {
                "items": [_img("https://x.invalid/robin-side.jpg")]
            }
        },
    )
    assert fetch_photos(_WIKI, "Erithacus rubecula", want=2) == [
        "https://upload.example.invalid/thumb/robin-front.jpg",
        "https://x.invalid/robin-side.jpg",
    ]


def test_stops_at_want_without_touching_the_english_article(monkeypatch):
    _router(
        monkeypatch,
        {
            "de.wikipedia.org/api/rest_v1/page/media-list": {
                "items": [_img("https://x.invalid/a.jpg"), _img("https://x.invalid/b.jpg")]
            },
            # Present but must never be consulted — the DE side already fills
            # the quota, and every extra request costs a rate-lock second.
            "en.wikipedia.org/api/rest_v1/page/summary": _EN_SUMMARY,
        },
    )
    got = fetch_photos(_WIKI, "Erithacus rubecula", want=3)
    assert got == [
        "https://upload.example.invalid/thumb/robin-front.jpg",
        "https://x.invalid/a.jpg",
        "https://x.invalid/b.jpg",
    ]


def test_falls_back_to_the_english_article_when_german_runs_dry(monkeypatch):
    """A short DE stub with a single image used to leave the dossier with
    one photo and a placeholder next to it. The EN article for the same
    taxon rarely uses the same picture set."""
    _router(
        monkeypatch,
        {
            "de.wikipedia.org/api/rest_v1/page/media-list": {"items": []},
            "en.wikipedia.org/api/rest_v1/page/summary": _EN_SUMMARY,
            "en.wikipedia.org/api/rest_v1/page/media-list": {
                "items": [_img("https://x.invalid/robin-winter.jpg")]
            },
        },
    )
    assert fetch_photos(_WIKI, "Erithacus rubecula", want=3) == [
        "https://upload.example.invalid/thumb/robin-front.jpg",
        "https://upload.example.invalid/thumb/robin-en.jpg",
        "https://x.invalid/robin-winter.jpg",
    ]


def test_the_english_article_never_repeats_a_photo_the_german_one_gave(monkeypatch):
    shared = "https://x.invalid/robin-shared.jpg"
    _router(
        monkeypatch,
        {
            "de.wikipedia.org/api/rest_v1/page/media-list": {"items": [_img(shared)]},
            "en.wikipedia.org/api/rest_v1/page/summary": _EN_SUMMARY,
            "en.wikipedia.org/api/rest_v1/page/media-list": {
                "items": [_img(shared), _img("https://x.invalid/robin-new.jpg")]
            },
        },
    )
    got = fetch_photos(_WIKI, "Erithacus rubecula", want=4)
    assert got.count(shared) == 1
    assert "https://x.invalid/robin-new.jpg" in got


def test_an_english_only_species_is_not_walked_twice(monkeypatch):
    """When the summary already CAME from the EN wiki, its media list has
    been walked once — re-walking the same article adds nothing."""
    en_wiki = dict(_EN_SUMMARY)
    _router(
        monkeypatch,
        {
            "en.wikipedia.org/api/rest_v1/page/media-list": {
                "items": [_img("https://x.invalid/one.jpg")]
            },
            "en.wikipedia.org/api/rest_v1/page/summary": en_wiki,
        },
    )
    got = fetch_photos(en_wiki, "Erithacus rubecula", want=3)
    assert got == [
        "https://upload.example.invalid/thumb/robin-en.jpg",
        "https://x.invalid/one.jpg",
    ]


def test_a_species_with_one_usable_image_keeps_exactly_one(monkeypatch):
    """No placeholder is ever substituted — the panel renders one box and
    the backfill sweep tries again later."""
    _router(monkeypatch, {})
    assert fetch_photos(_WIKI, "Erithacus rubecula", want=3) == [
        "https://upload.example.invalid/thumb/robin-front.jpg"
    ]


def test_a_disambiguation_page_is_not_used_as_a_source(monkeypatch):
    _router(
        monkeypatch,
        {
            "de.wikipedia.org/api/rest_v1/page/media-list": {"items": []},
            "en.wikipedia.org/api/rest_v1/page/summary": {"type": "disambiguation"},
        },
    )
    assert fetch_photos(_WIKI, "Erithacus rubecula", want=3) == [
        "https://upload.example.invalid/thumb/robin-front.jpg"
    ]


def test_returns_empty_for_falsy_wiki_input():
    assert fetch_photos(None, "Erithacus rubecula") == []
    assert fetch_photos({}, "Erithacus rubecula") == []


def test_a_summary_without_content_urls_still_yields_its_thumbnail(monkeypatch):
    _router(monkeypatch, {})
    thin = {"title": "X", "thumbnail": {"source": "https://x.invalid/only.jpg"}}
    assert fetch_photos(thin, "Genus species", want=3) == ["https://x.invalid/only.jpg"]
