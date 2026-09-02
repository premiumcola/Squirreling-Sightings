"""ZIP assembly, retention and listing for the debug bundle.

Nothing in here knows what a section IS — it takes ``arcname -> text``
and puts it on disk. The collectors live in :mod:`._sections`, so the
"what goes in" question and the "how it lands" question stay separable
(and separately testable).
"""

from __future__ import annotations

import logging
import zipfile
from datetime import datetime
from pathlib import Path

from ._consts import BUNDLE_DIR, BUNDLE_NAME_RE, MAX_BUNDLES, NAME_FMT

log = logging.getLogger(__name__)


def bundle_dir(storage_root) -> Path:
    return Path(storage_root) / BUNDLE_DIR


def bundle_name(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime(NAME_FMT)


def bundle_url(name: str) -> str:
    """The path ``/media/<subpath>`` already serves — the bundle dir is
    inside the storage root, so no second static route is needed."""
    return f"/media/{BUNDLE_DIR}/{name}"


def write_bundle(storage_root, entries: dict[str, str], now: datetime | None = None) -> Path:
    """Write one ZIP and return its path.

    Built under ``.part`` and renamed, so a listing (or the operator's
    file browser) never sees a half-written archive.
    """
    directory = bundle_dir(storage_root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / bundle_name(now)
    tmp = target.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, text in entries.items():
            zf.writestr(arcname, text)
    tmp.replace(target)
    return target


def iter_bundles(storage_root) -> list[Path]:
    """Every stored bundle, NEWEST first.

    Sorted by name, which is the timestamp — no stat() per file, and it
    survives a copy operation that resets the mtimes.
    """
    directory = bundle_dir(storage_root)
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.glob("*.zip") if BUNDLE_NAME_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )


def prune(storage_root, keep: int = MAX_BUNDLES) -> list[str]:
    """Delete everything past the newest ``keep``. Returns the names
    dropped. Runs on every write, not on a schedule."""
    evict = iter_bundles(storage_root)[max(0, keep) :]
    dropped = []
    for path in evict:
        try:
            path.unlink()
            dropped.append(path.name)
        except OSError as exc:
            log.warning("[storage] debug bundle %s nicht gelöscht: %s", path.name, exc)
    if dropped:
        log.info("[storage] debug bundle: %d alte verworfen", len(dropped))
    return dropped


def describe(path: Path) -> dict:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "name": path.name,
        "path": str(path),
        "url": bundle_url(path.name),
        "size": size,
    }


def list_bundles(storage_root) -> list[dict]:
    return [describe(p) for p in iter_bundles(storage_root)]
