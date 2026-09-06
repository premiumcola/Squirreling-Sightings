"""Der Filmstreifen unter dem Abspielbalken — für das Archiv nachgezogen.

Aus `migrations.py` herausgelöst, als die Datei mit der Aufsicht über
hängengebliebene Clips über die 500-Zeilen-Grenze lief. Ein eigener
Belang mit eigener Versionsnummer (`TILE_W`) und eigenem Log-Präfix,
also ein eigenes Modul — nicht die Grenze weggeschoben.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time as _time
from pathlib import Path

# Die Kachelbreite, auf die das Archiv geschnitten sein soll. Steht auf
# Modulebene statt im Durchlauf: sie IST die Versionsnummer, gegen die
# `_has_scrub` prüft, und eine Versionsprüfung hinter einem faulen Import
# findet niemand.
from .scrub_sprite import TILE_W

log = logging.getLogger(__name__)


def generate_missing_scrub_sprites(*, storage_root: Path, store=None) -> None:
    """Backfill the scrub filmstrip for motion clips recorded before it.

    Every clip from here on gets its sheet in the re-encode thread. The
    archive does not, and a player whose drag-preview works only on
    clips newer than one deploy is the kind of half-feature that reads
    as broken. So: one pass at boot, in the background, skipping
    anything that already has a sheet.

    PACED ON PURPOSE. This is a full sequential decode per clip, and an
    archive can hold thousands. The sleep between clips is what keeps a
    backfill from competing with live recording for the same cores —
    the same reason ``generate_missing_thumbnails`` paces itself, and
    the same reason ``check_tracks_schema_version`` refuses to
    auto-reindex.

    The event JSON is updated too, when a store is supplied: the sheet
    on disk is useless to the player without the grid that addresses
    it. A clip whose manifest cannot be found still gets its sheet, so
    a later reconcile can pick it up.
    """

    def _do():
        base = storage_root / "motion_detection"
        if not base.exists():
            return
        from .scrub_sprite import build_scrub_sprite, legacy_sprite_path_for, sprite_path_for

        made = 0
        swept = 0
        failed = 0
        # The first failure's own words. A count says how bad it is; one
        # example says what to go and look at, and costs one string.
        first_error = ""
        for cam_dir in sorted(base.iterdir()):
            if not cam_dir.is_dir():
                continue
            for mp4 in sorted(cam_dir.rglob("*.mp4")):
                # `.raw.mp4` is the stream copy, not the clip the player
                # plays — a sheet built from it would drift from the
                # spliced, re-encoded file by the whole pre-roll.
                if mp4.name.endswith(".raw.mp4"):
                    continue
                # Sheets briefly lived beside the clip as `<id>.scrub.jpg`,
                # where readers that pick "the first *.jpg here" found them
                # and put a grid of postage stamps on the media card. Sweep
                # any that a previous boot wrote.
                stale = legacy_sprite_path_for(mp4)
                if stale.exists():
                    with contextlib.suppress(Exception):
                        stale.unlink()
                        swept += 1
                # A SHEET ON DISK IS NOT ENOUGH. The player addresses a
                # tile through the grid on the EVENT — cols, rows, count,
                # interval, tile size — and a sheet whose geometry never
                # reached the manifest is a file nothing can read. The
                # skip used to test the disk alone, so any clip whose
                # `_attach_scrub` had failed (or that was built before
                # that step existed) was skipped again on every boot,
                # for good: „bitte lasse ein Skript laufen dass alle
                # Thumbnails Previews der Videos erstellt, hier is nix
                # da." Both halves have to be there to count as done.
                if sprite_path_for(mp4).exists() and _has_scrub(store, cam_dir.name, mp4.stem):
                    continue
                try:
                    geo = build_scrub_sprite(mp4)
                    if not geo:
                        # Unreadable or empty clip. Counted, not silent:
                        # a `continue` here is exactly how one clip went
                        # on failing every pass with nothing to show for
                        # it.
                        failed += 1
                        first_error = first_error or f"{mp4.name}: kein Blatt gebaut"
                        continue
                    made += 1
                    if store is not None:
                        _attach_scrub(store, cam_dir.name, mp4.stem, geo)
                except Exception as e:
                    failed += 1
                    first_error = first_error or f"{mp4.name}: {e}"
                    log.debug("[scrub] backfill failed for %s: %s", mp4.name, e)
                _time.sleep(0.05)  # pace startup
        if swept:
            log.info("[boot] %d fehlplatzierte Scrub-Blätter entfernt", swept)
        if made:
            log.info("[boot] %d Scrub-Filmstreifen nachgebaut", made)
        # AT WARNING, not debug. A clip whose filmstrip never builds shows
        # the operator a drag with no preview and no reason, forever —
        # and the only trace of it was a debug line nobody reads at the
        # level this app runs at.
        if failed:
            log.warning(
                "[scrub] %d Filmstreifen konnten nicht gebaut werden — erster: %s",
                failed,
                first_error,
            )

    threading.Thread(target=_do, daemon=True).start()


def _has_scrub(store, camera_id: str, event_id: str) -> bool:
    """Does this event's manifest carry a CURRENT, usable scrub grid?

    Without a store there is nothing to check and nothing to write, so
    the disk answer stands alone — that is the unit-test path and the
    only case where a bare sheet counts as finished.

    Three ways to fail, and each is a real state seen on this archive:

    * no grid at all — the sheet may sit on disk, but the player
      addresses a tile THROUGH this block and cannot find it without one;
    * a grid missing `count` or `tile_w` — ``_usable`` in
      timeline/_preview.js refuses to draw from it, so keeping it is
      keeping a value that renders as nothing;
    * a grid whose `tile_w` is below the current :data:`TILE_W` — built
      by an older version. The player sizes the drag preview from this
      number (it never assumes one), so an archive of 240 px sheets goes
      on looking soft however large the bubble is allowed to get. Tiles
      are always resized to exactly TILE_W at build time, so a smaller
      value can only mean "older", never "this clip was small".

    That last one is a VERSION CHECK, deliberately shaped like
    ``check_tracks_schema_version``: bump the constant and the next pass
    re-cuts the archive without a force flag anyone has to remember.
    """
    if store is None:
        return True
    try:
        ev = store.get_event(camera_id, event_id) or {}
    except Exception:
        return False
    geo = ev.get("scrub")
    if not isinstance(geo, dict) or not geo.get("count"):
        return False
    try:
        return int(geo.get("tile_w") or 0) >= int(TILE_W)
    except (TypeError, ValueError):
        return False


def _attach_scrub(store, camera_id: str, event_id: str, geo: dict) -> None:
    """Put one backfilled sheet's geometry onto its event JSON.

    Additive by construction — reads the manifest, sets one key, writes
    it back through the store's own atomic path. Never touches anything
    else on the event.
    """
    try:
        ev = store.get_event(camera_id, event_id)
        if not ev:
            return
        ev["scrub"] = geo
        store.update_event(camera_id, event_id, ev)
    except Exception as e:
        log.debug("[scrub] manifest update failed for %s: %s", event_id, e)
