"""The Telegram question: which band, how many, and when they are held.

Drives the real ``QuestionMixin`` against a stub transport. What is
pinned here is behaviour, not source text: a burst of events must not
produce a burst of questions, an alarm at 03:00 must still go out at
03:00, and an event over budget must still leave a record.
"""

from __future__ import annotations

import pytest

from app import net_archive
from app.telegram_bot._outbound._question import DAILY_BUDGET, QuestionMixin


class _Store:
    """Just the runtime API the mixin touches."""

    def __init__(self):
        self.runtime = {}
        self.alert_index = {}

    def runtime_get(self, key, default=None):
        return self.runtime.get(key, default)

    def runtime_set(self, key, value):
        self.runtime[key] = value

    def runtime_alert_index_set(self, eid, payload, cap=200):
        self.alert_index[eid] = payload


class _Bot(QuestionMixin):
    def __init__(self, root, cam, *, quiet=False):
        self.enabled = True
        self.push_cfg = {"labels": {"person": {"push": True, "threshold": 0.85}}}
        self.global_cfg = {"app": {"public_base_url": "https://example.invalid"}}
        self.settings_store = _Store()
        self._cam = cam
        self._root = root
        self._quiet = quiet
        self.sent = []

    # ── the seams the mixin reaches through ──
    def _camera_cfg(self, _cam_id):
        return self._cam

    def _storage_root(self):
        return self._root

    def _mute_reason(self, _cam_id):
        return None

    def _is_quiet_now(self):
        return self._quiet

    def _best_frame_jpeg(self, _meta, _cam):
        return None

    def _event_deep_link_url(self, _eid):
        return ""

    def _dashboard_url(self):
        # The real one reads `global_cfg()` — a CALLABLE in production.
        # `_netz_deep_link` used to reach for `.get` on it directly and
        # raised AttributeError inside the 07:00 release job.
        return self.global_cfg["app"]["public_base_url"]

    def send(self, text, **kwargs):
        self.sent.append({"text": text, **kwargs})
        return None


CAM = {
    "id": "cam_werkstatt",
    "name": "Werkstatt",
    "object_filter": ["person", "cat"],
    "telegram_enabled": True,
    "armed": True,
}


def _meta(eid, score, label="person"):
    return {
        "event_id": eid,
        "labels": [label],
        "detections": [{"label": label, "score": score}],
    }


@pytest.fixture
def bot(tmp_storage_root):
    return _Bot(tmp_storage_root, dict(CAM))


# ── the three bands ───────────────────────────────────────────────────


def test_the_band_is_decided_by_the_same_ladder_the_push_gate_uses(bot):
    """Shipped person: spawn 0.45, push 0.85."""
    assert bot.band_for(_meta("a", 0.92), "cam_werkstatt") == net_archive.KIND_ALARM
    assert bot.band_for(_meta("b", 0.62), "cam_werkstatt") == net_archive.KIND_FRAGE
    assert bot.band_for(_meta("c", 0.20), "cam_werkstatt") is None


def test_an_alarm_is_archived_but_never_re_asked(bot):
    """It already went out with its own ✅/❌ — a second bubble asking
    the same question would be noise."""
    assert bot.on_finalized_event(_meta("evt-alarm", 0.92), "cam_werkstatt") == "alarm"
    assert bot.sent == []
    rec = net_archive.get_record(bot._root, "evt-alarm")
    assert rec["kind"] == net_archive.KIND_ALARM


def test_a_question_is_sent_silently(bot):
    assert bot.on_finalized_event(_meta("evt-q", 0.62), "cam_werkstatt") == "frage"
    assert len(bot.sent) == 1
    # Questions must NEVER buzz, day or night. Only alarms earn that.
    assert bot.sent[0]["silent"] is True
    assert "Unsicher" in bot.sent[0]["text"]


def test_below_spawn_produces_nothing_at_all(bot):
    assert bot.on_finalized_event(_meta("evt-low", 0.10), "cam_werkstatt") is None
    assert bot.sent == []
    assert net_archive.get_record(bot._root, "evt-low") is None


# ── bounding ──────────────────────────────────────────────────────────


def test_a_burst_of_events_does_not_send_a_burst_of_questions(bot):
    """One squirrel visit is one question, not six. The 10-minute gap is
    per (camera, class) and runs on the monotonic clock."""
    for i in range(6):
        bot.send_question(_meta(f"burst-{i}", 0.62), "cam_werkstatt")
    assert len(bot.sent) == 1
    # A DIFFERENT class on the same camera is not gagged by it.
    bot.send_question(_meta("other-class", 0.62, label="cat"), "cam_werkstatt")
    assert len(bot.sent) == 2


def test_the_thirteenth_question_of_the_day_is_not_sent(bot):
    """MANDATORY #7 — and the record is still written, with asked=false,
    so the surplus surfaces in the archive under "Noch nicht beurteilt"
    instead of vanishing."""
    for i in range(DAILY_BUDGET):
        bot._question_last = {}  # let the per-class gap through
        assert bot.send_question(_meta(f"q-{i}", 0.62), "cam_werkstatt") is None
    bot._question_last = {}
    assert bot.send_question(_meta("q-over", 0.62), "cam_werkstatt") == "budget"
    assert len(bot.sent) == DAILY_BUDGET
    rec = net_archive.get_record(bot._root, "q-over")
    assert rec is not None and rec["asked"] is False


def test_the_budget_resets_with_the_calendar_day(bot):
    bot.settings_store.runtime["netz_question_budget"] = {"day": "1999-01-01", "n": 99}
    assert bot._question_budget_left() == DAILY_BUDGET


# ── quiet hours ───────────────────────────────────────────────────────


def test_at_night_a_question_is_held_and_an_alarm_is_not(tmp_storage_root):
    """MANDATORY #6. A security alert at 03:00 arrives at 03:00, exactly
    as today. Only the question waits."""
    bot = _Bot(tmp_storage_root, dict(CAM), quiet=True)
    assert bot.on_finalized_event(_meta("night-alarm", 0.92), "cam_werkstatt") == "alarm"
    assert bot.send_question(_meta("night-q", 0.62), "cam_werkstatt") == "quiet_hold"
    assert bot.sent == []
    assert len(bot.settings_store.runtime["netz_question_queue"]) == 1


def test_the_night_release_is_one_message_not_a_digest(tmp_storage_root):
    """A Telegram message with thirty thumbnails is unanswerable on a
    phone. One line, one button, and the judging happens in the archive."""
    bot = _Bot(tmp_storage_root, dict(CAM), quiet=True)
    for i in range(6):
        bot._question_last = {}
        bot.send_question(_meta(f"n-{i}", 0.62), "cam_werkstatt")
    assert bot.sent == []
    bot._job_question_release()
    assert len(bot.sent) == 1
    assert "6 Erkennungen" in bot.sent[0]["text"]
    assert bot.sent[0]["silent"] is True
    # Queue drained — a second run must not re-announce the same night.
    bot._job_question_release()
    assert len(bot.sent) == 1


def test_the_night_queue_is_bounded(tmp_storage_root):
    bot = _Bot(tmp_storage_root, dict(CAM), quiet=True)
    for i in range(40):
        bot._question_last = {}
        bot.send_question(_meta(f"flood-{i}", 0.62), "cam_werkstatt")
    assert len(bot.settings_store.runtime["netz_question_queue"]) == 20


def test_a_disarmed_or_telegram_off_camera_is_never_asked(tmp_storage_root):
    for key in ("armed", "telegram_enabled"):
        bot = _Bot(tmp_storage_root, {**CAM, key: False})
        assert bot.send_question(_meta("x", 0.62), "cam_werkstatt") == "camera_off"
        assert bot.sent == []


def test_a_class_with_push_disabled_is_still_asked_about(tmp_storage_root):
    """The whole point. `cat` ships with push:false, so it has no corpus
    — and asking about it is the only way it ever gets one."""
    bot = _Bot(tmp_storage_root, dict(CAM))
    bot.push_cfg = {"labels": {"cat": {"push": False, "threshold": 0.80}}}
    assert bot.send_question(_meta("cat-1", 0.62, label="cat"), "cam_werkstatt") is None
    assert len(bot.sent) == 1


# ── the callback payloads ─────────────────────────────────────────────


def test_every_callback_fits_telegrams_64_byte_limit():
    """`_send._build_markup` truncates at 64 bytes, and a truncated
    callback routes to the wrong branch or to none at all."""
    from app.telegram_bot._outbound._question import (
        question_class_markup,
        question_markup,
    )

    eid = "20260828-141233-874512"  # the real shape, 22 chars
    rows = question_markup(eid, "https://example.invalid/#/event/x")
    rows += question_class_markup(eid, ["person", "cat", "squirrel", "hedgehog"])
    for row in rows:
        for _label, payload in row:
            assert len(payload.encode("utf-8")) <= 64
