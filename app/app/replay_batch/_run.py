"""The batch worker body.

Not a second replay path. Every clip goes through exactly the functions
`routes/replay.py` calls for a single event — `resolve_replay_settings`,
`replay_clip`, `build_comparison`, `build_entry`, `append_replay` — with
the settings spec pinned to ``"current"``, which is the operator's
question: what does TODAY's detection make of clips recorded under an
older build.

Everything the run touches beyond those is injected by the caller
(`store`, `worker`, the two path/config lookups). That keeps this module
importable and testable with stubs — no Flask app context, no TPU, no
video file — which is the only way the batch path could be covered by
this repo's stub-based suite.

Live detection is never starved: `replay_clip` borrows
`TrackingWorker.detector()` and `TrackingWorker.bird_classifier()`, both
CPU-pinned instances, so the Edge TPU the camera runtimes own is never
contended for — not by the detector and not by the species classifier,
which is pinned independently of what `prefer_cpu` says for live
detection. The batch adds no new concurrency on top of that: it is one
thread walking clips in sequence, and both models are built once for
the whole run rather than once per clip.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from ..replay import (
    append_replay,
    build_comparison,
    build_entry,
    replay_clip,
    resolve_replay_settings,
)
from . import _state
from ._aggregate import fold, movers_from, summarise_event
from ._consts import BATCH_SCHEMA
from ._persist import save_report
from ._select import find_bird_events

log = logging.getLogger(__name__)


def _replay_one(ctx: dict, camera_id: str, event_id: str, event: dict) -> tuple[dict, list[dict]]:
    """Replay one clip with the current settings and summarise it.

    Raises on anything that makes this clip unanswerable; the caller
    counts that as an error and moves to the next one — one unreadable
    clip must not end a run over hundreds.
    """
    video = ctx["resolve_video"](event_id, camera_id)
    if video is None or not video.exists():
        raise ValueError("Video-Datei fehlt")
    cam_cfg = ctx["cam_cfg_for"](camera_id) or {}
    settings = resolve_replay_settings(event, cam_cfg, "current")
    result = replay_clip(
        worker=ctx["worker"],
        camera_id=camera_id,
        video_path=video,
        storage_root=ctx["storage_root"],
        cfg=settings["cfg"],
    )
    comparison = build_comparison(
        event=event,
        sidecar_tracks=ctx["sidecar_tracks_for"](video),
        replay=result,
        # Always the live profile: the spec is pinned to "current", so
        # resolve_replay_settings never returns the "provenance" basis
        # that routes/replay.py::_alarm_profile switches on.
        alarm_profile=cam_cfg.get("alarm_profile"),
    )
    entry = build_entry(settings=settings, replay=result, comparison=comparison)
    append_replay(ctx["store"], camera_id, event_id, entry)
    row = summarise_event(camera_id, event_id, event, comparison)
    return row, movers_from(camera_id, event_id, comparison)


def _walk(ctx: dict, scope: dict) -> tuple[list[dict], list[dict], int, bool]:
    """Replay every selected clip. ``(rows, movers, errors, cancelled)``."""
    rows: list[dict] = []
    movers: list[dict] = []
    errors = 0
    for camera_id, event_id, event in find_bird_events(
        ctx["store"], scope.get("cameras"), since=scope.get("since"), until=scope.get("until")
    ):
        if _state.cancel_requested():
            return rows, movers, errors, True
        try:
            row, moved = _replay_one(ctx, camera_id, event_id, event)
        except Exception as e:
            errors += 1
            log.warning("[tracking] batch replay: event=%s skipped: %s", event_id, e)
            _state.advance(event_id, failed=True)
            continue
        rows.append(row)
        movers.extend(moved)
        _state.advance(event_id)
    return rows, movers, errors, False


def run_batch(ctx: dict, scope: dict) -> dict:
    """Count, walk, fold, persist. Returns the report document."""
    total = sum(
        1
        for _ in find_bird_events(
            ctx["store"], scope.get("cameras"), since=scope.get("since"), until=scope.get("until")
        )
    )
    _state.set_total(total)
    rows, movers, errors, cancelled = _walk(ctx, scope)
    report = {
        "schema": BATCH_SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": scope,
        "selected": total,
        "cancelled": cancelled,
        **fold(rows, movers, errors=errors),
    }
    save_report(ctx["storage_root"], report)
    log.info(
        "[tracking] batch replay done: examined=%d/%d changed=%d more-birds=%d "
        "named=%d/%d errors=%d%s",
        report["examined"],
        total,
        report["changed"],
        report["birds_gained_strict"],
        report["species_named_events"],
        report["classified_events"],
        errors,
        " (abgebrochen)" if cancelled else "",
    )
    return report


def _thread_body(ctx: dict, scope: dict) -> None:
    """Thread entry point. Swallows everything onto the job state — a
    traceback escaping here would leave `running` True forever and the
    dashboard polling a run that is gone."""
    try:
        report = run_batch(ctx, scope)
    except Exception as e:
        log.error("[tracking] batch replay failed: %s", e, exc_info=True)
        _state.finish(None, error=str(e))
        return
    _state.finish(report, cancelled=bool(report.get("cancelled")))


def start_batch(ctx: dict, scope: dict) -> bool:
    """Claim the run slot and start the worker. False when a run is
    already in flight."""
    if not _state.begin(scope):
        return False
    threading.Thread(
        target=_thread_body, args=(ctx, scope), daemon=True, name="replay-batch"
    ).start()
    return True
