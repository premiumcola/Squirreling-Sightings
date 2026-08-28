"""The quiet question — the band between spawn and push, given a voice.

Two message classes, and only one of them is new:

    score >= push          ALARM · the existing event alert, unchanged.
                           It already carries [✅ Gültig] [❌ Falsch].
    spawn <= score < push  FRAGE · this module. Quiet, never buzzes.
    score <  spawn         nothing — the detector never spawned a track.

That middle band is the documented "dead zone" ``thresholds`` was
written to expose: sightings recorded and silently never sent. The net's
mapping keeps it open by construction (``push >= spawn + 0.10``).
Instead of closing it, this gives it a voice — below the alarm
threshold and above the detection floor, it does not alarm the operator,
it asks them. Every answer lands in the corpus, the corpus moves the
net, and the volume is bounded by the same number the operator is
dragging.

Gates, and why so few: the question is invoked beside the recording
ticker and on the ticker's principle. The ticker deliberately bypasses
the severity matrix, thresholds, quiet hours and schedule because those
gates are what a walk-in test is diagnosing. The question bypasses them
for the same reason — a class set to ``severity: off`` or ``push:
false`` is exactly the class with no corpus, and asking about it is the
entire point. It respects ``telegram_enabled``, ``armed``, the two mutes
and its own budget. Nothing else.
"""

from __future__ import annotations

import contextlib
import time
from datetime import datetime

from ... import net_archive
from ...detection_feedback import corpus_stats, resolve_stratum
from ...detection_feedback._io import ledger_index
from ...detection_feedback._write import record_alert
from ...telegram_helpers import LABEL_DE, most_specific_label
from ...thresholds import resolve_effective
from ...thresholds._apply import AXIS_ORDER, adapted_layer, rails
from .._consts import log

#: Questions per day, GLOBAL across every camera. Seven events a day are
#: expected, so this is 1.7x headroom — enough that a busy afternoon is
#: not silently dropped, low enough that a phone is never buried.
DAILY_BUDGET = 12

#: Minimum seconds between two questions for the same (camera, class).
#: One squirrel visit is one question, not six. Monotonic clock, the
#: `_TICKER_MIN_GAP_S` pattern from `_recording/_publish.py`.
PER_CLASS_GAP_S = 600.0

#: Night queue depth. Bounded and drop-oldest: a queue that grows without
#: limit turns one bad night into a morning of scrolling.
NIGHT_QUEUE_MAX = 20

_BUDGET_KEY = "netz_question_budget"
_QUEUE_KEY = "netz_question_queue"


def question_markup(eid: str, deep_link: str = "") -> list:
    """The four buttons. `ev:<eid>:alt` is 22 + 8 = 30 bytes, well inside
    the 64-byte callback_data limit `_send._build_markup` truncates at."""
    rows = [
        [("✅ Ja", f"ev:{eid}:ok")],
        [("❌ Nein", f"ev:{eid}:no")],
        [("🐿 War etwas anderes", f"ev:{eid}:alt")],
    ]
    if deep_link:
        rows.append([("🌐 In App öffnen", deep_link)])
    return rows


def question_class_markup(eid: str, classes) -> list:
    """One row per class enabled on that camera, plus a way back.

    ``ev:20260828-141233-874512:c:squirrel`` is 36 bytes — the longest
    callback this module can emit, and comfortably inside the limit.
    """
    rows = [[(f"{LABEL_DE.get(c, c)}", f"ev:{eid}:c:{c}")] for c in classes]
    rows.append([("← zurück", f"ev:{eid}:back")])
    return rows


def event_subject(meta: dict) -> tuple:
    """``(label, score)`` — the ONE class this event is about.

    ``most_specific_label`` and not ``labels[0]``, and the whole feature
    turned on that difference. ``_motion._build_event_meta`` writes
    ``labels: sorted(set(labels))``, so an event that saw a person while
    motion was still confirming is filed as ``["motion", "person"]`` and
    ``labels[0]`` is ``"motion"`` — alphabetically ahead of ``person``
    and ``squirrel``, the two classes these three cameras exist for.

    ``motion`` then resolves to ``push = 0.0`` (its shipped entry) while
    no detection carries the label ``motion``, so the score is 0.0 and
    ``0.0 >= 0.0`` classified EVERY real event as an alarm: no question
    was ever sent, and the archive filled with fabricated 0-percent
    alarms. This is the same helper ``_event_alert._event_ctx`` picks the
    push gate's label with, which is what "the two can never disagree"
    requires.

    Returns ``("motion", 0.0)`` for an event with no object detection at
    all — the caller drops it, because there is nothing to ask about.
    """
    label = most_specific_label(meta.get("labels") or [])
    score = max(
        (
            float(d.get("score") or 0.0)
            for d in (meta.get("detections") or [])
            if d.get("label") == label
        ),
        default=0.0,
    )
    return label, score


def _caption(cam_name: str, label: str, score: float) -> str:
    return (
        f"❓ <b>Unsicher</b> · {cam_name} · {datetime.now().strftime('%H:%M')}\n"
        f"Vermutung: {LABEL_DE.get(label, label)} · {int(round(float(score) * 100))} %\n"
        f"War das richtig?"
    )


class QuestionMixin:
    """The question path for TelegramService. Mixin — state via ``self.*``."""

    # ── budget + spacing ──────────────────────────────────────────────
    def _question_budget_left(self) -> int:
        """Questions remaining today. Resets at local midnight.

        Counted in ``runtime`` and keyed by the date, so the reset needs
        no scheduled job and survives a restart — a counter that only a
        cron resets is a counter that a 23:59 restart doubles.
        """
        ss = self.settings_store
        if not ss:
            return 0
        today = datetime.now().strftime("%Y-%m-%d")
        state = ss.runtime_get(_BUDGET_KEY) or {}
        if not isinstance(state, dict) or state.get("day") != today:
            return DAILY_BUDGET
        return max(0, DAILY_BUDGET - int(state.get("n") or 0))

    def _question_budget_spend(self) -> None:
        ss = self.settings_store
        if not ss:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        state = ss.runtime_get(_BUDGET_KEY) or {}
        if not isinstance(state, dict) or state.get("day") != today:
            state = {"day": today, "n": 0}
        state["n"] = int(state.get("n") or 0) + 1
        ss.runtime_set(_BUDGET_KEY, state)

    def _question_gap_ok(self, cam_id: str, label: str) -> bool:
        gaps = getattr(self, "_question_last", None)
        if gaps is None:
            gaps = {}
            self._question_last = gaps
        now = time.monotonic()
        last = gaps.get((cam_id, label), 0.0)
        return not (last and now - last < PER_CLASS_GAP_S)

    def _question_gap_mark(self, cam_id: str, label: str) -> None:
        gaps = getattr(self, "_question_last", None)
        if gaps is None:
            gaps = {}
            self._question_last = gaps
        gaps[(cam_id, label)] = time.monotonic()

    # ── the archive record ────────────────────────────────────────────
    def _question_net_state(self, cam_cfg: dict, cam_id: str) -> dict:
        """Every axis of this camera, as it stands right now."""
        labels = [
            lab for lab in AXIS_ORDER if lab in set(cam_cfg.get("object_filter") or AXIS_ORDER)
        ]
        try:
            stats = corpus_stats(self._storage_root())
        except Exception:
            stats = {"strata": [], "pooled": []}
        return net_archive.build_net_state(
            cam_cfg,
            self.push_cfg or {},
            labels,
            lambda lab: resolve_stratum(stats, cam_id, lab),
        )

    def _corpus_row(self, meta: dict, camera_id: str, *, kind: str) -> None:
        """The ledger row a later verdict on this event joins to.

        Without it the answer is written and then structurally dropped.
        ``detection_feedback.judged_alerts`` — the only thing the learner,
        the axis proposal and the drag preview read — iterates the ALERT
        records and looks each one's verdict up. A verdict whose event has
        no alert record is invisible to every stratum: it is kept on disk
        (``_retention`` protects it) and counted by nothing.

        ``_event_alert`` writes that record inside the push chain, which
        runs only when ``meta["notify"]`` is true. That excludes exactly
        the classes the net exists to learn: ``cat``, ``bird``, ``fox``,
        ``hedgehog`` and everything on ``severity: off`` never notify, so
        every question asked about them collected its answer into a void.
        A question about ``person`` in the quiet band is in the same
        position — it is BELOW the push bar by definition, and the whole
        point of asking is to learn where the bar belongs.

        Still ONE row per event: the push path runs first and, when it
        wrote one, this is a no-op. The check is against the same cached
        index every reader uses, so it costs no extra parse.
        """
        eid = meta.get("event_id") or ""
        root = self._storage_root()
        if eid and eid in ledger_index(root).alerts:
            return
        cam_cfg = self._camera_cfg(camera_id) or {}
        label, score = event_subject(meta)
        eff = resolve_effective(
            cam_cfg, self.push_cfg or {}, label, adapted=adapted_layer(cam_cfg, label)
        )
        record_alert(
            root,
            cam_id=camera_id,
            event_id=eid,
            label=label,
            score=score,
            threshold=eff.push,
            ts=time.time(),
            detections=meta.get("detections") or [],
            passed_threshold=(kind == net_archive.KIND_ALARM),
        )

    def archive_event(self, meta: dict, camera_id: str, *, kind: str, asked: bool) -> None:
        """Capture the ask-time state for one event. Never raises.

        Called for a question AND for every alarm, so the archive covers
        both bands. `asked=False` is written when the budget was spent —
        the event is on record, it simply was not put to the operator,
        and the "Noch nicht beurteilt" filter in the archive is where it
        surfaces instead.
        """
        try:
            cam_cfg = self._camera_cfg(camera_id) or {}
            det = meta.get("detections") or []
            label, _score = event_subject(meta)
            primary = next(
                (d for d in det if d.get("label") == label),
                det[0] if det else {"label": label, "score": 0.0},
            )
            net_archive.capture(
                self._storage_root(),
                event_id=meta.get("event_id") or "",
                cam_id=camera_id,
                cam_name=cam_cfg.get("name") or camera_id,
                kind=kind,
                detection={
                    "label": primary.get("label") or label,
                    "score": float(primary.get("score") or 0.0),
                    "bbox": primary.get("bbox"),
                    "all": [
                        {"label": d.get("label"), "score": float(d.get("score") or 0.0)}
                        for d in det
                    ],
                },
                net_state=self._question_net_state(cam_cfg, camera_id),
                rails=rails(),
                asked=asked,
                frame_bytes=self._best_frame_jpeg(meta, camera_id) or meta.get("thumb_bytes"),
            )
        except Exception as e:
            log.debug("[tg] Archiv-Datensatz zu %s übersprungen: %s", meta.get("event_id"), e)

    # ── the night queue ───────────────────────────────────────────────
    def _question_hold(self, meta: dict, camera_id: str) -> None:
        """Park a question until 07:00. Bounded FIFO, drop-oldest.

        Alarms are NEVER held: a security alert at 03:00 arrives at
        03:00, exactly as today. Only questions wait, and they are
        released as ONE message with one button — a Telegram message
        with thirty thumbnails is unanswerable on a phone.
        """
        ss = self.settings_store
        if not ss:
            return
        queue = ss.runtime_get(_QUEUE_KEY) or []
        if not isinstance(queue, list):
            queue = []
        queue.append(
            {
                "event_id": meta.get("event_id"),
                "cam": camera_id,
                "ts": time.time(),
            }
        )
        ss.runtime_set(_QUEUE_KEY, queue[-NIGHT_QUEUE_MAX:])

    def _job_question_release(self) -> None:
        """07:00 · one line naming how many wait. Registered as a daily job."""
        ss = self.settings_store
        if not (self.enabled and ss):
            return
        queue = ss.runtime_get(_QUEUE_KEY) or []
        if not isinstance(queue, list) or not queue:
            return
        # Drain LAST. Draining first and then raising on the way to the
        # send loses the night with no way to get it back.
        text = f"🌙 {len(queue)} Erkennungen aus der Nacht warten auf deine Einschätzung."
        link = self._netz_deep_link()
        buttons = [[("Ansehen", link)]] if link else None
        self.send(text, buttons=buttons, silent=True)
        ss.runtime_set(_QUEUE_KEY, [])
        log.info("[tg] Nacht-Warteschlange freigegeben: %d Fragen", len(queue))

    def _job_netz_learner(self) -> None:
        """03:30 · the nightly run. Registered in ``register_default_jobs``.

        Rebuilds the runtimes ONCE at the end rather than per class — a
        rebuild per axis would restart every camera a dozen times in a
        row for what is at most a handful of threshold changes.
        """
        if not self.settings_store:
            return
        try:
            from ...thresholds._learner import run_pass

            summary = run_pass(self._storage_root(), self.settings_store, self.push_cfg or {})
        except Exception as e:
            log.warning("[det] Netz-Nachtlauf fehlgeschlagen: %s", e)
            return
        if not summary.get("changed"):
            return
        try:
            from ... import app_state

            rebuild = getattr(app_state, "rebuild_runtimes", None)
            if callable(rebuild):
                rebuild()
        except Exception as e:
            log.warning("[det] rebuild_runtimes nach Netz-Lauf fehlgeschlagen: %s", e)

    def _netz_deep_link(self) -> str:
        """Through ``_dashboard_url`` like every other deep link here.

        ``self.global_cfg`` is a CALLABLE in production
        (``server._reload_telegram_service`` passes
        ``lambda: settings.export_effective_config(...)``), so reaching
        for ``.get`` on it raised ``AttributeError`` — after the queue
        had already been drained two lines above. Every night held that
        way was announced to nobody and could not be re-announced.
        """
        base = (self._dashboard_url() or "").rstrip("/")
        return f"{base}/#netz?tab=verlauf&filter=offen" if base else ""

    # ── entry point ───────────────────────────────────────────────────
    def band_for(self, meta: dict, camera_id: str) -> str | None:
        """Which of the net's two bands this event falls in.

        The one place the three-way split is decided, resolved through
        the same ladder the push gate uses so the two can never disagree
        about where the line is::

            score >= push          KIND_ALARM
            spawn <= score < push  KIND_FRAGE
            score <  spawn         None

        A motion-only event is None, never an alarm. ``motion`` ships
        with ``threshold: 0.0`` and carries no detection of its own, so
        the comparison would be ``0.0 >= 0.0`` — an alarm record with a
        0-percent score, about nothing, on every clip the cameras record.
        The net has no motion axis to learn from it either.
        """
        cam_cfg = self._camera_cfg(camera_id) or {}
        label, score = event_subject(meta)
        if label == "motion":
            return None
        eff = resolve_effective(
            cam_cfg, self.push_cfg or {}, label, adapted=adapted_layer(cam_cfg, label)
        )
        if score >= eff.push:
            return net_archive.KIND_ALARM
        if score >= eff.spawn:
            return net_archive.KIND_FRAGE
        return None

    def on_finalized_event(self, meta: dict, camera_id: str) -> str | None:
        """Archive every event that reached a band; ask about the quiet one.

        Called from ``_publish_finalized_event`` right after the alert.
        An alarm has already been sent with its own ✅/❌ — it is
        archived here so the record exists for BOTH bands, which is what
        makes the archive a complete account of the net rather than a
        log of questions.
        """
        band = self.band_for(meta, camera_id)
        if band is None:
            return None
        try:
            if band == net_archive.KIND_ALARM:
                self.archive_event(meta, camera_id, kind=net_archive.KIND_ALARM, asked=True)
                return "alarm"
            return self.send_question(meta, camera_id) or "frage"
        finally:
            # Here and not inside `send_question`: a question the mute or
            # the 10-minute gap swallowed is still a candidate the corpus
            # has to count, or the answer rate is computed against a
            # denominator that quietly excludes them. LAST, because
            # `archive_event` reads the corpus to snapshot the net and
            # writing first would force a re-parse of the whole ledger on
            # the thread that has just finished a clip.
            with contextlib.suppress(Exception):
                self._corpus_row(meta, camera_id, kind=band)

    def send_question(self, meta: dict, camera_id: str) -> str | None:
        """Ask about one uncertain detection. Returns the blocking reason.

        ``None`` means a question went out. Every other return value
        names the gate, so the caller and the decision trace can say why
        one did not.
        """
        if not self.enabled:
            return "disabled"
        cam_cfg = self._camera_cfg(camera_id) or {}
        if not cam_cfg.get("telegram_enabled", True) or not cam_cfg.get("armed", True):
            return "camera_off"
        if self._mute_reason(camera_id):
            return "muted"
        label, _score = event_subject(meta)
        if not self._question_gap_ok(camera_id, label):
            return "gap"
        if self._question_budget_left() <= 0:
            # Recorded anyway, asked=False — the surplus surfaces in the
            # archive under "Noch nicht beurteilt", where the operator
            # judges at their own pace and the web verdict writes the
            # same ledger row.
            self.archive_event(meta, camera_id, kind=net_archive.KIND_FRAGE, asked=False)
            log.info("[tg] Frage über Budget: cam=%s label=%s", camera_id, label)
            return "budget"
        if self._is_quiet_now():
            self.archive_event(meta, camera_id, kind=net_archive.KIND_FRAGE, asked=False)
            self._question_hold(meta, camera_id)
            return "quiet_hold"
        self._question_gap_mark(camera_id, label)
        self._question_budget_spend()
        self.archive_event(meta, camera_id, kind=net_archive.KIND_FRAGE, asked=True)
        self._push_question(meta, camera_id, cam_cfg, label)
        return None

    def _push_question(self, meta: dict, camera_id: str, cam_cfg: dict, label: str) -> None:
        eid = meta.get("event_id") or datetime.now().strftime("%Y%m%d-%H%M%S")
        # The subject's score, not the frame's maximum: a caption reading
        # "Vermutung: Person · 91 %" under a 0.62 person because a 0.91
        # cat shared the frame is a question the operator cannot answer.
        _label, score = event_subject(meta)
        photo = self._best_frame_jpeg(meta, camera_id) or meta.get("thumb_bytes")
        if self.settings_store:
            self.settings_store.runtime_alert_index_set(
                eid, {"cam": camera_id, "label": label, "ts": time.time()}
            )
        self.send(
            _caption(cam_cfg.get("name") or camera_id, label, score),
            photo=photo,
            buttons=question_markup(eid, self._event_deep_link_url(eid)),
            # ALWAYS silent, day or night. A question must never buzz —
            # only an alarm earns that.
            silent=True,
        )
        log.info("[tg] Frage gesendet: cam=%s label=%s score=%.2f", camera_id, label, score)
