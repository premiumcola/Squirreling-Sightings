"""The one place a finalized motion event is published.

Why this exists — the most consequential bug found in this codebase:

There are two ways a motion clip is finalized. When ffmpeg is available
(always, in the container) the clip is recorded by an ffmpeg subprocess
and finalized by ``_reencode_motion_clip``. Only when ffmpeg is missing
does the OpenCV frame-buffer path ``_finalize_motion_clip`` run.

Every downstream consequence of an event — the first-since marker, the
achievement unlock, the quest re-evaluation, the bird dossier, and above
all the **Telegram alert** — lived in ``_finalize_motion_clip`` alone.
So on every real deployment none of them ever ran. Clips were recorded,
events appeared in the library, MQTT fired, and the alert never left the
building. Not even a log line: the push gates were never reached, so
nothing could report being blocked.

The comment that had been left in the ffmpeg path made the belief
explicit — that the alert "is fired once, by the modern push pipeline in
_finalize_motion_clip". It was removed there as a duplicate. It was not
a duplicate; it was the only one that ran.

Both paths now end here. Adding a consequence to an event means adding
it once, in this file, and both recording modes get it.
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

from .._consts import log


# Minimum seconds between two ticker messages for the same camera. The
# ticker exists to answer "is it recording right now?" while someone
# walks in front of a camera; without a floor a busy scene would send a
# pair every few seconds and become the noise it is meant to cut through.
_TICKER_MIN_GAP_S = 20.0


class PublishMixin:
    def _ticker_enabled(self) -> bool:
        """Whether the recording ticker is on for this camera.

        Deliberately independent of the alert path. The ticker answers
        "is the camera recording me right now?" during a walk-in test —
        it must therefore survive every gate that could silence a real
        alert (severity matrix, push thresholds, quiet hours, schedule),
        because those gates are frequently the very thing being
        diagnosed. It still respects `telegram_enabled` and `armed`,
        which are the operator's explicit "this camera is off" switches.
        """
        if not (self.notifier and self.cfg.get("telegram_enabled", True)):
            return False
        if not self.cfg.get("armed", True):
            return False
        tg = (self.global_cfg.get("telegram") or {}) if self.global_cfg else {}
        cam_pref = self.cfg.get("recording_ticker")
        if cam_pref is not None:
            return bool(cam_pref)
        return bool(tg.get("recording_ticker", True))

    def _send_ticker(self, text: str) -> None:
        """Fire-and-forget one-line status message. Never raises."""
        try:
            now = time.monotonic()
            if now - getattr(self, "_ticker_last_ts", 0.0) < _TICKER_MIN_GAP_S:
                return
            self._ticker_last_ts = now
            threading.Thread(
                target=self.notifier.send_alert_sync,
                kwargs={"caption": text, "camera_id": self.camera_id},
                daemon=True,
            ).start()
        except Exception as e:
            log.debug("[%s] ticker send skipped: %s", self.camera_id, e)

    def notify_recording_started(self, labels, event_id: str | None = None) -> None:
        """Ticker: a clip just started."""
        if not self._ticker_enabled():
            return
        what = ", ".join(sorted(set(labels))) if labels else "Bewegung"
        self._send_ticker(
            f"🔴 Aufnahme gestartet · {self.cfg.get('name', self.camera_id)}\n" f"Erkannt: {what}"
        )

    def notify_recording_finished(self, meta: dict, duration_s: float | None) -> None:
        """Ticker: the clip ended — the cue that it is safe to walk in again."""
        if not self._ticker_enabled():
            return
        # Bypass the gap floor here: a start without its matching end
        # would leave the user waiting for a signal that never comes,
        # which is worse than one extra message.
        self._ticker_last_ts = 0.0
        labels = meta.get("labels") or []
        what = ", ".join(sorted(set(labels))) if labels else "Bewegung"
        dur = f"{duration_s:.0f} s" if duration_s else "—"
        self._send_ticker(
            f"⏹ Aufnahme beendet · {self.cfg.get('name', self.camera_id)}\n"
            f"Dauer: {dur} · Erkannt: {what}"
        )

    def _apply_first_since(self, event: dict, meta: dict) -> None:
        """F06 marker. Mutates both dicts so the JSON on disk carries it
        AND the alert caption can read it without a second store read."""
        try:
            from .... import app_state as _app_state

            detector = getattr(_app_state, "first_since_detector", None)
            if detector is None:
                return
            marker = detector.evaluate(event)
            if marker:
                event["first_since"] = marker
                meta["first_since"] = marker
        except Exception as e:
            log.debug("[%s] first_since skipped: %s", self.camera_id, e)

    def _publish_mqtt(self, event: dict) -> None:
        if not (self.mqtt and self.cfg.get("mqtt_enabled", True)):
            return
        with contextlib.suppress(Exception):
            self.mqtt.publish(f"events/{self.camera_id}", event)

    def _publish_achievement(self, meta: dict) -> None:
        species = meta.get("bird_species")
        if not species:
            return
        try:
            if not self._try_unlock_achievement(species, species):
                return
            if not self.notifier:
                return
            msg = (
                f"🌿 Neue Sichtung entdeckt: {species}!\n"
                f"📷 Kamera: {self.cfg.get('name', self.camera_id)}"
            )
            threading.Thread(
                target=self.notifier.send_alert_sync,
                kwargs={"caption": msg},
                daemon=True,
            ).start()
        except Exception as e:
            log.debug("[%s] achievement hook skipped: %s", self.camera_id, e)

    def _publish_quests(self) -> None:
        """F09 · full re-evaluation per event. The hourly job is the
        safety net; this keeps the pinboard current without the wait."""
        try:
            from ....quests import reevaluate_and_save

            threading.Thread(target=reevaluate_and_save, daemon=True).start()
        except Exception as e:
            log.debug("[%s] quest re-eval skipped: %s", self.camera_id, e)

    def _publish_dossiers(self, meta: dict, event_id: str) -> None:
        """F08 · register every species_latin in this event."""
        try:
            from .... import app_state as _app_state

            svc = getattr(_app_state, "bird_dossiers", None)
            if svc is None:
                return
            seen: set[str] = set()
            for det in meta.get("detections") or []:
                latin = (det.get("species_latin") or "").strip()
                if not latin or latin in seen:
                    continue
                seen.add(latin)
                svc.on_new_species(latin, det.get("species") or None, event_id, self.camera_id)
        except Exception as e:
            log.debug("[%s] dossier hook skipped: %s", self.camera_id, e)

    def _publish_alert(self, meta: dict, thumb_rel: str | None) -> None:
        """Hand the event to the push system.

        The camera-level switches are applied here (armed, per-zone
        send_telegram, telegram_enabled, notify from the severity
        matrix); everything finer — label config, threshold, suppress,
        rate limit, quiet hours — is the push system's decision.
        """
        notify = bool(meta.get("notify", False))
        if not self.cfg.get("armed", True):
            notify = False
        if not meta.get("send_telegram", True):
            notify = False
        # One ROUTING line per finalized event, BEFORE any further
        # gating, so the reason an alert is dropped is visible without
        # switching to DEBUG. This line's absence is what made the
        # missing-alert bug invisible for four months.
        log.info(
            "[trigger][cam:%s] alert routing: labels=%s notify=%s armed=%s "
            "telegram_enabled=%s send_telegram_meta=%s alarm_level=%s",
            self.camera_id,
            ",".join(sorted(set(meta.get("labels", [])))),
            notify,
            self.cfg.get("armed", True),
            self.cfg.get("telegram_enabled", True),
            meta.get("send_telegram", True),
            meta.get("alarm_level"),
        )
        if not (notify and self.cfg.get("telegram_enabled", True) and self.notifier):
            return
        try:
            storage_root = Path(self.global_cfg["storage"]["root"])
            snap_path = (storage_root / thumb_rel) if thumb_rel else None
            self.notifier.send_event_alert(
                meta=meta,
                camera_id=self.camera_id,
                snapshot_path=snap_path,
            )
            log.info(
                "[trigger][cam:%s] alert handed off to notifier (event_id=%s)",
                self.camera_id,
                meta.get("event_id"),
            )
        except Exception as e:
            log.warning("[%s] telegram event push failed: %s", self.camera_id, e)

    def _publish_finalized_event(
        self,
        event: dict,
        meta: dict,
        thumb_rel: str | None,
        *,
        apply_first_since: bool = True,
    ) -> None:
        """Every consequence of a finalized motion event, in order.

        `apply_first_since` is False for the OpenCV path, which must
        stamp the marker BEFORE its `add_event` so the first write of
        the JSON already carries it. The ffmpeg path updates an existing
        stub, so it stamps here.
        """
        if apply_first_since:
            self._apply_first_since(event, meta)
            with contextlib.suppress(Exception):
                self.store.update_event(self.camera_id, event.get("event_id"), event)
        self._publish_mqtt(event)
        self._publish_achievement(meta)
        self._publish_quests()
        self._publish_dossiers(meta, event.get("event_id") or meta.get("event_id") or "")
        self._publish_alert(meta, thumb_rel)
        # Last, so the "you can walk in again" cue only goes out once the
        # clip is genuinely finished and filed.
        self.notify_recording_finished(meta, event.get("duration_s"))
