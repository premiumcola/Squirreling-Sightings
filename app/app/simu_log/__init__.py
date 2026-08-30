"""SIMU log — every "Debug kopieren" tap, kept on the box.

"Vielleicht kannst Du, wenn ich auf kopieren drücke, parallel einfach
irgendwo den Log von dem Run ablegen … SIMU-Log irgendwie so was."

The clipboard is still the primary path; this is the copy that survives
it. One file per tap under ``storage/logs/simu/<cam_id>/``, holding the
same machine-first document the clipboard got
(:mod:`app.routes._debug_snapshot._machine`), scrubbed and capped.

Three rules, each of which is a test:

* **Fail soft.** ``store_run`` returns None rather than raising. A run
  that could not be written must not cost the operator the paste they
  actually asked for.
* **Never a credential.** Everything goes through :mod:`._scrub` on the
  way to disk, positionally rather than field-by-field — see that
  module's note on why.
* **Bounded.** :mod:`._retention` runs on every write, not on a
  schedule.
"""

from __future__ import annotations

import json
import logging

from ._consts import MAX_AGE_DAYS, MAX_FRONTEND_BYTES, MAX_RUNS_PER_CAMERA, RUN_NAME_RE
from ._io import list_runs, read_run, save_run
from ._retention import enforce, select_evictable
from ._scrub import scrub, scrub_text

log = logging.getLogger(__name__)

__all__ = [
    "MAX_AGE_DAYS",
    "MAX_FRONTEND_BYTES",
    "MAX_RUNS_PER_CAMERA",
    "RUN_NAME_RE",
    "clamp_frontend",
    "enforce",
    "list_runs",
    "read_run",
    "scrub",
    "scrub_text",
    "select_evictable",
    "store_run",
]


def clamp_frontend(block) -> dict:
    """The browser-owned block, bounded and shaped.

    Everything else in a stored run is built by this process; this is the
    one part a client supplies, so it is the one part that needs a size
    gate. Over the cap the block is REPLACED by a note rather than
    truncated — half a JSON object is worse than an honest absence.
    """
    if not isinstance(block, dict):
        return {}
    try:
        size = len(json.dumps(block, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return {"error": "frontend block is not JSON-serialisable"}
    if size > MAX_FRONTEND_BYTES:
        return {"error": "frontend block too large", "bytes": size, "limit": MAX_FRONTEND_BYTES}
    return block


def store_run(storage_root, cam_id: str, payload: dict) -> str | None:
    """Scrub, write and sweep. Returns the file name, or None."""
    if not storage_root or not cam_id or not isinstance(payload, dict):
        return None
    try:
        name = save_run(storage_root, cam_id, scrub(payload))
    except Exception as e:  # pragma: no cover - save_run swallows its own
        log.warning("[storage] simu_log: Lauf für %s nicht gespeichert: %s", cam_id, e)
        return None
    if name:
        enforce(storage_root, cam_id)
    return name
