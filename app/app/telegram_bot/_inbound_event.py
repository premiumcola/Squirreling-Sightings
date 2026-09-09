"""``ev:<event_id>:*`` — every callback an event bubble can produce.

Carved out of ``_inbound.py``, which stood 328 lines past the file
ceiling before the question's three new branches were added to it.

The chain one tap sets off, and its order, which is the part that
matters:

    _handle_event_cb
      ├─ record_verdict        → storage/_diag/*.jsonl   [durable]
      ├─ net_archive.append_verdict → storage/net_archive/… [durable]
      ├─ "ok" → stamp confirmed/confirmed_at on the event JSON
      ├─ "no"/"c:<label>" → take the disproven label OFF the event's
      │  OWN record too (event_relabel.apply_label_change) — the two
      │  ledgers above feed threshold tuning, not the badge/filters/
      │  achievements, which all read `labels` straight off the event
      └─ _set_badge (markup → one grey noop button)

Verdict FIRST, badge second, and the badge edit's failure swallowed —
so a Telegram edit that fails (deleted message, expired query, flood
wait) never costs a judgement. Nothing here recomputes the net: that is
the 03:30 job's work, once, because recomputing on every tap would make
the net twitch and spend the 24 h / 5-point budget in minutes.
"""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .. import net_archive
from ..detection_feedback import record_verdict
from ..event_relabel import apply_label_change, labels_after_correction
from ..species_video_count import record_confirmed_video
from ..telegram_helpers import LABEL_DE
from ._outbound._event_alert import _event_buttons
from ._outbound._question import (
    question_class_markup,
    question_markup,
    species_correction_markup,
)

log = logging.getLogger(__name__)

#: LRU cap on ``runtime.event_feedback``. It is a dedupe guard — "did I
#: already judge this event?" — and without a cap it grows settings.json
#: by one entry per judged event forever. 500 is far more than the few
#: days of history the guard actually needs.
EVENT_FEEDBACK_CAP = 500

_SOURCE_QUESTION = "telegram_q"


class EventCallbackMixin:
    """``ev:*`` callbacks for TelegramService. Mixin — state via ``self.*``."""

    # ── shared bits ───────────────────────────────────────────────────
    async def _set_badge(self, q, label: str):
        """Replace the entire reply markup with a single grey badge button."""
        try:
            mk = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data="noop")]])
            await q.edit_message_reply_markup(reply_markup=mk)
        except Exception as e:
            log.debug("[tg] badge edit failed: %s", e)

    def _event_context(self, eid: str) -> dict:
        """``{cam, label, score}`` for an event id — LRU first, archive second.

        ``runtime.alert_index`` is an LRU of 200 and drops the entry
        after roughly two hundred pushes. A verdict tapped after that
        still books correctly (``judged_alerts`` joins on ``event_id``),
        but ``:m1h`` and ``:siren`` need the camera and the class, and
        used to answer "Daten zur Erkennung fehlen." The archive record
        holds both durably and outlives the LRU by design.
        """
        ss = self.settings_store
        idx = (ss.runtime_get_subkey("alert_index", eid) if ss else None) or {}
        if idx.get("cam") and idx.get("label"):
            return dict(idx)
        with contextlib.suppress(Exception):
            found = net_archive.find_event_context(self._storage_root(), eid)
            if found:
                return {**found, **{k: v for k, v in idx.items() if v}}
        return dict(idx)

    def _camera_classes(self, cam_id: str | None) -> list:
        """Classes enabled on that camera — the rows of the "war etwas
        anderes" picker. Same list the net draws an axis per."""
        cam = (self._camera_cfg(cam_id) or {}) if cam_id else {}
        classes = [c for c in (cam.get("object_filter") or []) if isinstance(c, str)]
        return classes or ["person", "cat", "bird", "squirrel"]

    def _stamp_confirmed(self, eid: str, cam_id: str | None) -> None:
        """Give a Telegram ✅ the same protection a web ✅ has.

        ``storage_retention.JUDGEMENT_FIELDS`` is written only by the web
        ``/confirm`` route, so a Telegram-confirmed event was swept at 14
        days while an identical web-confirmed one was immortal. The two
        gestures mean the same thing and must leave the same mark.
        """
        if not (cam_id and self.store):
            return
        with contextlib.suppress(Exception):
            event = self.store.get_event(cam_id, eid)
            if not event:
                return
            event["confirmed"] = True
            event["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
            self.store.update_event(cam_id, eid, event)

    def _correct_event_label(
        self, eid: str, cam_id: str | None, wrong_label: str | None, corrected: str | None
    ) -> None:
        """Take the disproven label OFF the event's OWN record.

        A "Nein"/correction used to only ever reach the diagnostic
        ledger and the threshold-tuning archive — both feed the 03:30
        learner, neither is what the Mediathek badge, the label filters
        or the achievement counters read. Those all derive `labels`
        straight off the event on every render, so without this the
        event still showed "Katze" everywhere forever. Routed through
        the same ``event_relabel`` helpers the web lightbox's label
        toggle uses, so a Telegram "Nein" and a web untoggle leave the
        event in the same state.
        """
        if not (cam_id and wrong_label and self.store):
            return
        with contextlib.suppress(Exception):
            event = self.store.get_event(cam_id, eid)
            if not event:
                return
            new_labels = labels_after_correction(event.get("labels") or [], wrong_label, corrected)
            apply_label_change(event, new_labels)
            self.store.update_event(cam_id, eid, event)

    def _bird_species_of(self, eid: str, ctx: dict) -> str | None:
        """The event's `bird_species`, or None when this isn't a bird
        event / the field is empty. Needs a store round-trip because
        `_event_context` (the LRU/archive lookup used everywhere else)
        only carries `{cam, label, score}`."""
        cam = ctx.get("cam")
        if not (cam and self.store and ctx.get("label") == "bird"):
            return None
        with contextlib.suppress(Exception):
            event = self.store.get_event(cam, eid)
            species = (event or {}).get("bird_species") or ""
            return species.strip() or None
        return None

    def _book_verdict(
        self,
        eid: str,
        *,
        correct: bool,
        source: str,
        corrected: str | None = None,
        species: str | None = None,
    ):
        """Both durable writes, in one place so no branch can skip one."""
        ctx = self._event_context(eid)
        with contextlib.suppress(Exception):
            record_verdict(
                self._storage_root(),
                event_id=eid,
                correct=correct,
                ts=time.time(),
                corrected_label=corrected,
                source=source,
                cam_id=ctx.get("cam"),
                species=species,
            )
        value = net_archive.VERDICT_RIGHT if correct else net_archive.VERDICT_WRONG
        if corrected:
            value = net_archive.VERDICT_OTHER
        with contextlib.suppress(Exception):
            net_archive.append_verdict(
                self._storage_root(),
                eid,
                value=value,
                source=source,
                corrected_label=corrected,
            )
        if correct:
            self._stamp_confirmed(eid, ctx.get("cam"))
        else:
            self._correct_event_label(eid, ctx.get("cam"), ctx.get("label"), corrected)
        return ctx

    def _already_judged(self, eid: str):
        ss = self.settings_store
        return ss.runtime_get_subkey("event_feedback", eid) if ss else None

    def _mark_judged(self, eid: str, verdict: str, source: str) -> None:
        ss = self.settings_store
        if not ss:
            return
        ss.runtime_set_subkey_lru(
            "event_feedback",
            eid,
            {"verdict": verdict, "by": source, "ts": time.time()},
            EVENT_FEEDBACK_CAP,
        )

    # ── the router ────────────────────────────────────────────────────
    async def _handle_event_cb(self, q, data: str):
        # Telegram only accepts ONE answerCallbackQuery per query, so each
        # branch answers exactly once at its end.
        parts = data.split(":")
        if len(parts) < 3:
            await q.answer()
            return
        eid, verb = parts[1], parts[2]
        if verb in ("ok", "no"):
            await self._cb_verdict(q, eid, verb)
        elif verb == "alt":
            await self._cb_alt(q, eid)
        elif verb == "back":
            await self._cb_back(q, eid)
        elif verb == "c" and len(parts) >= 4:
            await self._cb_corrected(q, eid, parts[3])
        elif verb == "sp":
            await self._handle_species_cb(q, eid, parts[3] if len(parts) >= 4 else None)
        elif verb == "m1h":
            await self._cb_mute(q, eid)
        elif verb == "siren":
            await self._cb_siren(q, eid)
        else:
            await q.answer("Unbekannte Aktion")

    async def _cb_verdict(self, q, eid: str, verb: str):
        if self._already_judged(eid):
            await q.answer("Bereits bewertet")
            return
        verdict = "ok" if verb == "ok" else "no"
        # `telegram_q` and not `telegram`: an answered QUESTION and a
        # volunteered verdict on an ALARM carry different selection bias,
        # and the pooling in `_stats` needs to be able to tell them
        # apart. The archive prints the difference too.
        source = _SOURCE_QUESTION if self._is_question(eid) else "telegram"
        self._mark_judged(eid, verdict, source)
        ctx = self._event_context(eid)
        # "Ja" on a bird question confirms the caption's species guess
        # too — that IS what the caption showed. A "Nein" disputes the
        # whole detection, not just which bird, so nothing is counted.
        species = self._bird_species_of(eid, ctx) if verdict == "ok" else None
        self._book_verdict(eid, correct=(verdict == "ok"), source=source, species=species)
        if species:
            with contextlib.suppress(Exception):
                record_confirmed_video(self._storage_root(), species)
        ts_str = datetime.now().strftime("%H:%M")
        badge = f"✅ Ja · {ts_str}" if verdict == "ok" else f"❌ Nein · {ts_str}"
        await self._set_badge(q, badge)
        await q.answer(badge)

    def _is_question(self, eid: str) -> bool:
        with contextlib.suppress(Exception):
            rec = net_archive.get_record(self._storage_root(), eid)
            if rec:
                return rec.get("kind") == net_archive.KIND_FRAGE
        return False

    async def _cb_alt(self, q, eid: str):
        """Swap the keyboard for one row per class on that camera.

        Edit in place — `edit_message_reply_markup` — rather than a new
        message: the photo and its caption are the context for the
        choice, and a second bubble would separate them.
        """
        ctx = self._event_context(eid)
        classes = self._camera_classes(ctx.get("cam"))
        try:
            await q.edit_message_reply_markup(
                reply_markup=self._build_markup(question_class_markup(eid, classes))
            )
        except Exception as e:
            log.debug("[tg] alt markup edit failed: %s", e)
        await q.answer("Was war es wirklich?")

    async def _cb_back(self, q, eid: str):
        with contextlib.suppress(Exception):
            await q.edit_message_reply_markup(
                reply_markup=self._build_markup(
                    question_markup(eid, self._event_deep_link_url(eid))
                )
            )
        await q.answer()

    async def _cb_corrected(self, q, eid: str, label: str):
        if self._already_judged(eid):
            await q.answer("Bereits bewertet")
            return
        self._mark_judged(eid, f"c:{label}", _SOURCE_QUESTION)
        # A correction is a "no" that also names the truth: it counts as
        # confirmed-false for the class that fired AND as an example of
        # the class it really was.
        self._book_verdict(eid, correct=False, source=_SOURCE_QUESTION, corrected=label)
        ts_str = datetime.now().strftime("%H:%M")
        badge = f"🐿 {LABEL_DE.get(label, label)} · {ts_str}"
        await self._set_badge(q, badge)
        await q.answer(badge)

    # ── species correction ───────────────────────────────────────────
    async def _handle_species_cb(self, q, eid: str, arg: str | None):
        """``ev:<eid>:sp[:<arg>]`` — the whole species sub-flow.

        No 4th part opens the picker; ``back``/``none`` are reserved
        words (see `species_correction_markup`); anything else is a
        species name to record.
        """
        if arg is None:
            await self._cb_species_menu(q, eid)
        elif arg == "back":
            await self._cb_species_back(q, eid)
        elif arg == "none":
            await self._cb_species_unsure(q, eid)
        else:
            await self._cb_species_pick(q, eid, arg)

    def _event_species_candidates(self, eid: str, cam: str | None) -> list:
        if not (cam and self.store):
            return []
        with contextlib.suppress(Exception):
            event = self.store.get_event(cam, eid)
            return list((event or {}).get("species_candidates") or [])
        return []

    async def _cb_species_menu(self, q, eid: str):
        """Swap the keyboard for the species picker — edit in place, same
        reasoning as `_cb_alt`: the photo/caption stay the context."""
        ctx = self._event_context(eid)
        current = self._bird_species_of(eid, ctx)
        candidates = self._event_species_candidates(eid, ctx.get("cam"))
        try:
            await q.edit_message_reply_markup(
                reply_markup=self._build_markup(species_correction_markup(eid, candidates, current))
            )
        except Exception as e:
            log.debug("[tg] species markup edit failed: %s", e)
        await q.answer("Welche Art war es wirklich?")

    async def _cb_species_back(self, q, eid: str):
        """Restore whichever keyboard sent this message, species row and
        all — the operator can still answer Ja/Nein/Gültig/Falsch.

        The alarm path's siren button cannot be reconstructed here (it
        depended on the send-time armed/night-wakeup check, not stored
        anywhere retrievable by event id) — a minor loss on the rare
        path where a species picker was opened on an armed night alarm
        and then backed out of.
        """
        if self._already_judged(eid):
            await q.answer("Bereits bewertet")
            return
        ctx = self._event_context(eid)
        try:
            if self._is_question(eid):
                markup = question_markup(eid, self._event_deep_link_url(eid), species_known=True)
            else:
                markup = _event_buttons(
                    eid,
                    ctx.get("cam") or "",
                    False,
                    self._event_deep_link_url(eid),
                    species_known=True,
                )
            await q.edit_message_reply_markup(reply_markup=self._build_markup(markup))
        except Exception as e:
            log.debug("[tg] species back edit failed: %s", e)
        await q.answer()

    async def _cb_species_pick(self, q, eid: str, species: str):
        """The caption's guess was a bird, just the wrong species — the
        class verdict stands (still "correct"), only the species this
        confirms changes. Also fixes the event's own `bird_species` so
        the Mediathek badge and the species-tally agree with what the
        operator just said."""
        if self._already_judged(eid):
            await q.answer("Bereits bewertet")
            return
        self._mark_judged(eid, f"sp:{species}", _SOURCE_QUESTION)
        ctx = self._book_verdict(eid, correct=True, source=_SOURCE_QUESTION, species=species)
        with contextlib.suppress(Exception):
            record_confirmed_video(self._storage_root(), species)
        self._correct_bird_species(eid, ctx.get("cam"), species)
        ts_str = datetime.now().strftime("%H:%M")
        badge = f"🐦 {species} · {ts_str}"
        await self._set_badge(q, badge)
        await q.answer(badge)

    async def _cb_species_unsure(self, q, eid: str):
        """Still a bird — the operator just cannot tell which one.
        Confirms the class, records no species, counts nothing toward
        any species cap."""
        if self._already_judged(eid):
            await q.answer("Bereits bewertet")
            return
        self._mark_judged(eid, "sp:none", _SOURCE_QUESTION)
        self._book_verdict(eid, correct=True, source=_SOURCE_QUESTION, species=None)
        ts_str = datetime.now().strftime("%H:%M")
        badge = f"✅ Ja (Art unsicher) · {ts_str}"
        await self._set_badge(q, badge)
        await q.answer(badge)

    def _correct_bird_species(self, eid: str, cam_id: str | None, species: str) -> None:
        if not (cam_id and self.store):
            return
        with contextlib.suppress(Exception):
            event = self.store.get_event(cam_id, eid)
            if not event:
                return
            event["bird_species"] = species
            self.store.update_event(cam_id, eid, event)

    async def _cb_mute(self, q, eid: str):
        ss = self.settings_store
        ctx = self._event_context(eid)
        cam, label = ctx.get("cam"), ctx.get("label")
        if not cam or not label or not ss:
            await q.answer("Daten zur Erkennung fehlen.")
            return
        suppress = ss.runtime_get("suppress") or {}
        if not isinstance(suppress, dict):
            suppress = {}
        suppress[f"{cam}|{label}"] = time.time() + 3600
        ss.runtime_set("suppress", suppress)
        until_dt = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")
        await self._set_badge(q, f"🔇 Stumm bis {until_dt}")
        await q.answer(f"🔇 1 h still für {LABEL_DE.get(label, label)}")

    async def _cb_siren(self, q, eid: str):
        cam = self._event_context(eid).get("cam")
        rt = self.runtimes.get(cam) if cam else None
        triggered = False
        if rt and hasattr(rt, "trigger_siren"):
            try:
                triggered = bool(rt.trigger_siren())
            except Exception as e:
                log.warning("[tg] trigger_siren failed: %s", e)
        await self._set_badge(q, "🚨 Sirene")
        if triggered:
            await q.answer("🚨 Sirene aktiviert")
        else:
            # Reolink siren API isn't wired yet — log + acknowledge.
            log.info("[tg] siren requested for %s — not implemented", cam)
            await q.answer("🚨 Sirene angefordert (nicht unterstützt)")
