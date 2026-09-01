"""fetch_second_photo — the media-list filtering logic that picks a
second, distinct dossier photo (bird_dossiers_fetch.py). Stubs
`_rate_limited_get` so no real network call happens, mirroring
test_bird_dossiers.py's own monkeypatch-the-network-boundary approach.

Covers: the skip list (maps/icons/logos/SVGs), deduping against the
primary thumbnail, missing/malformed input, and picking the URL up from
`srcset` when `original` is absent.
"""

from __future__ import annotations

from app.bird_dossiers_fetch import fetch_second_photo

_WIKI = {
    "title": "Rotkehlchen",
    "thumbnail": {"source": "https://upload.example.invalid/thumb/robin-front.jpg"},
    "content_urls": {"desktop": {"page": "https://de.wikipedia.org/wiki/Rotkehlchen"}},
}


def _media_list(items):
    return {"items": items}


def test_picks_the_first_suitable_distinct_image(monkeypatch):
    monkeypatch.setattr(
        "app.bird_dossiers_fetch._rate_limited_get",
        lambda url: _media_list(
            [
                {"type": "image", "original": {"source": "https://x.invalid/robin-front.jpg"}},
                {"type": "image", "original": {"source": "https://x.invalid/robin-side.jpg"}},
            ]
        ),
    )
    assert fetch_second_photo(_WIKI) == "https://x.invalid/robin-side.jpg"


def test_skips_maps_icons_logos_and_svgs(monkeypatch):
    monkeypatch.setattr(
        "app.bird_dossiers_fetch._rate_limited_get",
        lambda url: _media_list(
            [
                {"type": "image", "original": {"source": "https://x.invalid/Distribution_map.png"}},
                {"type": "image", "original": {"source": "https://x.invalid/Wiki_icon.png"}},
                {"type": "image", "original": {"source": "https://x.invalid/Commons-logo.svg"}},
                {"type": "image", "original": {"source": "https://x.invalid/robin-bath.jpg"}},
            ]
        ),
    )
    assert fetch_second_photo(_WIKI) == "https://x.invalid/robin-bath.jpg"


def test_skips_a_duplicate_of_the_primary_thumbnail(monkeypatch):
    monkeypatch.setattr(
        "app.bird_dossiers_fetch._rate_limited_get",
        lambda url: _media_list(
            [
                {"type": "image", "original": {"source": "https://x.invalid/robin-front.jpg"}},
                {"type": "image", "original": {"source": "https://x.invalid/robin-nest.jpg"}},
            ]
        ),
    )
    assert fetch_second_photo(_WIKI) == "https://x.invalid/robin-nest.jpg"


def test_falls_back_to_srcset_when_original_is_missing(monkeypatch):
    monkeypatch.setattr(
        "app.bird_dossiers_fetch._rate_limited_get",
        lambda url: _media_list(
            [{"type": "image", "srcset": [{"src": "//x.invalid/robin-flight.jpg"}]}]
        ),
    )
    assert fetch_second_photo(_WIKI) == "https://x.invalid/robin-flight.jpg"


def test_skips_non_image_items_and_returns_none_for_a_video_only_list(monkeypatch):
    monkeypatch.setattr(
        "app.bird_dossiers_fetch._rate_limited_get",
        lambda url: _media_list(
            [{"type": "video", "original": {"source": "https://x.invalid/song.ogv"}}]
        ),
    )
    assert fetch_second_photo(_WIKI) is None


def test_returns_none_when_the_media_list_fetch_fails(monkeypatch):
    monkeypatch.setattr("app.bird_dossiers_fetch._rate_limited_get", lambda url: None)
    assert fetch_second_photo(_WIKI) is None


def test_returns_none_for_falsy_wiki_input():
    assert fetch_second_photo(None) is None
    assert fetch_second_photo({}) is None


def test_returns_none_when_content_urls_are_missing():
    assert fetch_second_photo({"title": "X"}) is None
