"""Pre-roll ring lifecycle for the weather event timelapse.

One capture thread per opted-in camera, owning the whole cycle the user
described: roll and discard, retain on trigger, keep writing forward,
build the video at the end. The bounded on-disk ring itself lives in
``_event_tl_ring.py`` — this module is the service-side wiring (start /
stop / sync / handover / cleanup) and holds no frame data of its own.

The design rule this module exists to enforce: **there is never a second
capture loop.** The ring loop and the forward capture use the same frame
source at the same cadence, and exactly one of them runs per camera at a
time — the ring loop exits the moment its ring is armed, and
``_event_tl_inflight`` keeps ``_sync_event_tl_rings`` from restarting it
underneath a running capture.
"""

from __future__ import annotations

import contextlib
import shutil
import threading
import time
from pathlib import Path

from ._consts import log
from ._event_tl_ring import (
    _RING_REPICK_S,
    DEFAULT_PREBUFFER_MAX_MB,
    DEFAULT_PREBUFFER_MIN,
    DEFAULT_PREBUFFER_MODE,
    DEFAULT_WATCH_GRACE_MIN,
    PREBUFFER_DIR_NAME,
    PREBUFFER_MODES,
    EventTLRing,
    purge_event_tl_scratch,
)


class EventTLPrebufferMixin:
    """Ring lifecycle for WeatherService: one capture thread per camera.

    Mixin for WeatherService — reads `self.cfg`, `self.runtimes`,
    `self.settings_store` off the concrete class.
    """

    # ── State ───────────────────────────────────────────────────────────
    def _event_tl_ring_state(self) -> dict:
        # Lazy attr — keeps WeatherService.__init__ unchanged, same
        # pattern as _event_tl_state().
        if not hasattr(self, "_event_tl_ring_dict"):
            self._event_tl_ring_dict = {
                "rings": {},  # cam_id -> EventTLRing
                "threads": {},  # cam_id -> (Thread, threading.Event)
                "inflight": set(),  # cam_ids with a capture running
                "watch_until": {},  # cam_id -> unix ts the watch expires
                "lock": threading.Lock(),
                "booted": False,
            }
        return self._event_tl_ring_dict

    def _event_tl_global_cfg(self) -> dict:
        """Global cost caps from ``weather.event_timelapse``."""
        g = (self.cfg.get("event_timelapse") or {}) if isinstance(self.cfg, dict) else {}
        return {
            "max_bytes": max(1, int(g.get("prebuffer_max_mb", DEFAULT_PREBUFFER_MAX_MB) or 1))
            * 1024
            * 1024,
            "watch_grace_s": max(60, int(g.get("watch_grace_min", DEFAULT_WATCH_GRACE_MIN) or 1))
            * 60,
        }

    @staticmethod
    def _event_tl_prebuffer_cfg(evt_cfg: dict) -> tuple:
        """(mode, prebuffer_min, interval_s) from a per-camera
        event_timelapse block, coerced through the shared schema so a
        hand-edited settings.json with ``"prebuffer_min": "15"`` still
        loads. Cameras that predate the key fall back to the shipped
        default rather than to "no pre-roll"."""
        from ..schema import WEATHER_EVENT_TL_SCHEMA, validate_and_coerce

        try:
            cfg = validate_and_coerce(evt_cfg or {}, WEATHER_EVENT_TL_SCHEMA)
        except ValueError as e:
            log.warning("[weather] event_timelapse config rejected (%s) — pre-roll off", e)
            return "off", 0, 8
        mode = str(cfg.get("prebuffer_mode") or DEFAULT_PREBUFFER_MODE).strip().lower()
        if mode not in PREBUFFER_MODES:
            mode = DEFAULT_PREBUFFER_MODE
        pre_min = int(cfg.get("prebuffer_min", DEFAULT_PREBUFFER_MIN))
        if pre_min < 0:
            pre_min = 0
        interval_s = max(1, int(cfg.get("interval_s", 8) or 8))
        if pre_min == 0:
            mode = "off"
        return mode, pre_min, interval_s

    def _event_tl_ring_dir(self, cam_id: str) -> Path:
        return self._sightings_dir() / cam_id / "event_timelapse" / PREBUFFER_DIR_NAME

    # ── Boot / teardown ─────────────────────────────────────────────────
    def _event_tl_boot_cleanup(self) -> None:
        """Purge orphan rings / scratch dirs / part-encodes. Runs once
        per service instance — `_sync_event_tl_rings` must never call
        this, it would delete a live ring."""
        st = self._event_tl_ring_state()
        if st["booted"]:
            return
        st["booted"] = True
        with contextlib.suppress(Exception):
            purge_event_tl_scratch(self._sightings_dir())

    def _stop_event_tl_prebuffers(self) -> None:
        """Stop every ring loop and delete every ring directory. Called
        from shutdown() and reload()."""
        st = self._event_tl_ring_state()
        for cam_id in list(st["threads"].keys()):
            self._stop_event_tl_ring(cam_id, purge=True)
        st["watch_until"].clear()

    def _stop_event_tl_ring(self, cam_id: str, purge: bool = True) -> None:
        st = self._event_tl_ring_state()
        entry = st["threads"].pop(cam_id, None)
        if entry is not None:
            thread, stop_ev = entry
            stop_ev.set()
            with contextlib.suppress(Exception):
                thread.join(timeout=3.0)
        ring = st["rings"].pop(cam_id, None) if purge else None
        if ring is not None:
            ring.purge()

    # ── Watch / sync ────────────────────────────────────────────────────
    def _event_tl_note_watch(self, cam_id: str, active: bool, reason: str) -> bool:
        """Extend (or let expire) the risk window for one camera. Returns
        whether the camera is inside its watch window right now.

        The grace period is what keeps a flickering forecast from wiping
        a half-full ring: one poll saying "elevated" keeps the ring alive
        for ``watch_grace_min`` minutes regardless of what the next poll
        says."""
        st = self._event_tl_ring_state()
        grace_s = self._event_tl_global_cfg()["watch_grace_s"]
        now = time.time()
        prev = st["watch_until"].get(cam_id, 0.0)
        if active:
            if prev <= now:
                log.info(
                    "[weather] Prebuffer-Watch armed on %s (%s)", self._cam_name(cam_id), reason
                )
            st["watch_until"][cam_id] = now + grace_s
            return True
        if prev > now:
            return True
        if prev:
            st["watch_until"].pop(cam_id, None)
            log.info("[weather] Prebuffer-Watch expired on %s", self._cam_name(cam_id))
        return False

    def _sync_event_tl_rings(self, slices: list) -> None:
        """Start / stop one ring loop per camera. Driven from the weather
        poll, so it also picks up cameras enabled or disabled at runtime.

        A camera with a capture in flight is skipped entirely: its ring
        has already been handed over and restarting the loop would put a
        second hires grabber on the same camera."""
        st = self._event_tl_ring_state()
        wanted: dict = {}
        for cam in self._cfg_cameras():
            cam_id = cam.get("id")
            if not cam_id:
                continue
            cw = cam.get("weather") or {}
            evt_cfg = cw.get("event_timelapse") or {}
            if not cw.get("enabled") or not evt_cfg.get("enabled"):
                continue
            mode, pre_min, interval_s = self._event_tl_prebuffer_cfg(evt_cfg)
            if mode == "off":
                continue
            if mode == "armed":
                active, reason = self._event_tl_watch_active(slices, evt_cfg)
                if not self._event_tl_note_watch(cam_id, active, reason):
                    continue
            wanted[cam_id] = (pre_min, interval_s)
        for cam_id in list(st["threads"].keys()):
            if cam_id not in wanted:
                self._stop_event_tl_ring(cam_id, purge=True)
        with st["lock"]:
            inflight = set(st["inflight"])
        for cam_id, (pre_min, interval_s) in wanted.items():
            if cam_id in inflight or cam_id in st["threads"]:
                continue
            self._start_event_tl_ring(cam_id, pre_min, interval_s)

    def _start_event_tl_ring(self, cam_id: str, pre_min: int, interval_s: int) -> None:
        st = self._event_tl_ring_state()
        capacity = max(1, -(-(pre_min * 60) // max(1, interval_s)))  # ceil
        ring_dir = self._event_tl_ring_dir(cam_id)
        shutil.rmtree(ring_dir, ignore_errors=True)
        try:
            ring = EventTLRing(ring_dir, capacity, self._event_tl_global_cfg()["max_bytes"])
        except Exception as e:
            log.warning("[weather] prebuffer start failed on %s: %s", self._cam_name(cam_id), e)
            return
        stop_ev = threading.Event()
        thread = threading.Thread(
            target=self._event_tl_ring_loop,
            args=(cam_id, ring, stop_ev, interval_s),
            daemon=True,
            name=f"weather-evt-tl-ring-{cam_id}",
        )
        st["rings"][cam_id] = ring
        st["threads"][cam_id] = (thread, stop_ev)
        thread.start()
        log.info(
            "[weather] Prebuffer rolling on %s · %d min / %d Frames à %ds",
            self._cam_name(cam_id),
            pre_min,
            capacity,
            interval_s,
        )

    # ── The rolling loop ────────────────────────────────────────────────
    def _event_tl_ring_loop(self, cam_id, ring, stop_ev, interval_s: int) -> None:
        """One hires grab every ``interval_s`` into the ring. Exits when
        the ring is armed (the capture takes over) or on stop."""
        from ..frame_helpers import grab_valid_frame, pick_profile_from_baseline

        profile = pick_profile_from_baseline([])
        last_repick = 0.0
        while not stop_ev.is_set() and not ring.armed:
            rt = self.runtimes.get(cam_id)
            if rt is None or not hasattr(rt, "snapshot_jpeg_hires"):
                # Camera offline / rebuilt. Keep the ring — the frames
                # already in it are still valid pre-roll — and retry on
                # the next tick rather than tearing the loop down.
                if stop_ev.wait(interval_s):
                    break
                continue
            jpg, _attempt, _reason = grab_valid_frame(
                lambda: rt.snapshot_jpeg_hires(quality=92), profile=profile
            )
            if jpg:
                ring.push(jpg)
                now = time.monotonic()
                if now - last_repick >= _RING_REPICK_S:
                    # Free re-pick: reuse the frame we just captured
                    # instead of spending an extra grab on the camera.
                    with contextlib.suppress(Exception):
                        profile = pick_profile_from_baseline([jpg])
                    last_repick = now
            if stop_ev.wait(interval_s):
                break

    # ── Handover to the capture ─────────────────────────────────────────
    def _event_tl_claim_capture(self, cam_id: str) -> bool:
        """Reserve the camera for one capture. False when a capture is
        already running — the guard against two triggers landing in quick
        succession and both consuming the same ring."""
        st = self._event_tl_ring_state()
        with st["lock"]:
            if cam_id in st["inflight"]:
                return False
            st["inflight"].add(cam_id)
        return True

    def _event_tl_release_capture(self, cam_id: str) -> None:
        st = self._event_tl_ring_state()
        with st["lock"]:
            st["inflight"].discard(cam_id)
        # Ring dir is gone with the handover (frames were moved into the
        # capture scratch); drop the object so the next sync builds a
        # fresh one.
        self._stop_event_tl_ring(cam_id, purge=True)

    def _event_tl_take_preroll(self, cam_id: str, frames_dir: Path) -> int:
        """Arm the ring, stop its loop and move the retained frames into
        the capture's scratch dir as ``00000.jpg`` upward.

        Returns the number of pre-roll frames now sitting in
        ``frames_dir`` — the index the forward capture continues from, so
        a plain ``sorted(glob("*.jpg"))`` stays chronological across the
        pre/post seam. Zero is a normal outcome (ring never armed, camera
        was offline, feature off) and the caller must still produce the
        forward-looking clip.
        """
        st = self._event_tl_ring_state()
        ring = st["rings"].get(cam_id)
        if ring is None:
            return 0
        ring.arm()
        entry = st["threads"].get(cam_id)
        if entry is not None:
            _thread, stop_ev = entry
            stop_ev.set()
        frames = ring.frames()
        moved = 0
        for src in frames:
            dst = frames_dir / ("%05d.jpg" % moved)
            try:
                src.replace(dst)
                moved += 1
            except Exception as e:
                log.warning("[weather] pre-roll move failed %s: %s", src.name, e)
        if moved:
            log.info(
                "[weather] Pre-roll retained on %s: %d Frames (%.1f MB)",
                self._cam_name(cam_id),
                moved,
                ring.bytes_held / (1024 * 1024),
            )
        return moved
