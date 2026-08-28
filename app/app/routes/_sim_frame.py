"""Frame acquisition and snapshot encoding for the Simulieren panel.

Split out of ``coral_test_detection`` so the endpoint reads as the
pipeline it drives rather than as a 200-line wait loop with a detection
pass appended. Nothing here decides anything about detections — it
answers "which frame, how old, from which stream" and "what does the
browser get to draw on".

The frame contract, and why it is what it is: poll up to
``FRESH_POLL_WINDOW_S`` for a frame that ARRIVED within
``FRESH_GRACE_S`` of the request AND comes from a decoder that is within
``MAX_CAPTURE_LAG_S`` of live. Arrival, not decode: a frame pulled from a
minutes-deep decoder backlog carries a decode stamp from a millisecond
ago and sails through any check built on it.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass
from typing import Any

import cv2
from flask import request

from ._sim_guard import MAX_CAPTURE_LAG_S

log = logging.getLogger(__name__)

# How far a candidate frame's ARRIVAL may predate the request before it
# counts as stale. One second so a normally-cadenced main frame (~350 ms)
# qualifies on the first poll.
FRESH_GRACE_S = 1.0

# How long the handler polls for a frame that clears both bars before it
# gives up and reports the stream stuck.
FRESH_POLL_WINDOW_S = 2.5

# C41 · per-camera last "preferred stream unavailable" warn timestamp.
# Rate-limited to once per 60 s so a camera with the sub-stream
# permanently disabled doesn't spam docker logs on every Simulieren tick.
_FALLBACK_WARN_TS: dict[str, float] = {}

# Q2-5 · per-(cam, client) request-gap tracking. The panel polls
# continuously while open; when the user's device loses connectivity the
# polling stops and resumes. ONE INFO line on resume so a user-reported
# "preview went black" can be correlated with server-side evidence. The
# threshold is ADAPTIVE — a slow twilight camera's normal cadence is many
# seconds, so a fixed 5 s would spam the log every cycle.
_CLIENT_GAP_FLOOR_S = 5.0
_CLIENT_GAP_FACTOR = 2.5
_CLIENT_GAP_IDLE_S = 600.0  # a >10-min silence is a fresh session, not a drop
_CLIENT_GAP_MAX_ENTRIES = 128
_CLIENT_GAP_STATE: dict[tuple, dict] = {}


def note_client_request(cam_id: str) -> None:
    """Record this client's request time; log one INFO line when the gap
    since its previous request is abnormally large (a likely drop).

    Detection is retroactive — the gap is measured on the request that
    ENDS it, which is exactly the moment it becomes knowable.
    """
    fwd = request.headers.get("X-Forwarded-For")
    client_ip = (fwd or request.remote_addr or "?").split(",")[0].strip()
    key = (cam_id, client_ip)
    now = _time.time()
    state = _CLIENT_GAP_STATE.get(key)
    if state is None:
        _CLIENT_GAP_STATE[key] = {"last": now, "ema": 0.0}
    else:
        gap = now - float(state.get("last", now))
        ema = float(state.get("ema", 0.0)) or gap
        threshold = max(_CLIENT_GAP_FLOOR_S, _CLIENT_GAP_FACTOR * ema)
        if threshold < gap < _CLIENT_GAP_IDLE_S:
            log.info(
                "[http] test-detection client gap · cam=%s client=%s "
                "last_request_at=%s gap=%.1fs (cadence≈%.1fs)",
                cam_id,
                client_ip,
                _time.strftime("%H:%M:%S", _time.localtime(float(state["last"]))),
                gap,
                ema,
            )
        # Don't let a one-off drop dominate the cadence EMA.
        state["ema"] = (0.3 * gap + 0.7 * ema) if gap < _CLIENT_GAP_IDLE_S else ema
        state["last"] = now
    if len(_CLIENT_GAP_STATE) > _CLIENT_GAP_MAX_ENTRIES:
        cutoff = now - _CLIENT_GAP_IDLE_S
        for stale in [k for k, v in _CLIENT_GAP_STATE.items() if float(v.get("last", 0)) < cutoff]:
            _CLIENT_GAP_STATE.pop(stale, None)


def newest_main_frame(rt):
    """``(frame_copy, arrival_ts)`` for the camera's newest main frame.

    Reads the runtime's drained reader slot, which holds the frame that
    came off the wire most recently, stamped when it ARRIVED — not when
    the main loop got round to storing it. The fallback (runtimes without
    the drained capture, e.g. HTTP-snapshot cameras) reads ``rt.frame``
    with its decode-time ``frame_ts``.
    """
    getter = getattr(rt, "latest_main_frame", None)
    if callable(getter):
        frame, ts = getter()
        # The reader publishes a fresh array per frame and never mutates
        # a published one, so copying outside rt.lock is safe.
        return (frame.copy() if frame is not None else None), float(ts or 0.0)
    with rt.lock:
        frame = rt.frame.copy() if rt.frame is not None else None
        ts = float(getattr(rt, "frame_ts", 0.0) or 0.0)
    return frame, ts


def capture_lag_s(rt):
    """Seconds the runtime's decoder trails real time, or None."""
    getter = getattr(rt, "capture_lag_s", None)
    return getter() if callable(getter) else None


@dataclass
class FramePick:
    """Everything the handler needs to know about the served frame."""

    frame: Any = None
    ts: float = 0.0
    src: str = ""
    outcome: str = "no_frame"
    waited_s: float = 0.0
    retries: int = 0
    last_candidate_ts: float = 0.0
    saw_frame: bool = False
    saw_fresh: bool = False
    validator_reason: str = ""
    profile: Any = None
    # Age of the served PIXELS, frozen when the wait loop ends. ts is an
    # arrival timestamp on both stream paths, so this is the real age of
    # the picture, not the age of the decode.
    age_ms: int = 0

    def failure(self) -> tuple[str, str]:
        """``(code, german_message)`` for the 503 body."""
        if not self.saw_frame:
            return "no_frame", "Kamera liefert noch keine Frames"
        if not self.saw_fresh:
            return "stale", "Stream-Puffer hinkt zurück — kein frischer Frame innerhalb 2.5 s"
        return "corrupt", "Stream liefert nur korrupte Frames"


def acquire_frame(rt, cam_id: str, stream_pref: str) -> FramePick:
    """Poll for a frame that clears the freshness + decoder-strip bars.

    The richer ``is_valid_frame`` validator (bright_outlier_dark_scene,
    grey_toned, dead_area, …) is deliberately NOT applied: it gates the
    ALARM pipeline against frames that look broken to a human, and this
    view's job is the opposite — show what Coral sees on the CURRENT
    frame, whatever it looks like. Applying it here produced ~60 %
    rejection on the Garten-Dachterrasse twilight scene and made the UI
    show stale state. ``has_corrupt_strip`` stays because a pink/rainbow
    bottom strip is a narrow decoder artefact that only produces
    spurious detections on garbage chroma. The trace states the skip.
    """
    from ..frame_helpers import has_corrupt_strip, pick_profile_from_baseline

    pick = FramePick()
    started_at = _time.time()
    deadline = _time.monotonic() + FRESH_POLL_WINDOW_S
    order = ("main", "sub") if stream_pref == "main" else ("sub", "main")
    while _time.monotonic() < deadline:
        picked = False
        for which in order:
            if which == "sub":
                picked = _read_sub(rt, pick, started_at, pick_profile_from_baseline)
            else:
                picked = _read_main(
                    rt, pick, started_at, cam_id, has_corrupt_strip, pick_profile_from_baseline
                )
            if picked:
                break
        pick.retries += 1
        if picked:
            break
        _time.sleep(0.05)
    pick.waited_s = _time.time() - started_at
    if pick.frame is not None:
        pick.age_ms = int((_time.time() - pick.ts) * 1000) if pick.ts else 0
        _warn_on_fallback(cam_id, stream_pref, pick.src)
    return pick


def _read_sub(rt, pick: FramePick, started_at: float, pick_profile) -> bool:
    """Sub-stream candidate. Freshness only — the sub is a clean H.264
    preview, so the corrupt-strip signature does not apply to it."""
    with rt.lock:
        cand = rt._preview_frame.copy() if rt._preview_frame is not None else None
        cand_ts = float(getattr(rt, "_preview_frame_ts", 0.0) or 0.0)
    if cand is None:
        return False
    pick.saw_frame = True
    pick.last_candidate_ts = max(pick.last_candidate_ts, cand_ts)
    # _preview_frame_ts is written by _preview_loop the moment its read()
    # returns, so it is an arrival stamp, not a decode-time stamp.
    if cand_ts < started_at - FRESH_GRACE_S:
        if pick.outcome != "corrupt":
            pick.outcome = "stale"
        return False
    pick.frame = cand
    pick.ts = cand_ts
    pick.saw_fresh = True
    pick.profile = pick_profile([cand])
    pick.src = "sub"
    pick.outcome = "ok"
    return True


def _read_main(
    rt, pick: FramePick, started_at: float, cam_id: str, has_corrupt_strip, pick_profile
) -> bool:
    """Main-stream candidate — freshness, decoder lag, corrupt strip."""
    cand, cand_ts = newest_main_frame(rt)
    if cand is None:
        return False
    pick.saw_frame = True
    pick.last_candidate_ts = max(pick.last_candidate_ts, cand_ts)
    if cand_ts < started_at - FRESH_GRACE_S:
        if pick.outcome != "corrupt":
            pick.outcome = "stale"
        return False
    # Second half of the freshness contract: a decoder that cannot keep
    # up delivers old pixels that still ARRIVE just now.
    lag_s = capture_lag_s(rt)
    if lag_s is not None and lag_s > MAX_CAPTURE_LAG_S:
        if pick.outcome != "corrupt":
            pick.outcome = "stale"
        pick.validator_reason = f"capture_lag={lag_s:.1f}s"
        return False
    pick.saw_fresh = True
    pick.profile = pick_profile([cand])
    if has_corrupt_strip(cand):
        pick.outcome = "corrupt"
        pick.validator_reason = "has_corrupt_strip"
        log.info("[test-detection] %s rejected candidate · strip=True", cam_id)
        return False
    pick.frame = cand
    pick.ts = cand_ts
    pick.src = "main"
    pick.outcome = "ok"
    return True


def _warn_on_fallback(cam_id: str, stream_pref: str, used: str) -> None:
    if used == stream_pref:
        return
    now_ts = _time.time()
    if now_ts - _FALLBACK_WARN_TS.get(cam_id, 0.0) <= 60.0:
        return
    _FALLBACK_WARN_TS[cam_id] = now_ts
    log.warning(
        "[test-detection] cam=%s preferred stream '%s' unavailable, served '%s'",
        cam_id,
        stream_pref,
        used,
    )


def encode_snapshot(frame, rows: list, skip: bool) -> tuple:
    """``(data_url_or_None, w, h, scale)`` for the panel's inline image.

    Downscaled to ≤960 px: inference already ran on the full-resolution
    frame, and a 1920×1080 base64 snapshot at 1 Hz turns iOS Safari into
    molasses without any actual stream problem. Bbox coordinates are
    rewritten into the same space so the SVG viewBox lines up.
    ``skip`` is the ``?no_snapshot=1`` path — the frontend drives the
    video from the MJPEG stream and needs only the boxes, which cuts the
    response from ~106 kB to ~1 kB.
    """
    src_h, src_w = frame.shape[:2]
    if skip:
        return None, src_w, src_h, 1.0
    target_w = 960
    scale = 1.0
    snap_w, snap_h = src_w, src_h
    snap_frame = frame
    if src_w > target_w:
        scale = target_w / float(src_w)
        snap_w = target_w
        snap_h = max(2, int(round(src_h * scale)) // 2 * 2)
        snap_frame = cv2.resize(frame, (snap_w, snap_h), interpolation=cv2.INTER_AREA)
        # Skip the multiplication entirely on the no-op path so rounding
        # never nudges an integer bbox off the source frame.
        for r in rows:
            x, y, w_box, h_box = r["bbox"]
            r["bbox"] = [
                int(round(x * scale)),
                int(round(y * scale)),
                int(round(w_box * scale)),
                int(round(h_box * scale)),
            ]
    try:
        import base64

        ok, jpg = cv2.imencode(
            ".jpg",
            snap_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 65, int(cv2.IMWRITE_JPEG_OPTIMIZE), 1],
        )
        url = f"data:image/jpeg;base64,{base64.b64encode(jpg.tobytes()).decode()}" if ok else None
    except Exception as e:  # noqa: BLE001 — a failed encode must not 500
        log.warning("[test-detection] snapshot encode failed: %s", e)
        url = None
    return url, snap_w, snap_h, scale
