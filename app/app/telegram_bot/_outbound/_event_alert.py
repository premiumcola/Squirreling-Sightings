"""The event push path: nine gates, then one message.

Split out of `_outbound/__init__.py` where it had grown to 247 lines in a
single method — the reason nothing new could be added to it.

The cut is deliberate and not cosmetic. Every gate now reports *why* it
blocked through one choke point (`_event_blocked` → `EventAlertResult
.blocked_by`) instead of nine bare `return`s, so the answer to "why did
no message arrive?" is available to the caller and to the per-camera
decision trace, rather than only to whoever greps the log.

Order matters and is unchanged: the ledger record is written above the
threshold gate on purpose — see the comment at the call site.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ...detection_feedback import record_alert
from ...telegram_helpers import LABEL_DE, most_specific_label
from .._consts import _NOTIFY_COOLDOWN_DEFAULTS, log


@dataclass(frozen=True)
class EventAlertResult:
    """What send_event_alert did, for callers that care.

    `blocked_by` names the first gate that said no — one of
    disabled / push_disabled / global_mute / cam_mute / push_flag /
    threshold / suppressed / rate_limit / cooldown / schedule — and is
    None on a delivered alert."""

    sent: bool = False
    blocked_by: str | None = None
    label: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class _EventCtx:
    """Everything the gate chain and the message composer need, resolved
    once so neither has to reach back into config a second time."""

    meta: dict
    camera_id: str
    cam_cfg: dict = field(default_factory=dict)
    label_cfg: dict = field(default_factory=dict)
    primary: str = "motion"
    top_score: float = 0.0
    threshold: float = 0.0


def _top_score(detections: list, primary: str) -> float:
    """Top score for the primary label specifically — falls back to the
    event's overall top detection if the primary isn't a CV label."""
    top = max(
        (float(d.get("score", 0.0)) for d in detections if d.get("label") == primary),
        default=0.0,
    )
    if top == 0.0 and detections:
        top = max((float(d.get("score", 0.0)) for d in detections), default=0.0)
    return top


def _event_caption(meta: dict, primary: str, cam_name: str, score_pct: int) -> str:
    """F06 first-since: when this event is the first of its class after a
    long gap, lead with a celebratory headline. The marker may name a
    different label than `primary` (e.g. the event has "person" +
    "squirrel" but only squirrel crossed its 12 h threshold) — the
    marker's label wins so the user sees the actually-anomalous class.
    is_new_record adds a sparkle so the rarity is noticeable."""
    first_since = meta.get("first_since") if isinstance(meta.get("first_since"), dict) else None
    if not first_since:
        return f"<b>{LABEL_DE.get(primary, primary)}</b> · {score_pct}% · {cam_name}"
    fs_label = first_since.get("label") or primary
    fs_label_de = LABEL_DE.get(fs_label, fs_label)
    gap_h = float(first_since.get("gap_hours") or 0.0)
    gap_str = f"{int(round(gap_h))} h" if gap_h >= 1 else f"{int(round(gap_h * 60))} min"
    record_tag = " ✨ (neuer Rekord)" if first_since.get("is_new_record") else ""
    return f"<b>Erstes {fs_label_de} seit {gap_str}{record_tag}</b>\n{cam_name} · {score_pct}%"


def _event_buttons(eid: str, camera_id: str, siren: bool, deep_link: str) -> list:
    """Verdict row, mute row (+ siren on an armed night wakeup), live
    actions, and the deep link when public_base_url is configured.

    The live row re-uses the same cam:<id>:livebild / cam:<id>:clip:5
    callbacks the /menu picker already routes — single source of truth,
    no parallel dispatcher. URL buttons are recognised by their http(s)
    prefix in _build_markup, so they need no callback_data."""
    buttons = [
        [("✅ Gültig", f"ev:{eid}:ok"), ("❌ Falsch", f"ev:{eid}:no")],
        [("🔇 1 h still", f"ev:{eid}:m1h")],
    ]
    if siren:
        buttons[1].append(("🚨 Sirene", f"ev:{eid}:siren"))
    buttons.append(
        [
            ("📷 Livebild", f"cam:{camera_id}:livebild"[:64]),
            ("🎬 5 s Clip", f"cam:{camera_id}:clip:5"[:64]),
        ]
    )
    if deep_link:
        buttons.append([("🌐 In App öffnen", deep_link)])
    return buttons


class EventAlertMixin:
    """Event push for TelegramService. Mixin — reads shared state via
    `self.*` and the predicates from GatesMixin."""

    def send_event_alert(
        self, meta: dict, camera_id: str, snapshot_path: str | Path | None = None
    ) -> EventAlertResult:
        """Push entry point used by the camera runtime after an event is finalized.

        Decides — based on push.labels[primary], suppress, rate-limit and
        quiet/night state — whether and how to alert. Caller is expected
        to have already written the event to disk.

        Returns an EventAlertResult naming the gate that blocked; today's
        production callers ignore it."""
        if not self.enabled:
            return EventAlertResult(blocked_by="disabled")
        pcfg = self.push_cfg or {}
        if not pcfg.get("enabled", True):
            log.debug("[tg] push: disabled")
            return EventAlertResult(blocked_by="push_disabled")
        # Observability marker — lands BEFORE every gate so a missing
        # push can be diagnosed by checking whether this line fires:
        #   • absent → live pipeline never produced an event for this
        #     cam (capture/motion/confirm upstream); not a notify gate
        #   • present + a "[tg] skip:" line for the same cam → that
        #     gate is the cause
        #   • present + no skip and no "[tg] event alert:" → bot init
        #     or transport issue; check Polling/HTTP errors above
        _labels_preview = meta.get("labels") or []
        log.info(
            "[tg] notify-attempt cam=%s label=%s sev=%s",
            camera_id,
            most_specific_label(_labels_preview) if _labels_preview else "—",
            (meta.get("severity") or "—"),
        )
        ctx = self._event_ctx(pcfg, meta, camera_id)
        blocked = self._event_blocked(ctx)
        if blocked:
            return EventAlertResult(blocked_by=blocked, label=ctx.primary, score=ctx.top_score)
        self._push_event(ctx, snapshot_path)
        return EventAlertResult(sent=True, label=ctx.primary, score=ctx.top_score)

    def _event_ctx(self, pcfg: dict, meta: dict, camera_id: str) -> _EventCtx:
        """Resolve label, score and the two config blocks the rest of the
        path reads."""
        labels = meta.get("labels") or []
        primary = most_specific_label(labels)
        label_cfg = (pcfg.get("labels") or {}).get(primary, {})
        return _EventCtx(
            meta=meta,
            camera_id=camera_id,
            cam_cfg=self._camera_cfg(camera_id) or {},
            label_cfg=label_cfg,
            primary=primary,
            top_score=_top_score(meta.get("detections") or [], primary),
            threshold=float(label_cfg.get("threshold", 0.0) or 0.0),
        )

    def _event_blocked(self, ctx: _EventCtx) -> str | None:
        """The ordered gate chain. Returns the name of the first gate that
        said no, or None when the alert may go out."""
        camera_id, primary = ctx.camera_id, ctx.primary
        top_score, threshold = ctx.top_score, ctx.threshold
        detections = ctx.meta.get("detections") or []
        muted = self._mute_reason(camera_id)
        if muted:
            return muted
        if not ctx.label_cfg.get("push", False):
            log.warning("[tg] skip: %s push disabled (cam=%s)", primary, camera_id)
            return "push_flag"
        # C4 · record the CANDIDATE here, above every gate. Recording
        # after them would only ever capture events that cleared the bar
        # — for `person` nothing under 0.85 — and a calibration built on
        # that could raise a threshold but never lower one, which is the
        # direction this system actually needs. The score of a rejected
        # candidate is only observable at this point.
        with contextlib.suppress(Exception):
            record_alert(
                self._storage_root(),
                cam_id=camera_id,
                event_id=ctx.meta.get("event_id") or "",
                label=primary,
                score=top_score,
                threshold=threshold,
                ts=time.time(),
                detections=detections,
                passed_threshold=top_score >= threshold,
            )
        if top_score < threshold:
            log.warning(
                "[tg] skip: %s score=%.2f < threshold=%.2f (cam=%s)",
                primary,
                top_score,
                threshold,
                camera_id,
            )
            return "threshold"
        if self._is_suppressed(camera_id, primary):
            log.warning("[tg] skip: suppressed %s/%s", camera_id, primary)
            return "suppressed"
        if self._is_rate_limited(camera_id):
            log.warning("[tg] skip: rate-limited %s", camera_id)
            return "rate_limit"
        if self._cooldown_blocked(ctx):
            return "cooldown"
        if self._schedule_blocked(ctx):
            return "schedule"
        return None

    def _mute_reason(self, camera_id: str) -> str | None:
        """Global + per-camera mute. Both honour the same "_until" epoch
        contract: 0 / past = no mute, future = active. Daily reports,
        highlights and the watchdog go through their own jobs and stay
        silent-by-design — they bypass this gate entirely."""
        if not self.settings_store:
            return None
        try:
            global_mute = float(self.settings_store.runtime_get("global_mute_until") or 0)
        except Exception:
            global_mute = 0
        if global_mute and time.time() < global_mute:
            log.info("[tg] skip: global mute active until epoch=%d", int(global_mute))
            return "global_mute"
        try:
            cam_mute = float(
                self.settings_store.runtime_get_subkey("cam_mute_until", camera_id, 0) or 0
            )
        except Exception:
            cam_mute = 0
        if cam_mute and time.time() < cam_mute:
            log.info("[tg] skip: cam %s muted until epoch=%d", camera_id, int(cam_mute))
            return "cam_mute"
        return None

    def _cooldown_blocked(self, ctx: _EventCtx) -> bool:
        """Per-class cooldown — minimum elapsed seconds between two
        successive pushes for the SAME class on the SAME camera. The
        primary label is the gate; multi-class events update the
        primary's cooldown and only the primary's is consulted next
        time. Recording / archiving are unaffected — this is purely a
        notification gate."""
        cd_cfg = ctx.cam_cfg.get("notification_cooldown") or {}
        cd_default = _NOTIFY_COOLDOWN_DEFAULTS.get(ctx.primary, 0)
        cd_seconds = int(cd_cfg.get(ctx.primary, cd_default))
        if cd_seconds <= 0:
            return False
        now_mono = time.monotonic()
        key = (ctx.camera_id, ctx.primary)
        last = self._last_notify.get(key, 0.0)
        elapsed = now_mono - last
        if last and elapsed < cd_seconds:
            log.info(
                "[tg] skip: cooldown active for %s on %s (%ds remaining)",
                ctx.primary,
                ctx.camera_id,
                int(cd_seconds - elapsed),
            )
            return True
        self._last_notify[key] = now_mono
        return False

    def _schedule_blocked(self, ctx: _EventCtx) -> bool:
        """Per-camera notification schedule. Outside the configured
        schedule_notify window the push is suppressed. Daily reports /
        highlights / watchdog are system-level and not gated by this.
        Falls back to the legacy schedule.actions.telegram check for
        cameras that haven't been migrated yet (settings_store's boot-time
        _migrate_alerting_schedules catches them on the next start)."""
        from ...event_logic import is_schedule_window_active, schedule_action_active as _sched_act

        sch_notify = ctx.cam_cfg.get("schedule_notify")
        if isinstance(sch_notify, dict) and sch_notify:
            if not is_schedule_window_active(sch_notify):
                log.warning("[tg] skip: schedule_notify blocks telegram (cam=%s)", ctx.camera_id)
                return True
            return False
        if not _sched_act(ctx.cam_cfg.get("schedule") or {}, "telegram"):
            log.warning("[tg] skip: legacy schedule blocks telegram (cam=%s)", ctx.camera_id)
            return True
        return False

    def _resolve_silence(
        self, ctx: _EventCtx, severity: str, is_armed: bool
    ) -> tuple[bool, bool, bool]:
        """(silent, is_night_now, night_wakeup).

        Quiet hours → silent push, unless the alert qualifies as a
        "wakeup at night" — those must always ring through. The per-class
        severity matrix is the newer source of truth on top of that:
        severity="info" is always silent (the user explicitly asked for a
        quiet ping), severity="alarm" keeps the quiet-hours behaviour (a
        loud alarm in quiet hours still mutes unless night_wakeup
        escalates it)."""
        pcfg = self.push_cfg or {}
        is_night_now = self._is_night_for_camera(ctx.camera_id)
        is_quiet = self._is_quiet_now()
        night_cfg = pcfg.get("night_alert") or {}
        night_wakeup = (
            bool(night_cfg.get("enabled", True))
            and is_night_now
            and (not night_cfg.get("armed_only", True) or is_armed)
        )
        silent = is_quiet and not night_wakeup
        if severity == "info":
            silent = True
        elif severity == "alarm":
            silent = is_quiet and not night_wakeup
        return silent, is_night_now, night_wakeup

    def _event_photo(self, ctx: _EventCtx, snapshot_path: str | Path | None):
        """Prefer the highest-scoring frame from the tracking sidecar
        (Phase 1 worker → tracks.json) with the bbox burnt on. Fallback
        chain when the worker hasn't finished yet, or ffmpeg is missing:
        the trigger snapshot bytes from meta, then snapshot_path on
        disk."""
        photo = self._best_frame_jpeg(ctx.meta, ctx.camera_id)
        if photo is None:
            photo = ctx.meta.get("thumb_bytes")
        if photo is None and snapshot_path:
            photo = str(snapshot_path)
        return photo

    def _push_event(self, ctx: _EventCtx, snapshot_path: str | Path | None) -> None:
        """Compose the message every gate has cleared and hand it to send()."""
        meta, camera_id = ctx.meta, ctx.camera_id
        cam_name = ctx.cam_cfg.get("name") or camera_id
        is_armed = bool(ctx.cam_cfg.get("armed", True))
        severity = (meta.get("severity") or "").lower()
        silent, is_night_now, night_wakeup = self._resolve_silence(ctx, severity, is_armed)
        eid = meta.get("event_id") or datetime.now().strftime("%Y%m%d-%H%M%S")
        caption = _event_caption(meta, ctx.primary, cam_name, int(round(ctx.top_score * 100)))
        buttons = _event_buttons(
            eid, camera_id, night_wakeup and is_armed, self._event_deep_link_url(eid)
        )
        if self.settings_store:
            self.settings_store.runtime_alert_index_set(
                eid,
                {
                    "cam": camera_id,
                    "label": ctx.primary,
                    "ts": time.time(),
                },
            )
        # The ledger record for this event was already written above the
        # push gates — deliberately, so rejected candidates are captured
        # too. Nothing to add here.
        photo = self._event_photo(ctx, snapshot_path)
        self.send(caption, photo=photo, buttons=buttons, silent=silent, dark=is_night_now)
        self._record_rate_limit(camera_id)
        log.info(
            "[tg] event alert: cam=%s label=%s score=%.2f severity=%s silent=%s dark=%s",
            camera_id,
            ctx.primary,
            ctx.top_score,
            severity or "—",
            silent,
            is_night_now,
        )
