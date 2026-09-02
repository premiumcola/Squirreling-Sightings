"""What goes into a debug bundle, one collector per section.

Two rules run through all of them:

* **Never a credential.** Every section is routed through
  :mod:`app.simu_log._scrub` — positionally, over the whole assembled
  value, not field by field. The bundle exists to be handed to someone
  else; that is exactly the situation in which a redaction that only
  happens where somebody remembered to call it stops happening.
* **Fail soft.** A collector that raises costs its own section, not the
  bundle. A bundle missing ``telemetry.json`` still answers most of the
  questions it was built for; no bundle at all answers none.

The raw ``settings.json`` is deliberately NOT a section, in any shape.
The config that ships is ``export_effective_config()`` — the merged
runtime view — after scrubbing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..simu_log import scrub, scrub_text
from ._consts import EVENT_COUNT, LOG_TAIL_LINES

log = logging.getLogger(__name__)


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _guard(name: str, fn, *args, **kwargs):
    """Run a collector, or return the reason it could not run."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # one broken section must not cost the bundle
        log.warning("[storage] debug bundle: %s nicht erfasst: %s", name, exc)
        return {"error": f"{type(exc).__name__}: {exc}"}


# ── Log ────────────────────────────────────────────────────────────────────
def _tail(path: Path, lines: int) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.splitlines()[-lines:]


def log_tail(storage_root, lines: int = LOG_TAIL_LINES) -> str:
    """The last ``lines`` log lines, scrubbed.

    Reads the rotating file installed by
    :func:`app.logging_setup.attach_file_handler`, reaching one rotation
    back when the current file was just rolled — otherwise a bundle
    taken seconds after a rotation would carry three lines. Falls back
    to the 400-line in-memory buffer when no file exists at all (a
    read-only storage mount, or a process started before the handler).
    """
    from ..logging_setup import log_buffer, log_file_path

    path = Path(log_file_path(storage_root))
    out = _tail(path, lines)
    if len(out) < lines:
        older = _tail(path.with_name(path.name + ".1"), lines - len(out))
        out = older + out
    if not out:
        out = [f"{r['ts']} {r['level']:<5} {r['msg']}" for r in log_buffer.get()]
        out.insert(0, "# keine Logdatei gefunden — Speicher-Puffer (max. 400 Zeilen)")
    return scrub_text("\n".join(out))


# ── Config ─────────────────────────────────────────────────────────────────
def redact_settings(cfg: dict | None) -> dict:
    """The effective config with every secret gone.

    Not a second redactor: :func:`app.simu_log.scrub` is the one this
    project already trusts with the debug snapshots, and it works
    positionally — every key that NAMES a secret becomes ``<key>_set``,
    every string is masked for embedded URL credentials, bot tokens and
    RFC-1918 addresses, at any depth.
    """
    return scrub(cfg or {})


# ── Events ─────────────────────────────────────────────────────────────────
def recent_events(store, cam_ids, limit: int = EVENT_COUNT) -> list[dict]:
    """The newest ``limit`` event JSONs across all cameras, scrubbed.

    Whole documents, not a summary — they carry the ``provenance`` block
    (the tuning, models and ROI in force at trigger time), which is the
    reason the bundle is worth sending at all.
    """
    items: list[dict] = []
    for cam_id in cam_ids:
        try:
            items.extend(store.list_events(cam_id, limit=limit))
        except Exception as exc:
            log.warning("[storage] debug bundle: Ereignisse %s: %s", cam_id, exc)
    items.sort(key=lambda e: str(e.get("time") or ""), reverse=True)
    return [scrub(e) for e in items[:limit]]


# ── Live state ─────────────────────────────────────────────────────────────
def status_snapshot() -> dict:
    """``/api/status`` as of now — per-camera state plus TPU utilisation."""
    from ..routes.bootstrap import status_payload

    return scrub(status_payload())


def telemetry_snapshot() -> dict:
    """Per-stage inference telemetry: device, model, timings, projection."""
    from ..routes.telemetry import _build_payload

    return scrub(_build_payload())


def tuning_snapshot(cam_ids) -> dict:
    """Per-camera net state: the tuning fold, the axes, and the values
    the net deliberately never writes (``frozen``)."""
    from ..routes._netz_helpers import net_state

    out: dict = {}
    for cam_id in cam_ids:
        state = _guard(f"Feinschliff {cam_id}", net_state, cam_id)
        if not isinstance(state, dict):
            continue
        if "error" in state:
            out[cam_id] = state
            continue
        out[cam_id] = scrub(
            {
                key: state.get(key)
                for key in ("cam_id", "cam_name", "role", "auto", "tuning", "frozen", "axes")
                if key in state
            }
        )
    return out
