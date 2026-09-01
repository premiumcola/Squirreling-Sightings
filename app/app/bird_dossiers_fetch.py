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
import threading
import time
from urllib.parse import quote, urlparse

log = logging.getLogger("app.bird_dossiers")

# Xeno-canto API v3 requires a per-account `key` parameter (v2 is gone
# as of early 2026). When `XENO_CANTO_API_KEY` is unset, the audio
# fetch is silently skipped — `audio_url` stays None and the frontend
# hides the player. q:A means "Quality A"; len:5-15 picks recordings
# short enough to play inline as MP3 in the dossier panel.
_XC_API_KEY = os.environ.get("XENO_CANTO_API_KEY", "").strip()
_XC_QUERY_TEMPLATE = (
    "https://xeno-canto.org/api/3/recordings" "?query={latin}+q:A+len:5-15&key={key}"
)

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


# Filenames that mark a media-list item as unsuitable for the second
# dossier photo — a distribution map, a UI icon, or a Commons/Wikimedia
# housekeeping graphic, none of which show the actual animal.
_SECOND_PHOTO_SKIP_WORDS = (
    "icon",
    "map",
    "verbreitung",
    "distribution",
    "range",
    "logo",
    "commons",
)


def fetch_second_photo(wiki: dict | None) -> str | None:
    """Given a successful `fetch_wikipedia` result, pull the page's media
    list and return a second, distinct photo URL — so the dossier can show
    two reference views of the species side by side. Skips maps/icons/SVGs
    and the primary thumbnail itself. None on any failure, an unsuitable
    list, or when `wiki` itself is falsy (no point querying a page that
    doesn't exist)."""
    if not wiki:
        return None
    page_url = ((wiki.get("content_urls") or {}).get("desktop") or {}).get("page")
    title = wiki.get("title")
    if not page_url or not title:
        return None
    host = urlparse(page_url).netloc
    if not host:
        return None
    primary_name = ((wiki.get("thumbnail") or {}).get("source") or "").rsplit("/", 1)[-1].lower()
    url = f"https://{host}/api/rest_v1/page/media-list/{quote(title)}"
    data = _rate_limited_get(url)
    if not data:
        return None
    for item in data.get("items") or []:
        if item.get("type") != "image":
            continue
        srcset = item.get("srcset") or []
        original = (item.get("original") or {}).get("source") or (
            srcset[-1].get("src") if srcset else None
        )
        if not original:
            continue
        if original.startswith("//"):
            original = "https:" + original
        name = original.rsplit("/", 1)[-1].lower()
        if name.endswith(".svg") or name == primary_name:
            continue
        if any(w in name for w in _SECOND_PHOTO_SKIP_WORDS):
            continue
        return original
    return None


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


def fetch_xeno_canto(latin: str, max_recordings: int = 3) -> list[dict]:
    """Pull up to `max_recordings` quality-A 5-15 s clips for the species.

    Returns a list of recording dicts (`id`, `file_url`, `type_en`,
    `type_de`, `recordist`, `license_url`, `length`). Empty list when
    no recordings are available — typical for rare or recently-named
    species — OR when no API key is configured. Both cases let the
    frontend hide the audio block.

    Subspecies fallback mirrors the Wikipedia path. The picker prefers
    a diverse set of call types when available (one Gesang + one Ruf
    + one Warnruf reads better than three Gesänge), then fills the
    remaining slots in API order.
    """
    if not _XC_API_KEY:
        return []
    candidates = [latin]
    stripped = _strip_subspecies(latin)
    if stripped != latin:
        candidates.append(stripped)
    for cand in candidates:
        url = _XC_QUERY_TEMPLATE.format(latin=quote(cand), key=_XC_API_KEY)
        data = _rate_limited_get(url)
        if not data:
            continue
        recordings = data.get("recordings") or []
        if not recordings:
            continue
        # Diversity-first picker: walk the list and prefer a new type
        # each round; when we run out of new types, fall back to API
        # order to fill remaining slots.
        seen_types: set[str] = set()
        first_pass: list[dict] = []
        leftover: list[dict] = []
        for rec in recordings:
            type_de = _de_type(rec.get("type"))
            if type_de in seen_types:
                leftover.append(rec)
                continue
            seen_types.add(type_de)
            first_pass.append(rec)
            if len(first_pass) >= max_recordings:
                break
        picked = first_pass
        for rec in leftover:
            if len(picked) >= max_recordings:
                break
            picked.append(rec)
        out: list[dict] = []
        for rec in picked:
            file_url = rec.get("file") or ""
            if file_url.startswith("//"):
                file_url = "https:" + file_url
            if not file_url:
                continue
            out.append(
                {
                    "id": str(rec.get("id") or "").strip() or None,
                    "file_url": file_url,
                    "type_en": rec.get("type") or "",
                    "type_de": _de_type(rec.get("type")),
                    "recordist": rec.get("rec") or None,
                    "license_url": rec.get("lic") or None,
                    "length": rec.get("length") or None,
                }
            )
        if out:
            return out
    return []
