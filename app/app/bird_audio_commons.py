"""Bird song from Wikimedia Commons — the source that needs no key.

„Ich will die Vogelgezwitscher wieso findest du nix das kann doch nicht
sein! Überleg dir was wie wir das einmalig bekommen!"

He is right that it cannot be. Every dossier already fetches the
species' Wikipedia media list to pick its reference photos, and that
list carries the article's audio too — we were filtering it out one line
into ``select_photo_urls`` (``if item.get("type") != "image": continue``)
and then going to xeno-canto, which since 2025-10-10 refuses to answer
without a per-account API key nobody had set. The answer was in a
response we were already paying for.

Measured against the live API while writing this:

    de:Hausrotschwanz   20 images, 1 video, 1 audio
    de:Rotkehlchen      24 images, 1 video, 1 audio
    de:Blaumeise        28 images,          1 audio
    en:Black redstart   11 images,          1 audio

WHY NOT JUST LINK THE .ogg. Commons stores these as Ogg Vorbis and
Safari does not play Ogg — on the operator's iPhone the file would load
and stay silent, which is worse than the honest "keine Vogelstimme".
Commons auto-transcodes every audio file to MP3 at a DERIVED path:

    …/commons/4/4f/Singing_Phoenicurus_ochruros.ogg
    …/commons/transcoded/4/4f/Singing_Phoenicurus_ochruros.ogg/
        Singing_Phoenicurus_ochruros.ogg.mp3

Both verified 200 / audio/mpeg before this module was written. The
transcode is used when the original is not already a browser-native
format, and the original is kept when it is (mp3/wav/m4a uploads exist
too).

ATTRIBUTION IS NOT OPTIONAL. These recordings are CC-licensed and the
panel already shows recordist + licence for the xeno-canto ones; the
same two fields are pulled from Commons' ``extmetadata`` so a Commons
recording is credited exactly as well.

Best-effort like every other fetch in this package: any failure returns
None and the dossier keeps its honest empty state.
"""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import quote, urlparse

log = logging.getLogger("app.bird_dossiers")

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"

#: Formats a browser plays without help. Anything else goes through the
#: Commons transcode.
_NATIVE_AUDIO_EXT = (".mp3", ".m4a", ".aac", ".wav")

#: Strip the wiki's namespace prefix — the REST media list returns
#: "Datei:…" on de, "File:…" on en, and the Commons API wants "File:".
_NS_PREFIX = re.compile(r"^\s*(datei|file|bild|image)\s*:\s*", re.I)


def audio_title_from_media_list(items: list) -> str | None:
    """The first real audio file in a REST media list, as ``File:Name``.

    ``leadImage`` items and anything without a title are skipped. The
    list is already ordered the way the article is, so the first hit is
    the recording the article itself leads with.
    """
    for item in items or []:
        if item.get("type") != "audio":
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue
        return "File:" + _NS_PREFIX.sub("", title)
    return None


def transcoded_mp3_url(original_url: str) -> str | None:
    """The Commons MP3 transcode of an upload URL, or None.

    Derived, not queried: Commons publishes transcodes at a fixed path
    beside the original, so this costs no extra request. Returns None for
    a file that is already browser-native (nothing to transcode to) or a
    URL that is not a Commons upload path.
    """
    if not original_url:
        return None
    clean = original_url.split("?", 1)[0]
    if clean.lower().endswith(_NATIVE_AUDIO_EXT):
        return None
    marker = "/commons/"
    if marker not in clean:
        return None
    head, tail = clean.split(marker, 1)
    name = tail.rsplit("/", 1)[-1]
    if not name:
        return None
    return f"{head}{marker}transcoded/{tail}/{name}.mp3"


def _plain(value: str | None) -> str | None:
    """Commons' extmetadata carries HTML. The panel renders text."""
    if not value:
        return None
    text = re.sub(r"<[^>]+>", "", str(value))
    text = html.unescape(text).strip()
    return text or None


def _file_page_url(file_title: str) -> str:
    """The Commons description page — where the licence and the author
    are, for a file whose metadata did not come back.

    The namespace colon is left unescaped: ``/wiki/File:A.ogg`` is the
    canonical spelling and the one a person can read in a status bar
    before clicking it. ``%3A`` resolves too, but this link exists to be
    checked by a human."""
    return "https://commons.wikimedia.org/wiki/" + quote(file_title.replace(" ", "_"), safe=":/")


def build_recording(file_title: str, info: dict) -> dict | None:
    """Shape one Commons imageinfo record the way the panel reads it.

    The keys mirror the xeno-canto rows exactly (``file_url``,
    ``type_de``, ``recordist``, ``license_url``) so the frontend needs no
    branch for where a recording came from — see ``_recordingsOf`` in
    sichtungen/_hero-overlay.js.
    """
    original = (info.get("url") or "").split("?", 1)[0]
    if not original:
        return None
    playable = transcoded_mp3_url(original) or original
    meta = info.get("extmetadata") or {}
    recordist = _plain((meta.get("Artist") or {}).get("value"))
    licence = _plain((meta.get("LicenseShortName") or {}).get("value"))
    return {
        "file_url": playable,
        # Named for what it is. The operator sees this word next to the
        # play button, and "Aufnahme" alone would not say that the
        # recording is the article's own rather than one of ours.
        "type_de": "Gesang (Wikimedia Commons)",
        "recordist": recordist or "Wikimedia Commons",
        # The FILE PAGE, not the raw licence text: it carries the licence,
        # the author and the source in one place a person can check.
        "license_url": (meta.get("LicenseUrl") or {}).get("value") or _file_page_url(file_title),
        "license_name": licence,
    }


def commons_audio(file_title: str, getter) -> dict | None:
    """Resolve ``File:Name.ogg`` to a playable, credited recording.

    ``getter`` is injected rather than imported so this module stays
    testable without the network AND so the caller's existing
    rate limiter is the one that runs — the spec's one-request-per-second
    budget covers Commons too, and a second limiter here would quietly
    double the rate.
    """
    if not file_title:
        return None
    url = (
        f"{_COMMONS_API}?action=query&format=json&formatversion=2"
        f"&prop=imageinfo&iiprop=url%7Cmime%7Cextmetadata"
        f"&titles={quote(file_title)}"
    )
    data = getter(url)
    if not data:
        return None
    pages = ((data.get("query") or {}).get("pages")) or []
    if not pages:
        return None
    infos = pages[0].get("imageinfo") or []
    if not infos:
        return None
    rec = build_recording(file_title, infos[0])
    if rec:
        log.info("[dossiers] Vogelstimme über Wikimedia Commons: %s", file_title)
    return rec


def article_title_of(page_url: str) -> str | None:
    """The article title a REST page URL points at, for the media list."""
    try:
        path = urlparse(page_url or "").path
    except Exception:
        return None
    if not path or "/wiki/" not in path:
        return None
    return path.split("/wiki/", 1)[1] or None
