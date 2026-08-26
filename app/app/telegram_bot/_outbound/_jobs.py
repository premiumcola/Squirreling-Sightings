"""System-level pushes: the three scheduled jobs and two one-shot notices.

Split out of `_outbound/__init__.py` (far past the 500-line file budget).
What holds this module together is the tier, not the trigger: none of
these five is an event alert, none goes through the push gates in
`_event_alert.py`, and every one of them is silent by design. The three
`_job_*` bodies are the APScheduler entry points registered in
`_lifecycle.start`; the two `send_*` notices are fired by the quest
evaluator and by camera_runtime after a timelapse encode.

Every job body swallows its own exceptions — a scheduler thread that
raises loses the job for the rest of the process lifetime.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from ...telegram_helpers import DULL_BIRDS, LABEL_DE, LABEL_WEIGHT, OBJECT_LABELS
from .._consts import log

# A highlight candidate has to be a confident detection — below this the
# "Highlight des Tages" is just the least bad frame of a quiet day.
_HIGHLIGHT_MIN_SCORE = 0.70
# After-hours events are worth half as much: night captures are grainy
# and over-represented because motion runs the same either way.
_AFTER_HOURS_WEIGHT = 0.5
# A camera counts as offline for this long before the push goes out, so a
# reconnect blip stays invisible.
_OFFLINE_ALERT_AFTER_S = 300
_STORAGE_WARN_GB = 2.0
_STORAGE_WARN_EVERY_S = 86400


class JobsMixin:
    """Scheduled jobs and system notices for TelegramService. Mixin —
    reads shared state via `self.*`."""

    def send_quest_completed(self, quest: dict):
        """Push a one-shot Glückwunsch when an F09 quest hits its target.

        Caller (quest evaluator) is responsible for the notified_at
        gate — this method only formats and sends. Silent push so it
        joins the daily-summary tier of "informational" pings rather
        than waking the user at 3 AM the moment a wildlife threshold
        flips.
        """
        if not self.enabled:
            return
        icon = quest.get("icon") or "🎉"
        title = quest.get("title") or quest.get("id") or "Quest"
        desc = quest.get("description") or ""
        text = f"<b>🎉 Quest abgeschlossen: {icon} {title}</b>\n{desc}"
        try:
            self.send(text, silent=True)
            log.info("[tg] quest completion sent: %s", quest.get("id"))
        except Exception as e:
            log.warning("[tg] quest push failed for %s: %s", quest.get("id"), e)

    def send_timelapse_alert(
        self, video_path: str | Path, cam_name: str, profile_de: str, duration_s: int, rel_path: str
    ):
        """Fired by camera_runtime after a successful timelapse encode."""
        if not self.enabled:
            return
        if not (self.push_cfg.get("timelapse") or {}).get("enabled", True):
            return
        caption = f"<b>Zeitraffer fertig</b>\n" f"{cam_name} · {profile_de} · {duration_s}s"
        buttons = [[("💾 Speichern", f"tl:save:{rel_path}"[:64])]]
        self.send(caption, video=str(video_path), buttons=buttons, silent=True)

    # ── Scheduled jobs ────────────────────────────────────────────────────
    def _job_daily_report(self):
        try:
            pcfg = self.push_cfg or {}
            if not pcfg.get("enabled", True) or not (pcfg.get("daily_report") or {}).get(
                "enabled", True
            ):
                return
            date_de = datetime.now().strftime("%d.%m.%Y")
            per_cam = self._daily_counts()
            lines = [f"<b>Tagesreport · {date_de}</b>", ""]
            if per_cam:
                for name, counts in per_cam:
                    chips = " · ".join(
                        f"<code>{n}</code> {LABEL_DE.get(l, l)}"
                        for l, n in sorted(counts.items(), key=lambda x: -x[1])
                        if n > 0
                    )
                    lines.append(f"{name}: {chips}")
            else:
                lines.append("Keine Erkennungen heute.")
            try:
                delta_gb = self._storage_today_delta_gb()
                if delta_gb is not None:
                    lines.append("")
                    lines.append(f"Speicher heute: + {delta_gb:.1f} GB")
            except Exception:
                pass
            buttons = [
                [("📊 Detail-Statistik", "menu:stats:today")],
                [("🎞 Tageszeitraffer", "menu:zeitraffer:today")],
            ]
            self.send("\n".join(lines), buttons=buttons, silent=True)
            log.info("[tg] daily report sent")
        except Exception as e:
            log.error("[tg] daily report job failed: %s", e)

    def _daily_counts(self) -> list[tuple[str, dict]]:
        """Per-camera label counts for today, busiest camera first."""
        cameras = self._cfg().get("cameras", []) or []
        today_iso = datetime.now().strftime("%Y-%m-%d")
        object_set = set(OBJECT_LABELS)
        per_cam: list[tuple[str, dict]] = []
        for cam in cameras:
            cam_id = cam.get("id")
            if not cam_id or not self.store:
                continue
            counts: dict[str, int] = {}
            for ev in self.store.list_events(cam_id, start=today_iso, limit=5000):
                # Counting rule of the Mediathek, not most_specific_label:
                # an event with no recognised label is not counted at all.
                labels = ev.get("labels") or []
                primary = next((l for l in labels if l in object_set), None)
                if primary is None and "motion" in labels:
                    primary = "motion"
                if primary:
                    counts[primary] = counts.get(primary, 0) + 1
            if counts:
                per_cam.append((cam.get("name") or cam_id, counts))
        per_cam.sort(key=lambda kv: -sum(kv[1].values()))
        return per_cam

    def _job_highlight(self):
        try:
            pcfg = self.push_cfg or {}
            if not pcfg.get("enabled", True) or not (pcfg.get("highlight") or {}).get(
                "enabled", True
            ):
                return
            cands = self._highlight_candidates()
            if not cands:
                log.info("[tg] highlight: no candidates")
                return
            pick = max(cands, key=lambda c: c["score"])
            caption = (
                f"<b>✨ Highlight des Tages</b>\n"
                f"{LABEL_DE.get(pick['label'], pick['label'])} · {pick['cam_name']} · {pick['time_hm']}"
            )
            photo = None
            if pick["snap_rel"]:
                full = self._storage_root() / pick["snap_rel"]
                if full.exists():
                    photo = str(full)
            buttons = [
                [("🖼 Hochauflösend", f"hi:{pick['eid']}"[:64])],
                [("📤 Teilen", f"share:{pick['eid']}"[:64])],
            ]
            if self.settings_store and pick["eid"]:
                self.settings_store.runtime_alert_index_set(
                    pick["eid"],
                    {
                        "cam": pick["cam_id"],
                        "label": pick["label"],
                        "ts": time.time(),
                    },
                )
            self.send(caption, photo=photo, buttons=buttons, silent=True)
            log.info(
                "[tg] highlight sent: %s/%s score=%.2f", pick["cam_id"], pick["eid"], pick["score"]
            )
        except Exception as e:
            log.error("[tg] highlight job failed: %s", e)

    def _highlight_candidates(self) -> list[dict]:
        """Every event of the last 24 h that could carry the highlight,
        each with its weighted score. Dull birds (pigeon & co) and
        low-confidence detections are dropped here."""
        cameras = self._cfg().get("cameras", []) or []
        cutoff_ts = time.time() - 24 * 3600
        object_set = set(OBJECT_LABELS)
        cands: list[dict] = []
        for cam in cameras:
            cam_id = cam.get("id")
            if not cam_id or not self.store:
                continue
            for ev in self.store.list_events(cam_id, limit=400):
                try:
                    ev_dt = datetime.fromisoformat(ev.get("time", ""))
                except Exception:
                    continue
                if ev_dt.timestamp() < cutoff_ts:
                    continue
                primary = next((l for l in (ev.get("labels") or []) if l in object_set), None)
                if not primary:
                    continue
                if primary == "bird":
                    species = (ev.get("bird_species") or "").lower()
                    if any(d in species for d in DULL_BIRDS):
                        continue
                detections = ev.get("detections") or []
                top = max(
                    (float(d.get("score", 0.0)) for d in detections if d.get("label") == primary),
                    default=0.0,
                )
                if top < _HIGHLIGHT_MIN_SCORE:
                    continue
                daylight = _AFTER_HOURS_WEIGHT if ev.get("after_hours") else 1.0
                cands.append(
                    {
                        "score": top * LABEL_WEIGHT.get(primary, 1.0) * daylight,
                        "eid": ev.get("event_id"),
                        "cam_id": cam_id,
                        "cam_name": cam.get("name") or cam_id,
                        "label": primary,
                        "time_hm": ev_dt.strftime("%H:%M"),
                        "snap_rel": ev.get("snapshot_relpath"),
                    }
                )
        return cands

    def _job_watchdog(self):
        try:
            pcfg = self.push_cfg or {}
            if not pcfg.get("enabled", True) or not (pcfg.get("system") or {}).get("enabled", True):
                return
            ss = self.settings_store
            if not ss:
                return
            now = time.time()
            state = ss.runtime_get("system_state") or {}
            for cam_id, rt in (self.runtimes or {}).items():
                self._watch_camera(cam_id, rt, state, now)
            ss.runtime_set("system_state", state)
            self._watch_storage(ss, now)
        except Exception as e:
            log.error("[tg] watchdog failed: %s", e)

    def _watch_camera(self, cam_id: str, rt, state: dict, now: float) -> None:
        """One camera's online/offline transition, pushed at most once per
        outage and once on recovery."""
        try:
            status = rt.status() if hasattr(rt, "status") else {}
        except Exception:
            status = {}
        cam_name = status.get("name") or cam_id
        # Treat 'error' or stale frames as offline; 'active' / 'starting' as online.
        online = status.get("status") in ("active", "starting")
        cam_state = state.setdefault(cam_id, {"online": True, "since": now, "alert_sent": False})
        # Transition: online → offline
        if not online and cam_state.get("online", True):
            cam_state["online"] = False
            cam_state["since"] = now
            cam_state["alert_sent"] = False
            return
        offline_for = now - float(cam_state.get("since", now))
        # Still offline → push once after 5 min
        if not online and not cam_state.get("alert_sent"):
            if offline_for >= _OFFLINE_ALERT_AFTER_S:
                self.send(
                    f"<b>{cam_name} offline</b> seit {int(offline_for/60)} Min · keine RTSP-Antwort",
                    buttons=[
                        [("🔄 Neu verbinden", f"cam:{cam_id}:reconnect"[:64])],
                        [("📋 Logs", "menu:logs")],
                    ],
                )
                cam_state["alert_sent"] = True
            return
        # Recovery: offline → online
        if online and not cam_state.get("online", True):
            if cam_state.get("alert_sent"):
                self.send(
                    f"{cam_name} wieder online (Ausfall {int(offline_for/60)} Min)",
                    silent=True,
                )
            cam_state["online"] = True
            cam_state["since"] = now
            cam_state["alert_sent"] = False

    def _watch_storage(self, ss, now: float) -> None:
        """Free-space check — pushed at most once per 24 h while low."""
        try:
            import shutil as _sh

            root = str(self._storage_root())
            free_gb = _sh.disk_usage(root).free / (1024**3)
            last_warn = float(ss.runtime_get("last_storage_warn_ts") or 0)
            if free_gb < _STORAGE_WARN_GB and (now - last_warn) > _STORAGE_WARN_EVERY_S:
                self.send(f"<b>⚠ Speicher knapp</b>: nur noch {free_gb:.1f} GB frei")
                ss.runtime_set("last_storage_warn_ts", now)
        except Exception as e:
            log.debug("[tg] storage check failed: %s", e)

    def _storage_today_delta_gb(self) -> float | None:
        """Sum bytes of media files modified today (best-effort, never raises)."""
        root = self._storage_root()
        if not root.exists():
            return None
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        total = 0
        for sub in ("motion_detection", "timelapse"):
            base = root / sub
            if not base.exists():
                continue
            for p in base.rglob("*"):
                try:
                    st = p.stat()
                    if st.st_mtime >= today_start and p.is_file():
                        total += st.st_size
                except Exception:
                    continue
        return total / (1024**3)
