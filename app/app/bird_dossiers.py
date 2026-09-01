"""Auto-built bird "dossiers" — a personal field guide that grows as
the bird species classifier identifies new species in your garden.

How it grows:
    Every time the bird classifier returns a latin name, the camera
    runtime calls `on_new_species(latin, common_de, event_id, camera_id)`.
    First-ever sighting → a fresh dossier entry plus a background fetch
    of (a) Wikipedia summary + thumbnail, (b) a Xeno-canto audio sample
    with attribution. Subsequent sightings → just a counter bump.

    Separately, `sweep_prebuild` (called from maintenance.py's daily
    tick) warms the SAME reference content for species that have never
    been detected yet, so a still-locked achievement tile has something
    to show the moment it's clicked instead of a blank "warte auf die
    erste Sichtung" state. It never touches `sighting_count` or
    `first_seen_at` — a species built this way stays locked until a
    real sighting calls `on_new_species`.

External APIs are deliberately best-effort:
    Network failures and rate-limits never poison the camera pipeline.
    A missed Wikipedia fetch leaves `wikipedia_fetched_at = null` in the
    dossier; the next sighting (or a manual /refetch) tries again. No
    retry loops, no cascading timeouts back into detection.

License compliance:
    Xeno-canto audio is Creative Commons but each recording carries its
    own license (CC-BY, CC-BY-SA, CC-BY-NC, CC0). The dossier MUST store
    `audio_attribution` + `audio_license` and the frontend MUST display
    them next to the player — anything less is a license violation.
    Wikipedia text is CC-BY-SA; the API extract is 2-3 sentences which
    is a fair-use snippet.
"""

from __future__ import annotations

import json as _json_mod
import logging
import threading
from datetime import datetime
from pathlib import Path

# Re-export from the shared helper so the single internal callers
# (this module and any future ones) all land on one implementation.
from .bird_dossiers_fetch import fetch_wikipedia as _fetch_wikipedia
from .bird_dossiers_fetch import fetch_xeno_canto as _fetch_xeno_canto
from .io_utils import atomic_write_json as _atomic_write_json  # noqa: F401

log = logging.getLogger("app.bird_dossiers")

#: Per-call budget for `BirdDossierService.sweep_prebuild` — new
#: placeholder dossiers created per maintenance tick. Each one spawns up
#: to two rate-limited network fetches, serialised ~1 s apart (see
#: bird_dossiers_fetch.py's `_rate_lock`) — so the real cost of a FULL
#: pass over the whole vocabulary (well under 100 species) is a couple
#: of minutes, not a multi-day trickle. maintenance.py's daily-cleanup
#: timer already runs once immediately at every boot (server.py calls
#: `_run_daily_cleanup()` directly, not just via its own 24 h
#: re-schedule) — so one generous budget here means "every species has
#: a reference dossier within minutes of the next restart", not days.
#: 15 was too conservative: it was reasoned about as "protect against a
#: fetch storm", but a fetch storm was never the actual risk — the rate
#: lock already caps that at exactly 1 req/s regardless of the budget.
#: A few hundred is still a real ceiling (protects a future, much
#: larger vocabulary from blocking one sweep for an unreasonable time),
#: just not one the current vocabulary ever bumps into.
DOSSIER_PREBUILD_BUDGET = 200


# ── Service ────────────────────────────────────────────────────────────────
class BirdDossierService:
    """Owns `bird_dossiers.json` plus the background fetcher pool.

    Constructed once at boot in server.py. Camera runtimes call
    `on_new_species` from the motion-finalize hook; the route layer
    reads via `list_dossiers` / `get_dossier` and triggers manual
    refetches via `refetch_dossier`.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = self._load()
        # Background fetches share a single daemon-thread pool. We never
        # join it; pending fetches die with the process. Each fetch is
        # short (≤2× _HTTP_TIMEOUT = 10 s upper bound), so shutdown
        # always sees a small in-flight set.
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"schema": 1, "dossiers": {}}
        try:
            d = _json_mod.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                return {"schema": 1, "dossiers": {}}
            d.setdefault("schema", 1)
            d.setdefault("dossiers", {})
            return d
        except Exception as e:
            log.warning("[dossiers] load failed (%s) — starting empty", e)
            return {"schema": 1, "dossiers": {}}

    def _save_locked(self) -> None:
        """Persist self.data. Caller holds self._lock."""
        try:
            _atomic_write_json(self.path, self.data)
        except Exception as e:
            log.warning("[dossiers] save failed: %s", e)

    # ── Public API ─────────────────────────────────────────────────────
    @staticmethod
    def _blank_dossier(
        latin: str,
        common_de: str | None,
        *,
        first_seen_at: str | None,
        first_seen_event_id: str | None,
        first_seen_camera_id: str | None,
        sighting_count: int,
    ) -> dict:
        """The dossier dict shape, shared by every entry point that can
        create one — a real first sighting (`on_new_species`) or the
        no-sighting-yet reference-content warm-up (`_create_placeholder`).
        Keeping one shape in one place means a field added for one path
        can't silently drift out of sync with the other."""
        return {
            "common_name_de": common_de,
            "common_name_en": None,
            "latin": latin,
            "first_seen_at": first_seen_at,
            "first_seen_event_id": first_seen_event_id,
            "first_seen_camera_id": first_seen_camera_id,
            "sighting_count": sighting_count,
            "wikipedia_summary": None,
            "wikipedia_url": None,
            "wikipedia_thumb_url": None,
            "wikipedia_fetched_at": None,
            # Multi-clip xeno-canto store. Each entry carries id /
            # file_url / type_en / type_de / recordist / license_url /
            # length so the frontend can render a labelled <audio>
            # row per clip and the cache check can skip refetch on
            # subsequent views. The legacy single-clip fields below
            # mirror recordings[0] for backward-compat with older
            # dossier consumers; the frontend prefers `recordings`.
            "recordings": [],
            "audio_url": None,
            "audio_attribution": None,
            "audio_license": None,
            "audio_fetched_at": None,
            "wiki_distribution_thumb": None,
        }

    def on_new_species(
        self, latin: str, common_de: str | None, event_id: str, camera_id: str
    ) -> bool:
        """Hook called by the bird classifier on every successful ID.

        Returns True if a new dossier was created (first sighting),
        False if it just bumped the counter. Never raises.
        """
        if not latin:
            return False
        latin = latin.strip()
        with self._lock:
            existing = self.data["dossiers"].get(latin)
            if existing is not None:
                existing["sighting_count"] = int(existing.get("sighting_count", 0)) + 1
                self._save_locked()
                return False
            now_iso = datetime.now().isoformat(timespec="seconds")
            self.data["dossiers"][latin] = self._blank_dossier(
                latin,
                common_de,
                first_seen_at=now_iso,
                first_seen_event_id=event_id,
                first_seen_camera_id=camera_id,
                sighting_count=1,
            )
            self._save_locked()
        log.info("[dossiers] new species: %s (%s) — fetching", latin, common_de or "?")
        self._spawn_fetch(latin)
        return True

    def _create_placeholder(self, latin: str, common_de: str | None) -> bool:
        """Pre-build a bare, never-detected dossier entry (sighting_count
        stays 0, first_seen_* stays None) and spawn its Wikipedia +
        Xeno-canto fetch — see `sweep_prebuild`. Returns False without
        any side effect if a dossier already exists for `latin`; a real
        detection's data (on_new_species / increment_sighting) always
        wins and is never overwritten by this path."""
        latin = (latin or "").strip()
        if not latin:
            return False
        with self._lock:
            if latin in self.data["dossiers"]:
                return False
            self.data["dossiers"][latin] = self._blank_dossier(
                latin,
                common_de,
                first_seen_at=None,
                first_seen_event_id=None,
                first_seen_camera_id=None,
                sighting_count=0,
            )
            self._save_locked()
        log.info("[dossiers] pre-built reference dossier: %s (%s)", latin, common_de or "?")
        self._spawn_fetch(latin)
        return True

    def sweep_prebuild(self, vocabulary: dict, *, budget: int = DOSSIER_PREBUILD_BUDGET) -> dict:
        """Bounded pass that warms the reference-content cache for every
        species in `vocabulary` (latin → German common name, e.g. the
        classifier's full latin_to_de map) that has no dossier yet —
        detected or not. Mirrors bird_species_backfill.py::
        sweep_bird_species_backfill's own "budget per call, piggyback on
        the daily maintenance timer" shape: at most `budget` NEW
        placeholders are created per call, so a large vocabulary can't
        turn one maintenance tick into a fetch storm. Species already
        covered (by a real sighting or an earlier sweep call) are
        skipped cheaply and don't count against the budget — a call
        picks up exactly where the previous one left off.

        Deliberately does NOT touch achievements.json, sighting counts,
        or first_seen_at — a species built here stays LOCKED in the
        achievement grid until a real detection calls on_new_species.
        This only makes a still-locked tile's dossier content (photo,
        text, audio) ready to show the instant it's clicked.
        """
        examined = 0
        created = 0
        for latin, common_de in (vocabulary or {}).items():
            if not latin:
                continue
            with self._lock:
                exists = latin in self.data["dossiers"]
            if exists:
                continue
            if created >= budget:
                break
            examined += 1
            if self._create_placeholder(latin, common_de):
                created += 1
        return {"examined": examined, "created": created}

    def increment_sighting(self, latin: str) -> None:
        """Bump the counter without going through the new-species path.
        Use when you already know the dossier exists."""
        if not latin:
            return
        with self._lock:
            d = self.data["dossiers"].get(latin)
            if d is None:
                return
            d["sighting_count"] = int(d.get("sighting_count", 0)) + 1
            self._save_locked()

    def get_dossier(self, latin: str) -> dict | None:
        with self._lock:
            d = self.data["dossiers"].get(latin)
            return dict(d) if d else None

    def list_dossiers(self) -> list[dict]:
        """Newest-first list. Keys with no first_seen_at sink to the end."""
        with self._lock:
            items = list(self.data["dossiers"].values())
        items.sort(key=lambda d: d.get("first_seen_at") or "", reverse=True)
        return [dict(d) for d in items]

    def refetch_dossier(self, latin: str) -> bool:
        """Manual re-fetch trigger from the API. Returns True if a fetch
        was started, False if the dossier doesn't exist."""
        with self._lock:
            if latin not in self.data["dossiers"]:
                return False
        self._spawn_fetch(latin)
        return True

    # ── Background fetcher ─────────────────────────────────────────────
    def _spawn_fetch(self, latin: str) -> None:
        """Start a daemon thread for the Wiki + xeno-canto fetch unless
        one is already in flight for this latin name."""
        with self._inflight_lock:
            if latin in self._inflight:
                return
            self._inflight.add(latin)
        threading.Thread(target=self._fetch_worker, args=(latin,), daemon=True).start()

    def _fetch_worker(self, latin: str) -> None:
        try:
            self._fetch_and_apply(latin)
        finally:
            with self._inflight_lock:
                self._inflight.discard(latin)

    def _fetch_and_apply(self, latin: str) -> None:
        wiki = _fetch_wikipedia(latin)
        # Cache check: if recordings are already populated, skip the
        # xeno-canto round-trip. The frontend's "open dossier" path
        # ends up here whenever a fresh species is detected; for known
        # species we keep the cached clips instead of re-pulling.
        with self._lock:
            d_existing = self.data["dossiers"].get(latin)
            already_have_audio = bool(d_existing and d_existing.get("recordings"))
        recordings = [] if already_have_audio else _fetch_xeno_canto(latin)
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            d = self.data["dossiers"].get(latin)
            if d is None:
                return
            self._apply_wikipedia(d, wiki, now_iso)
            if not already_have_audio:
                self._apply_xeno_canto(d, recordings, now_iso)
            self._save_locked()
        log.info(
            "[dossiers] fetched %s — wiki=%s xc=%s",
            latin,
            "ok" if wiki else "miss",
            f"{len(recordings)} clips"
            if recordings
            else ("cached" if already_have_audio else "miss"),
        )

    @staticmethod
    def _apply_wikipedia(dossier: dict, wiki: dict | None, now_iso: str) -> None:
        """Merge a successful Wikipedia summary into the dossier dict.

        On miss: leave wikipedia_fetched_at NULL so a future trigger
        retries (the spec's "Indikator dass der Fetch noch aussteht").
        """
        if not wiki:
            return
        thumb = (wiki.get("thumbnail") or {}).get("source")
        page_url = ((wiki.get("content_urls") or {}).get("desktop") or {}).get("page")
        dossier["wikipedia_summary"] = wiki.get("extract") or None
        dossier["wikipedia_url"] = page_url or None
        dossier["wikipedia_thumb_url"] = thumb or None
        dossier["wikipedia_fetched_at"] = now_iso
        # Title is normally the German common name when the DE wiki hit;
        # use it to backfill common_name_de if the classifier didn't
        # provide one (rare path, but happens for genus-only matches).
        if not dossier.get("common_name_de") and wiki.get("title"):
            dossier["common_name_de"] = wiki.get("title")

    @staticmethod
    def _apply_xeno_canto(dossier: dict, recordings: list, now_iso: str) -> None:
        """Merge xeno-canto recordings into the dossier.

        `recordings` is a list of dicts (see _fetch_xeno_canto). Stored
        on `dossier["recordings"]` directly; the legacy single-clip
        fields (`audio_url` / `audio_attribution` / `audio_license`)
        mirror the first entry for backward-compat with older
        consumers but the frontend prefers iterating `recordings[]`.
        """
        if not recordings:
            return
        dossier["recordings"] = recordings
        dossier["audio_fetched_at"] = now_iso
        # Legacy mirror — keeps any older code path that still reads
        # the single-clip fields working without a coordinated change.
        head = recordings[0]
        dossier["audio_url"] = head.get("file_url")
        dossier["audio_attribution"] = head.get("recordist")
        dossier["audio_license"] = head.get("license_url")
