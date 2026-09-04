"""Network + parsing helpers for `bird_dossiers.py` — the Wikipedia
summary fetch and the Xeno-canto recordings fetch, split out once
`bird_dossiers.py` crossed the 500-line file ceiling (CLAUDE.md). Plain
sibling module, not a package conversion, so no relative-import shift
to audit (see the refactor-gotchas skill) — `bird_dossiers.py` just
imports the two public functions below.

External APIs are deliberately best-effort here too: every function
returns None / an empty list on any failure rather than raising, so a
network hiccup never poisons the camera pipeline that (indirectly, via
BirdDossierService) calls into this module.
"""

from __future__ import annotations

import json as _json_mod
import logging
import os
import re
import threading
import time
from urllib.parse import quote, unquote, urlparse

from .bird_audio_commons import article_title_of as _article_title_of
from .bird_audio_commons import audio_title_from_media_list as _audio_title_from_media_list
from .bird_audio_commons import commons_audio as _commons_audio

log = logging.getLogger("app.bird_dossiers")

# Xeno-canto API v3 requires a per-account `key` parameter (the free v2
# endpoint was retired 2025-10-10). The key is read PER CALL, not
# snapshotted at import: a module-level `os.environ[...]` made the gate
# invisible (no log line, no way to see it in a test without reloading
# the module) and froze the value at boot. Without a key the audio fetch
# is skipped — but said once, so a missing extra has a findable cause.
#
# NO LONGER FATAL for bird song: Wikimedia Commons carries the article's
# own recording and needs no credential at all (bird_audio_commons.py).
# xeno-canto is now the enrichment, not the source, which is why this
# dropped from a WARNING to an INFO — it stopped describing a feature
# that does not work.
_XC_API_URL = "https://xeno-canto.org/api/3/recordings"
_xc_key_warned = [False]


def _xc_api_key() -> str:
    """Current xeno-canto API key, "" when unconfigured (warned once)."""
    key = os.environ.get("XENO_CANTO_API_KEY", "").strip()
    if not key and not _xc_key_warned[0]:
        _xc_key_warned[0] = True
        log.info(
            "[dossiers] XENO_CANTO_API_KEY nicht gesetzt — Vogelstimmen kommen von "
            "Wikimedia Commons. Ein Key von xeno-canto.org/account bringt zusätzlich "
            "mehrere Aufnahmen je Art mit Ruf-/Gesang-Unterscheidung."
        )
    return key


# Filter ladder for the recordings query, strictest first. q:A is
# "Quality A", len:5-15 picks clips short enough to play inline in the
# panel — but a species whose only uploads are longer or unrated used to
# come back empty FOREVER under that one strict query. Each rung is
# tried in turn and the first one with a hit wins, so the common case
# still gets a short quality-A clip and the rare one gets *something*.
_XC_FILTER_LADDER = ("q:A len:5-15", "q:A", "")

# The MediaWiki REST summary endpoint. Returns title, extract, thumbnail,
# content_urls, and a couple of cross-language hints. Works on every
# language wiki — we try DE first, EN as fallback.
_WIKI_SUMMARY_URL_DE = "https://de.wikipedia.org/api/rest_v1/page/summary/{latin}"
_WIKI_SUMMARY_URL_EN = "https://en.wikipedia.org/api/rest_v1/page/summary/{latin}"

_HTTP_TIMEOUT = 5.0
_USER_AGENT = (
    "squirreling-sightings bird-dossier-builder (https://github.com/premiumcola/cam-manager)"
)

# ── Rate-limit lock ────────────────────────────────────────────────────────
# The spec mandates ≤1 outgoing request/sec to Wikipedia + Xeno-canto.
# A single global lock + a "next allowed slot" timestamp is the simplest
# bound: every fetch grabs the lock, sleeps until the slot opens, fires
# its request, then sets the next slot to now+1 s. Multiple species
# fetched in the same minute (a real sighting or a prebuild sweep tick)
# serialise behind this; nothing is dropped.
_rate_lock = threading.Lock()
_next_request_slot = [0.0]


def _rate_limited_get(url: str) -> dict | None:
    """GET `url`, return parsed JSON or None on any failure (404, timeout,
    network error, malformed JSON). Never raises. Caller is expected to
    treat None as "fetch failed, try again later"."""
    import urllib.request as _ur

    with _rate_lock:
        sleep_for = max(0.0, _next_request_slot[0] - time.time())
        if sleep_for > 0:
            time.sleep(sleep_for)
        _next_request_slot[0] = time.time() + 1.0
    try:
        req = _ur.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
        with _ur.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
            if r.status >= 400:
                return None
            return _json_mod.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        log.debug("[dossiers] GET %s failed: %s", url, e)
        return None


def _strip_subspecies(latin: str) -> str:
    """Drop the third name in a trinomial — "Erithacus rubecula rubecula"
    → "Erithacus rubecula". Wikipedia normally indexes species at the
    binomial, so the trinomial 404s but the binomial fallback hits.
    Returns the input unchanged when it isn't a trinomial."""
    parts = latin.split()
    return f"{parts[0]} {parts[1]}" if len(parts) >= 3 else latin


def fetch_wikipedia(latin: str) -> dict | None:
    """Try DE summary first, EN fallback, subspecies-stripped fallback.

    Returns None when all three lookups fail. The caller stores None
    fields rather than the literal None — see
    BirdDossierService._apply_wikipedia."""
    candidates = [latin]
    stripped = _strip_subspecies(latin)
    if stripped != latin:
        candidates.append(stripped)
    for cand in candidates:
        for url_tmpl in (_WIKI_SUMMARY_URL_DE, _WIKI_SUMMARY_URL_EN):
            url = url_tmpl.format(latin=quote(cand))
            data = _rate_limited_get(url)
            if not data:
                continue
            if data.get("type") == "disambiguation":
                continue
            extract = data.get("extract") or ""
            if not extract.strip():
                continue
            return data
    return None


# How many reference photos a dossier shows at most. Two lets the
# operator compare their own camera frame against a second view; a third
# helps for species with a strong male/female or summer/winter
# difference. More than three doesn't fit the panel.
PHOTO_TARGET = 3

# Words in a filename that mark a media-list item as NOT a photograph of
# the animal: distribution maps, UI icons, Wikimedia housekeeping
# graphics, and — the subtle one — xeno-canto style spectrogram images,
# which are ordinary PNGs and would otherwise sail through as "a photo".
_PHOTO_SKIP_WORDS = (
    "icon",
    "map",
    "karte",
    "verbreitung",
    "distribution",
    "range",
    "logo",
    "commons",
    "spectrogram",
    "sonogram",
    "spektrogramm",
    "signature",
    "skelett",
    "skeleton",
    "egg",
    "ei_",
)

# Only real raster photo formats. An allowlist rather than an .svg
# blacklist: media lists also carry .tif, .gif, .webm poster frames and
# .ogv thumbnails, none of which belong in the hero.
_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Render prefixes Commons puts in front of a scaled file name.
_RENDER_PREFIX = re.compile(r"^(?:lossy-)?(?:page\d+-)?(?:thumbnail-)?\d+px-")

# Markers that say "this is a derivative of another file in the same
# list" rather than a separate photograph.
_DERIVATIVE_MARKERS = (
    "(cropped)",
    "_cropped",
    "-cropped",
    "cropped",
    "_crop",
    "-crop",
    "_edit",
    "-edit",
    "retouched",
    "_adjusted",
    "denoise",
    "_flipped",
    "_mirror",
)

# A trailing sequence number — `_1`, `-02`, ` (3)`. Same shoot, same
# pose, next frame.
_TRAILING_SEQ = re.compile(r"[ _-]*\(?\d{1,3}\)?$")


def photo_identity(url: str) -> str:
    """The Commons file a URL points at, independent of how it is served.

    The same photograph reaches us under two different basenames: the
    summary endpoint hands out a scaled thumbnail
    ``…/thumb/9/9a/Delichon_urbicum.jpg/320px-Delichon_urbicum.jpg``
    while the media list hands out the original
    ``…/9/9a/Delichon_urbicum.jpg``. Comparing raw basenames therefore
    said "different file" and the Mehlschwalbe's dossier showed the very
    same picture twice, side by side.

    Strips the ``NNNpx-`` render prefix (and the ``lossy-page1-`` and
    ``thumbnail-`` variants Commons puts in front of it) and percent-
    decodes, so both spellings collapse to one identity.
    """
    name = unquote(url.rsplit("/", 1)[-1]).lower()
    prev = None
    while prev != name:
        prev = name
        name = _RENDER_PREFIX.sub("", name)
    return name


def photo_variant_key(url: str) -> str:
    """The SUBJECT of a photo — one step coarser than its identity.

    „vögel sollen aus einer unterschiedlichen perspektive sein!" A media
    list routinely carries several derivatives of one shot: the original,
    a crop, a retouched pass, a numbered sequence from the same session.
    They are distinct files, so identity alone lets all of them through
    and the operator gets the same bird in the same pose twice — which is
    useless next to their own camera frame.

    Dropping the extension, the trailing sequence number and the common
    derivative markers folds those back together, so the second slot has
    to come from a genuinely different photograph.
    """
    stem = photo_identity(url).rsplit(".", 1)[0]
    for marker in _DERIVATIVE_MARKERS:
        stem = stem.replace(marker, "")
    # Alternate stripping separators and a trailing number until the
    # stem stops changing. One pass is not enough: removing "(cropped)"
    # from `parus_caeruleus_2_(cropped)` leaves a trailing underscore
    # that hides the `_2` from the sequence pattern, so the crop and its
    # original would still read as two different shots.
    prev = None
    while prev != stem:
        prev = stem
        stem = _TRAILING_SEQ.sub("", stem.strip(" _-"))
    return stem.strip(" _-")


def _seed_variant(seen: set[str], url: str) -> None:
    """Record a picked URL's variant key so later candidates from the
    same shot are rejected. Separate from the identity `seen.add` at each
    call site only because an empty key must not be stored."""
    variant = photo_variant_key(url)
    if variant:
        seen.add(variant)


def _photo_url_of(item: dict) -> str | None:
    """Best available source URL for one media-list item, protocol-fixed.
    None when the item carries no usable source."""
    srcset = item.get("srcset") or []
    original = (item.get("original") or {}).get("source") or (
        srcset[-1].get("src") if srcset else None
    )
    if not original:
        return None
    return "https:" + original if original.startswith("//") else original


def select_photo_urls(items: list, skip_names: set[str], want: int) -> list[str]:
    """Pick up to `want` distinct photo URLs out of a REST media-list's
    `items` array. Pure — no I/O — so the filtering rules are unit
    testable without touching the network.

    Rejects anything that isn't an image item, isn't a raster photo
    format, matches a `_PHOTO_SKIP_WORDS` marker, or whose filename is
    already in `skip_names` (the primary thumbnail, plus everything an
    earlier article already contributed). `skip_names` is MUTATED as
    picks are made, so a caller can thread one set through several
    media lists and never get the same file twice.

    Two levels of sameness are rejected, not one. `photo_identity`
    catches the same Commons file arriving under a thumbnail name and an
    original name — that is what put one identical Mehlschwalbe beside
    another. `photo_variant_key` then catches the crop / retouch /
    next-frame derivatives of a shot already picked, because the point
    of the second slot is a DIFFERENT view of the bird, not a second
    copy of the same pose.

    `skip_names` carries both kinds of key. They cannot collide: an
    identity always keeps its extension, a variant key never has one.
    """
    out: list[str] = []
    for item in items or []:
        if len(out) >= want:
            break
        if item.get("type") != "image":
            continue
        url = _photo_url_of(item)
        if not url:
            continue
        name = photo_identity(url)
        if not name.endswith(_PHOTO_EXTS):
            continue
        if name in skip_names:
            continue
        if any(w in name for w in _PHOTO_SKIP_WORDS):
            continue
        variant = photo_variant_key(url)
        if variant and variant in skip_names:
            continue
        skip_names.add(name)
        if variant:
            skip_names.add(variant)
        out.append(url)
    return out


def _media_list_photos(page_url: str, title: str, skip_names: set[str], want: int) -> list[str]:
    """Fetch one article's media list and select photos from it. Empty
    list on any failure — the caller just moves on to the next source."""
    host = urlparse(page_url or "").netloc
    if not host or not title or want <= 0:
        return []
    data = _rate_limited_get(f"https://{host}/api/rest_v1/page/media-list/{quote(title)}")
    if not data:
        return []
    return select_photo_urls(data.get("items") or [], skip_names, want)


def fetch_photos(wiki: dict | None, latin: str, want: int = PHOTO_TARGET) -> list[str]:
    """Up to `want` reference photos of the species, best first.

    Starts from the summary's own thumbnail, then walks the article's
    media list for further views. If that article alone can't fill the
    quota — common for a short DE stub — the EN article for the same
    latin name is tried as a second source, since the two wikis rarely
    illustrate a species with the same picture set.

    Returns [] when `wiki` is falsy. A species that genuinely yields
    only one usable image simply gets a one-entry list; the caller
    stores exactly that and a later fetch can still grow it (see
    BirdDossierService.sweep_photo_backfill) — a placeholder is never
    substituted for a missing photo."""
    if not wiki:
        return []
    seen: set[str] = set()
    photos: list[str] = []
    primary = (wiki.get("thumbnail") or {}).get("source") or ""
    if primary:
        seen.add(photo_identity(primary))
        _seed_variant(seen, primary)
        photos.append(primary)
    page_url = ((wiki.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
    photos += _media_list_photos(page_url, wiki.get("title") or "", seen, want - len(photos))
    if len(photos) >= want:
        return photos[:want]
    # Second source: the EN article for the same taxon. The latin name is
    # the reliable cross-wiki key — the DE title is not.
    en = _rate_limited_get(_WIKI_SUMMARY_URL_EN.format(latin=quote(_strip_subspecies(latin))))
    if not en or en.get("type") == "disambiguation":
        return photos
    en_page = ((en.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
    if en_page and en_page == page_url:
        return photos  # same article we already walked
    en_thumb = (en.get("thumbnail") or {}).get("source") or ""
    if en_thumb and photo_identity(en_thumb) not in seen and len(photos) < want:
        seen.add(photo_identity(en_thumb))
        _seed_variant(seen, en_thumb)
        photos.append(en_thumb)
    photos += _media_list_photos(en_page, en.get("title") or "", seen, want - len(photos))
    return photos[:want]


# Map xeno-canto English call-type strings to a short German caption.
# Keys are matched case-insensitively via substring search; the order
# matters because longer keys must be tested before shorter ones
# they could collide with — "flight call" must win over "call",
# "alarm call" over "call". Unrecognised types fall back to the raw
# string capitalised — better than nothing.
_XC_TYPE_DE: dict[str, str] = {
    "flight call": "Flugruf",
    "alarm call": "Warnruf",
    "begging call": "Bettelruf",
    "alarm": "Warnruf",
    "begging": "Bettelruf",
    "subsong": "Subgesang",
    "song": "Gesang",
    "drumming": "Trommeln",
    "duet": "Duett",
    "wing": "Flügelschlag",
    "call": "Ruf",
}


def _de_type(raw: str | None) -> str:
    """Translate an xeno-canto call-type string to a short German caption."""
    if not raw:
        return "Aufnahme"
    s = raw.lower().strip()
    for k, v in _XC_TYPE_DE.items():
        if k in s:
            return v
    return raw.strip().capitalize() or "Aufnahme"


def xc_query_urls(latin: str, key: str) -> list[str]:
    """Every xeno-canto URL to try for `latin`, strictest filter first.

    Pure — no I/O — so the query FORM is testable without the network,
    which is what this needed: API v3 documents its search as tags
    (`gen:larus sp:fuscus`), and the bare binomial this used to send
    (`query=Phoenicurus%20ochruros`) is not a documented v3 form. A
    genus/species split also makes the old subspecies retry pass
    unnecessary — the third name is simply never sent, so
    "Erithacus rubecula rubecula" hits the species on the first try
    instead of burning a rate-limited request on a guaranteed miss.
    """
    parts = (latin or "").split()
    if not parts:
        return []
    taxon = f"gen:{parts[0]}"
    if len(parts) >= 2:
        taxon += f" sp:{parts[1]}"
    urls = []
    for extra in _XC_FILTER_LADDER:
        query = f"{taxon} {extra}".strip()
        # `safe=":"` keeps the tag colons readable in the log; spaces
        # become %20, which PHP's query parser reads as a separator
        # exactly like the docs' "+".
        urls.append(f"{_XC_API_URL}?query={quote(query, safe=':')}&key={quote(key)}")
    return urls


def _pick_diverse(recordings: list, want: int) -> list[dict]:
    """Up to `want` recordings, preferring a new call type each round.

    One Gesang + one Ruf + one Warnruf reads better than three Gesänge;
    once the types run out the remaining slots fill in API order."""
    seen_types: set[str] = set()
    picked: list[dict] = []
    leftover: list[dict] = []
    for rec in recordings:
        type_de = _de_type(rec.get("type"))
        if type_de in seen_types:
            leftover.append(rec)
            continue
        seen_types.add(type_de)
        picked.append(rec)
        if len(picked) >= want:
            return picked
    return (picked + leftover)[:want]


def _recording_dict(rec: dict) -> dict | None:
    """One API recording → the dossier's own shape. None when the entry
    carries no playable file URL."""
    file_url = rec.get("file") or ""
    if file_url.startswith("//"):
        file_url = "https:" + file_url
    if not file_url:
        return None
    return {
        "id": str(rec.get("id") or "").strip() or None,
        "file_url": file_url,
        "type_en": rec.get("type") or "",
        "type_de": _de_type(rec.get("type")),
        "recordist": rec.get("rec") or None,
        "license_url": rec.get("lic") or None,
        "length": rec.get("length") or None,
    }


def fetch_xeno_canto(latin: str, max_recordings: int = 3) -> list[dict]:
    """Pull up to `max_recordings` clips of the species' voice.

    Returns a list of recording dicts (`id`, `file_url`, `type_en`,
    `type_de`, `recordist`, `license_url`, `length`). Empty list when
    xeno-canto has nothing for the species on any rung of the filter
    ladder — or when no API key is configured, which `_xc_api_key`
    warns about once per process rather than skipping in silence.
    """
    key = _xc_api_key()
    if not key:
        return []
    for url in xc_query_urls(latin, key):
        data = _rate_limited_get(url)
        recordings = (data or {}).get("recordings") or []
        if not recordings:
            continue
        out = [r for r in map(_recording_dict, _pick_diverse(recordings, max_recordings)) if r]
        if out:
            return out
    return []


def fetch_bird_audio(wiki: dict | None, latin: str) -> list[dict]:
    """The species' voice, from whichever source can actually answer.

    WIKIMEDIA COMMONS FIRST, and it is not a fallback. The article's own
    media list — the one this module already fetches for the reference
    photos — carries the recording, so this needs no credential of any
    kind. xeno-canto has demanded a per-account API key since 2025-10-10,
    and without one every dossier in the archive showed „Keine
    Vogelstimme verfügbar" while the answer sat in a response we had
    already downloaded and thrown away.

    xeno-canto still runs when a key IS configured: it offers several
    recordings per species with call/song types, which Commons does not.
    Its results are appended, so the always-available one is what plays
    first and the extras enrich it.
    """
    out: list[dict] = []
    page_url = ((wiki or {}).get("content_urls") or {}).get("desktop", {}).get("page") or ""
    title = (wiki or {}).get("title") or _article_title_of(page_url)
    host = urlparse(page_url).netloc if page_url else ""
    if host and title:
        data = _rate_limited_get(f"https://{host}/api/rest_v1/page/media-list/{quote(title)}")
        file_title = _audio_title_from_media_list((data or {}).get("items") or [])
        if file_title:
            rec = _commons_audio(file_title, _rate_limited_get)
            if rec:
                out.append(rec)
    out.extend(fetch_xeno_canto(latin))
    if not out:
        log.info("[dossiers] keine Vogelstimme für %s — weder Commons noch xeno-canto", latin)
    return out
