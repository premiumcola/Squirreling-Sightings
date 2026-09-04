"""Bird song without a credential.

„Ich will die Vogelgezwitscher wieso findest du nix das kann doch nicht
sein! Überleg dir was wie wir das einmalig bekommen!"

He was right that it could not be. Every dossier already fetches the
species' Wikipedia media list for its reference photos, and that list
carries the article's own recording — `select_photo_urls` was dropping
it on its second line (`if item.get("type") != "image": continue`) and
the code then went to xeno-canto, which has demanded a per-account API
key since 2025-10-10. Nobody had one, so every dossier in the archive
said "Keine Vogelstimme verfügbar" while the answer sat in a response we
had already paid for.

Verified against the live APIs while writing this:

    Phoenicurus ochruros → …/Singing_Phoenicurus_ochruros.ogg.mp3
                           200 audio/mpeg 56433 B · Waithamai · CC BY-SA 4.0
    Erithacus rubecula   → …/Erithacus_rubecula.ogg.mp3
                           200 audio/mpeg 430684 B · CC BY-SA 3.0
    Columba palumbus     → genuinely no audio in the article

These tests are offline: the network shape is captured above, and what
is pinned here is the parsing and the URL derivation.
"""

from __future__ import annotations

import pytest

from app.bird_audio_commons import (
    article_title_of,
    audio_title_from_media_list,
    build_recording,
    commons_audio,
    transcoded_mp3_url,
)

COMMONS = "https://upload.wikimedia.org/wikipedia/commons"


# ── finding the recording in a list we already fetch ─────────────────


def test_the_audio_item_is_found_among_the_photos():
    items = [
        {"type": "image", "title": "Datei:A.jpg"},
        {"type": "audio", "title": "Datei:Singing_Phoenicurus_ochruros.ogg"},
        {"type": "image", "title": "Datei:B.jpg"},
    ]
    assert audio_title_from_media_list(items) == "File:Singing_Phoenicurus_ochruros.ogg"


@pytest.mark.parametrize("prefix", ["Datei:", "File:", "Bild:", "datei:", "  File: "])
def test_every_wiki_namespace_prefix_normalises(prefix):
    """de returns "Datei:", en returns "File:", and the Commons API
    wants "File:" — a dossier built from the German article must not
    resolve to a different query than one built from the English."""
    items = [{"type": "audio", "title": f"{prefix}X.ogg"}]
    assert audio_title_from_media_list(items) == "File:X.ogg"


def test_a_species_with_no_recording_reports_none():
    """Columba palumbus really has none. That is not a failure and must
    not be dressed up as one."""
    assert audio_title_from_media_list([{"type": "image", "title": "Datei:A.jpg"}]) is None
    assert audio_title_from_media_list([]) is None
    assert audio_title_from_media_list(None) is None


def test_an_audio_item_without_a_title_is_skipped():
    items = [{"type": "audio"}, {"type": "audio", "title": "Datei:Real.ogg"}]
    assert audio_title_from_media_list(items) == "File:Real.ogg"


# ── the URL that actually plays on an iPhone ─────────────────────────


def test_an_ogg_becomes_the_commons_mp3_transcode():
    """Safari does not play Ogg Vorbis. Linking the original would load
    a file and stay silent, which is worse than saying there is none."""
    orig = f"{COMMONS}/4/4f/Singing_Phoenicurus_ochruros.ogg"
    assert transcoded_mp3_url(orig) == (
        f"{COMMONS}/transcoded/4/4f/Singing_Phoenicurus_ochruros.ogg/"
        "Singing_Phoenicurus_ochruros.ogg.mp3"
    )


def test_the_tracking_query_is_stripped_before_deriving():
    """The imageinfo API appends ?utm_source=… to the url it returns, and
    it lands in the middle of the derived path — this produced a 404 on
    the first pass and is exactly the kind of thing a person reads past."""
    orig = f"{COMMONS}/4/4f/A.ogg?utm_source=commons.wikimedia.org&utm_content=original"
    assert transcoded_mp3_url(orig) == f"{COMMONS}/transcoded/4/4f/A.ogg/A.ogg.mp3"


@pytest.mark.parametrize("ext", [".mp3", ".m4a", ".aac", ".wav", ".MP3"])
def test_an_already_playable_upload_is_left_alone(ext):
    """There is no transcode of a file that needs none, so deriving one
    would point at a 404."""
    assert transcoded_mp3_url(f"{COMMONS}/1/12/A{ext}") is None


@pytest.mark.parametrize("url", ["", None, "https://example.org/a.ogg", f"{COMMONS}/"])
def test_a_url_that_is_not_a_commons_upload_yields_none(url):
    assert transcoded_mp3_url(url) is None


# ── credit, because these are CC-licensed ────────────────────────────


def test_the_recording_carries_its_recordist_and_licence():
    rec = build_recording(
        "File:Singing_Phoenicurus_ochruros.ogg",
        {
            "url": f"{COMMONS}/4/4f/Singing_Phoenicurus_ochruros.ogg",
            "extmetadata": {
                "Artist": {"value": '<a href="/wiki/User:W">Waithamai</a>'},
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
            },
        },
    )
    assert rec["recordist"] == "Waithamai", "the HTML link must not reach the panel"
    assert rec["license_name"] == "CC BY-SA 4.0"
    assert rec["license_url"].startswith("https://creativecommons.org/")
    assert rec["file_url"].endswith(".mp3")


def test_html_entities_in_the_credit_are_decoded():
    rec = build_recording(
        "File:A.ogg",
        {"url": f"{COMMONS}/1/12/A.ogg", "extmetadata": {"Artist": {"value": "M&amp;M"}}},
    )
    assert rec["recordist"] == "M&M"


def test_a_file_with_no_metadata_still_credits_the_source():
    """CC compliance is not optional, so an unknown author still points
    at the file page, where the licence and the author actually live."""
    rec = build_recording("File:A.ogg", {"url": f"{COMMONS}/1/12/A.ogg"})
    assert rec["recordist"] == "Wikimedia Commons"
    assert "commons.wikimedia.org/wiki/File:A.ogg" in rec["license_url"]


def test_the_shape_matches_what_the_panel_reads():
    """sichtungen/_hero-overlay.js::_recordingsOf reads these four keys
    and branches on nothing else, so a Commons recording and a
    xeno-canto one render through one path."""
    rec = build_recording("File:A.ogg", {"url": f"{COMMONS}/1/12/A.ogg"})
    assert {"file_url", "type_de", "recordist", "license_url"} <= set(rec)


def test_a_record_with_no_url_is_refused():
    assert build_recording("File:A.ogg", {}) is None


# ── the lookup, with the network stubbed ─────────────────────────────


def test_the_lookup_asks_commons_and_shapes_the_answer():
    seen = {}

    def getter(url):
        seen["url"] = url
        return {
            "query": {
                "pages": [{"imageinfo": [{"url": f"{COMMONS}/4/4f/Singing.ogg"}]}],
            }
        }

    rec = commons_audio("File:Singing.ogg", getter)
    assert rec["file_url"].endswith("Singing.ogg.mp3")
    assert "commons.wikimedia.org/w/api.php" in seen["url"]
    assert "extmetadata" in seen["url"], "without it there is no credit to show"


@pytest.mark.parametrize(
    "answer",
    [None, {}, {"query": {}}, {"query": {"pages": []}}, {"query": {"pages": [{}]}}],
)
def test_every_shape_of_empty_answer_is_survivable(answer):
    assert commons_audio("File:A.ogg", lambda _u: answer) is None


def test_no_title_means_no_request_at_all():
    def getter(_url):  # pragma: no cover - must not run
        raise AssertionError("asked Commons about nothing")

    assert commons_audio("", getter) is None


# ── the article title, for the media-list call ───────────────────────


def test_the_article_title_comes_out_of_the_page_url():
    assert article_title_of("https://de.wikipedia.org/wiki/Hausrotschwanz") == "Hausrotschwanz"


@pytest.mark.parametrize("url", ["", None, "https://de.wikipedia.org/", "not a url"])
def test_an_unusable_page_url_yields_none(url):
    assert article_title_of(url) is None
