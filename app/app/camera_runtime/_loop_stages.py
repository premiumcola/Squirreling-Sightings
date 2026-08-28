from __future__ import annotations

import os
import time
from pathlib import Path

import cv2

from ._consts import log, log_cam


class LoopStagesMixin:
    """Three stages lifted out of ``_loop``.

    ``camera_runtime/_main_loop`` was 1040 lines before this commit —
    twice CLAUDE.md's 500-line ceiling — with ``_loop`` itself one
    ~780-line function. These are the three blocks with no back-edge into
    the loop's control flow: each takes what it needs, returns, and
    changes nothing about the order things happen in. Pure code motion.

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (confirmer, store, notifier, config) which live on the concrete class.
    """

    def _confirmed_labels(self, detections: list, spawn_for) -> list:
        """Labels that cleared the N-of-M confirmation window this frame."""
        # N-of-M confirmation gate. Dedupe by label per frame so a
        # frame with three concurrent persons counts as ONE hit
        # for "person" — the window measures temporal persistence,
        # not per-frame multiplicity. Detections still appear in
        # the live preview overlay (drawn already paints them);
        # only the trigger pipeline downstream filters on the
        # confirmed labels.
        #
        # Score gate: only detections at-or-above the per-label
        # spawn threshold count toward the confirmation window.
        # The two-tier tracker keeps a track alive on tentative
        # (< spawn) samples once it has been spawned at-or-above
        # threshold, so an unconditional confirmer.check() would
        # fire on the low-confidence tail of a sighting whose
        # CURRENT score is well under the configured threshold
        # (e.g. a person briefly seen at 60%, then dropping to
        # 23% for many frames — old behaviour: confirmation
        # stayed live, sub-threshold dips even re-fired after
        # the 2× window decay). Ongoing sightings still
        # propagate via is_confirmed so an already-running clip
        # carries the label across its tail.
        cw_cfg = self.cfg.get("confirmation_window") or {}
        confirmed_object_labels: list[str] = []
        _seen_this_frame: set[str] = set()
        for d in detections:
            if d.label in _seen_this_frame:
                if self._confirmer.is_confirmed(self.camera_id, d.label):
                    confirmed_object_labels.append(d.label)
                continue
            _seen_this_frame.add(d.label)
            cw = cw_cfg.get(d.label) or {}
            n = max(1, int(cw.get("n", 3)))
            secs = max(0.5, float(cw.get("seconds", 5.0)))
            spawn_threshold = spawn_for(d.label)
            if float(d.score) < spawn_threshold:
                # Sub-threshold continuation — counts in tracking
                # but NOT toward the recording-trigger
                # confirmation. Surface ongoing sightings only.
                if self._confirmer.is_confirmed(self.camera_id, d.label):
                    confirmed_object_labels.append(d.label)
                log.debug(
                    "[cam:%s] ↓ sub-threshold: %s %d%% " "(< spawn %d%%) — Bestätigung unverändert",
                    self.camera_id,
                    d.label,
                    int(round(d.score * 100)),
                    int(round(spawn_threshold * 100)),
                )
                continue
            fired = self._confirmer.check(self.camera_id, d.label, n, secs)
            if fired:
                cur = self._confirmer.current_count(self.camera_id, d.label)
                log.info(
                    "[cam:%s] ✅ BESTÄTIGT: %s — %d Treffer in %.1fs → Alert ausgelöst",
                    self.camera_id,
                    d.label,
                    cur,
                    secs,
                )
                confirmed_object_labels.append(d.label)
            elif self._confirmer.is_confirmed(self.camera_id, d.label):
                confirmed_object_labels.append(d.label)
            else:
                cur = self._confirmer.current_count(self.camera_id, d.label)
                log.info(
                    "[cam:%s] ⏳ wartend: %s %d%% (Bestätigung %d/%d in %.1fs)",
                    self.camera_id,
                    d.label,
                    int(round(d.score * 100)),
                    cur,
                    n,
                    secs,
                )
        return confirmed_object_labels

    def _save_snapshot_event(
        self, now_dt, labels: list, detections: list, drawn, effective_bbox, cooldown: int
    ) -> None:
        """Snapshot-camera event: JPEG + event JSON + MQTT + Telegram.

        The branch a camera without an ``rtsp_url`` takes instead of the
        pre-buffer / ffmpeg recording path.
        """
        has_person = "person" in labels
        elapsed = (now_dt - self.last_event_at).total_seconds()
        if labels and (has_person or elapsed >= cooldown):
            self.last_event_at = now_dt
            self.event_counter_today += 1
            ts = now_dt
            event_id = ts.strftime("%Y%m%d-%H%M%S-%f")
            day_dir = (
                Path(self.global_cfg["storage"]["root"])
                / "motion_detection"
                / self.camera_id
                / ts.strftime("%Y-%m-%d")
            )
            day_dir.mkdir(parents=True, exist_ok=True)
            # Build event meta first so we know whether the
            # zone(s) the detections fell into actually want a
            # photo saved. save_photo:false zones still log the
            # event JSON but skip the JPEG write.
            ev_meta = self._build_event_meta(ts, labels, detections, drawn, effective_bbox)
            snap_path = day_dir / f"{event_id}.jpg"
            rel = snap_path.relative_to(Path(self.global_cfg["storage"]["root"]))
            public_base = (self.global_cfg.get("server", {}).get("public_base_url") or "").rstrip(
                "/"
            )
            snapshot_url = None
            if ev_meta.get("save_photo", True):
                snapshot_url = self._write_snapshot_jpeg(
                    snap_path, rel, drawn, effective_bbox, public_base
                )
            event = {
                "event_id": event_id,
                "camera_id": self.camera_id,
                "camera_name": self.cfg.get("name", self.camera_id),
                "armed": bool(self.cfg.get("armed", True)),
                "after_hours": ev_meta["after_hours"],
                "alarm_level": ev_meta["alarm_level"],
                "time": ts.isoformat(timespec="seconds"),
                "labels": ev_meta["labels"],
                "top_label": ev_meta["top_label"],
                "bird_species": ev_meta["bird_species"],
                "cat_name": ev_meta["cat_name"],
                "person_name": ev_meta["person_name"],
                "whitelisted": ev_meta["whitelisted"],
                "detections": ev_meta["detections"],
                "snapshot_url": snapshot_url,
                "snapshot_relpath": rel.as_posix() if snapshot_url else None,
                "video_url": None,
                "video_relpath": None,
            }
            self.store.add_event(self.camera_id, event)
            self._dispatch_snapshot_event(event, ev_meta, snap_path, snapshot_url, public_base)

    def _write_snapshot_jpeg(self, snap_path, rel, drawn, effective_bbox, public_base):
        """Write the event JPEG (motion box drawn on, downscaled to 1280
        wide) and return its public URL, or None when no base URL is set."""
        save_frame = drawn.copy()
        if effective_bbox is not None:
            mx, my, mw, mh = effective_bbox
            cv2.rectangle(save_frame, (mx, my), (mx + mw, my + mh), (0, 220, 0), 2)
        h_px, w_px = save_frame.shape[:2]
        if w_px > 1280:
            scale = 1280 / w_px
            save_frame = cv2.resize(
                save_frame, (1280, int(h_px * scale)), interpolation=cv2.INTER_AREA
            )
        cv2.imwrite(str(snap_path), save_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        return f"{public_base}/media/{rel.as_posix()}" if public_base else None

    def _dispatch_snapshot_event(
        self, event: dict, ev_meta: dict, snap_path, snapshot_url, public_base: str
    ) -> None:
        """MQTT publish + the Telegram alert, with the three independent
        mutes ("Stumm" camera, telegram_enabled, zone send_telegram)."""
        if self.mqtt and self.cfg.get("mqtt_enabled", True):
            self.mqtt.publish(f"events/{self.camera_id}", event)
        _send_tg = ev_meta["notify"] and self.cfg.get("telegram_enabled", True)
        # Defensive: "Stumm" cameras never send Telegram.
        if not self.cfg.get("armed", True):
            _send_tg = False
        if not ev_meta.get("send_telegram", True):
            _send_tg = False
        if not (_send_tg and self.notifier):
            return
        # Only attach the JPEG when one was actually written. If
        # save_photo was off, fall back to the in-memory thumb_bytes.
        thumb = ev_meta.get("thumb_bytes")
        if snapshot_url:
            try:
                with open(snap_path, "rb") as fh:
                    thumb = fh.read()
            except Exception:
                pass
        self.notifier.send_alert_sync(
            caption=(
                f"ℹ️ {', '.join(ev_meta['labels'])}\n"
                f"📷 {self.cfg.get('name', self.camera_id)}\n"
                f"🕒 {event['time']}"
            ),
            jpeg_bytes=thumb,
            snapshot_url=snapshot_url,
            dashboard_url=public_base,
            camera_id=self.camera_id,
        )

    def _handle_loop_error(self, e: Exception) -> None:
        """One failed frame: streak bookkeeping, backoff, capture release.

        Escalating log levels (debug at 1, warning at 5, error at 15 and
        every 30 after) so a transient dropout stays quiet and a dead
        stream does not.
        """
        self._error_streak += 1
        self.last_error = str(e)
        # V81 · per-failure diagnostic. Env-gated so non-flapping
        # installs pay zero log overhead. Uses the existing
        # _last_rtsp_success_ts (set on every successful grab)
        # as the "since last good frame" timestamp.
        if os.getenv("FLAP_DIAG", "").lower() in ("1", "true", "yes"):
            _last_ok = self._last_rtsp_success_ts or 0.0
            _since = (time.time() - _last_ok) if _last_ok else -1.0
            _reconnects_24h = len([t for t in self._reconnect_log if time.time() - t < 86400])
            log.info(
                "[cam:%s][flap] streak=%d err=%s:%s since_last_ok=%.1fs reconnects_24h=%d",
                self.camera_id,
                self._error_streak,
                type(e).__name__,
                str(e)[:200],
                _since,
                _reconnects_24h,
            )
        if self._error_streak == 1:
            log.debug("[%s] Frame lesen fehlgeschlagen: %s", self.camera_id, e)
        elif self._error_streak == 5:
            log_cam.warning(
                "[%s] Verbindungsprobleme – %d aufeinanderfolgende Fehler: %s",
                self.camera_id,
                self._error_streak,
                e,
            )
        elif self._error_streak == 15 or (self._error_streak > 15 and self._error_streak % 30 == 0):
            log.error(
                "[%s] Stream verloren (streak=%d): %s",
                self.camera_id,
                self._error_streak,
                e,
            )
        try:
            if self.capture is not None:
                self.capture.release()
        except Exception:
            pass
        self.capture = None
        self._reconnect_count += 1
        self._reconnect_log.append(time.time())
        # Short backoff for transient dropouts, longer for persistent failures
        sleep_t = 2.0 if self._error_streak <= 3 else min(30.0, 5.0 * (self._error_streak // 5 + 1))
        time.sleep(sleep_t)
