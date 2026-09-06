"""How many questions a day, and how far apart — the two counters.

Split out of ``_question.py`` when that file crossed CLAUDE.md's 500-line
ceiling, and this is the seam that actually holds: everything here is
BOOKKEEPING. It decides how often to speak, never what to say. The
question itself — the band it lives in, the caption, the buttons, the
archive record — stays next door.

Three limits, and each answers a different failure:

    DAILY_BUDGET      a runaway night must not bury the phone
    CLASS_SHARE_MAX   one busy class must not spend the whole day
    PER_CLASS_GAP_S   one visit is one question, not six

Every number below was measured against this installation rather than
chosen, and the measurement is written beside it — a limit whose
provenance is lost is a limit nobody dares to change.
"""

from __future__ import annotations

import time
from datetime import datetime

#: Questions per day, GLOBAL across every camera.
#:
#: WAS 12, ON AN ASSUMPTION THE ARCHIVE CONTRADICTS. The old comment read
#: "Seven events a day are expected, so this is 1.7x headroom" — measured
#: over the real timeline of this installation (GET /api/timeline?days=7,
#: 2026-08-30..09-06) those seven days carried 118 events: 15 · 3 · 14 ·
#: 1 · 0 · 6 · 64 · 15. A mean of 17 a day and a peak of 64. The budget
#: sat below the average day, not above it — and the archive shows the
#: day it bit: on 2026-09-05 exactly 12 questions went out, the last at
#: 18:36, and seven more were recorded unasked through the evening.
#:
#: Raised on the operator's own request — „Ich will öfter gefragt werden
#: mit Bild zur Bestätigung ob was ok ist". 40 is a little over twice the
#: measured average and still a hard ceiling, which is the only thing
#: this number was ever for.
DAILY_BUDGET = 40

#: The largest share of one day's questions a SINGLE class may take.
#:
#: Measured, not chosen: of 43 questions in the archive, 36 were
#: `person`, 4 `bird`, 2 `car`, 1 `cat` — and on the day the budget ran
#: out, all 19 were `person`. Raising the global number alone would have
#: bought mostly more person questions, while the class the operator
#: actually asked about („bitte schlage auch Vogelarten vor") stayed at
#: four answers for the week.
#:
#: 0.4 of 40 is 16 a day for any one class. Generous enough that a real
#: person event is never dropped for want of room, tight enough that a
#: busy driveway cannot spend the day before a bird arrives.
CLASS_SHARE_MAX = 0.4

#: Minimum seconds between two questions for the same (camera, class).
#: One visit is one question, not six. Monotonic clock, the
#: `_TICKER_MIN_GAP_S` pattern from `_recording/_publish.py`.
#:
#: Halved with the budget: ten minutes meant a feeder busy all morning
#: produced six questions before lunch. Five still collapses one visit
#: into one question, which is the point of the gap.
PER_CLASS_GAP_S = 300.0

_BUDGET_KEY = "netz_question_budget"


class QuestionBudgetMixin:
    """The two counters. Mixin — state via ``self.settings_store``."""

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

    def _class_budget_left(self, label: str) -> int:
        """How many of today's questions this ONE class may still spend.

        A GLOBAL number was the wrong dial, and the archive says so: of
        43 questions asked, 36 were `person`, 4 `bird`, 2 `car`, 1 `cat`
        — and on the day the budget ran out, all 19 were `person`.
        Raising the total therefore buys mostly more person questions,
        while the axis the operator actually asked about („bitte schlage
        auch Vogelarten vor") stays at four answers all week. A busy
        driveway would go on crowding out every other class, and the
        corpus would keep learning the one thing it already knows.

        The cap is per class and deliberately generous: no single class
        may take more than `CLASS_SHARE_MAX` of the day. Nothing is
        reserved for anyone — a quiet day still lets person have its
        share and no more, and the room left over is there when a bird
        finally turns up.
        """
        ss = self.settings_store
        if not ss:
            return 0
        cap = max(1, int(DAILY_BUDGET * CLASS_SHARE_MAX))
        today = datetime.now().strftime("%Y-%m-%d")
        state = ss.runtime_get(_BUDGET_KEY) or {}
        if not isinstance(state, dict) or state.get("day") != today:
            return cap
        per = state.get("per") or {}
        if not isinstance(per, dict):
            return cap
        return max(0, cap - int(per.get(label) or 0))

    def _question_budget_spend(self, label: str = "") -> None:
        ss = self.settings_store
        if not ss:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        state = ss.runtime_get(_BUDGET_KEY) or {}
        if not isinstance(state, dict) or state.get("day") != today:
            state = {"day": today, "n": 0, "per": {}}
        state["n"] = int(state.get("n") or 0) + 1
        per = state.get("per")
        if not isinstance(per, dict):
            per = {}
        if label:
            per[label] = int(per.get(label) or 0) + 1
        state["per"] = per
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
