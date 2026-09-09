"""The rare-species override: a confirmed count, not a class label, is
what should gate whether a bird sighting gets asked about.

Two defects motivate this file, both invisible to `test_netz_question.py`
because that file never sets `bird_species` on an event.

**Silently budget-skipped.** `_question_gap_ok` / `_class_budget_left` /
`_question_budget_left` are all keyed by the CLASS label ("bird"), never
by species. A rare species (a first-ever mallard) is exactly as likely
to lose the gap/budget lottery as the fiftieth magpie of the day — the
corpus never hears about it either way.

**Silently archived-only.** `band_for` routes any confident detection
into `KIND_ALARM`, and `on_finalized_event` used to treat that band as
fully handled: archived, done. The actual notification is a SEPARATE
call (`_event_alert.send_event_alert`) gated by `push.labels["bird"].push`
— `False` by default. A confident first-ever sighting therefore reached
NOBODY: not the alarm (push off), not even the quiet question a
lower-confidence sighting of the same species would have earned.

`QuestionMixin._species_rare_override` forces both open for one axis:
a bird species with fewer than `storage.bird_species_ask_until_count`
operator-CONFIRMED videos (`species_video_count.confirmed_video_count`)
is always asked about, regardless of band, gap or budget — while a
non-rare species still runs the ordinary gates untouched.

Drives the real `QuestionMixin` against a stub transport, the same
shape `test_netz_question.py` uses — real gate logic, real net_archive
records, only the Telegram/camera-cfg seams stubbed.
"""

from __future__ import annotations

import pytest

from app import net_archive
from app.settings._consts import BIRD_SPECIES_ASK_UNTIL_DEFAULT
from app.species_video_count import record_confirmed_video
from app.telegram_bot._outbound._question import (
    CLASS_SHARE_MAX,
    DAILY_BUDGET,
    QuestionMixin,
)

CAM_ID = "cam_werkstatt"


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
    """The same seams `test_netz_question.py::_Bot` stubs, plus `_cfg()`
    — the one new gate (`_species_rare_override`) reads a GLOBAL storage
    setting, not the per-camera config every other gate here uses, so it
    goes through the accessor `_camera_cfg` / `_storage_root` /
    `_dashboard_url` already use in production (`LifecycleMixin._cfg`,
    which unwraps the callable `server.py` actually passes)."""

    def __init__(self, root, cam, *, storage=None, quiet=False, muted=None):
        self.enabled = True
        self.push_cfg = {
            "labels": {
                "bird": {"push": False, "threshold": 0.90},
                "person": {"push": True, "threshold": 0.85},
            }
        }
        self.global_cfg = {"storage": dict(storage or {})}
        self.settings_store = _Store()
        self._cam = cam
        self._root = root
        self._quiet = quiet
        self._muted = muted
        self.sent = []

    # ── the seams the mixin reaches through ──
    def _cfg(self):
        return self.global_cfg

    def _camera_cfg(self, _cam_id):
        return self._cam

    def _storage_root(self):
        return self._root

    def _mute_reason(self, _cam_id):
        return self._muted

    def _is_quiet_now(self):
        return self._quiet

    def _best_frame_jpeg(self, _meta, _cam):
        return None

    def _event_deep_link_url(self, _eid):
        return ""

    def _dashboard_url(self):
        return ""

    def send(self, text, **kwargs):
        self.sent.append({"text": text, **kwargs})
        return None


CAM = {
    "id": CAM_ID,
    "name": "Werkstatt",
    "object_filter": ["person", "cat", "bird"],
    "telegram_enabled": True,
    "armed": True,
}


def _meta(eid, score, *, label="bird", species=None):
    meta = {
        "event_id": eid,
        "labels": [label],
        "detections": [{"label": label, "score": score}],
    }
    if species is not None:
        meta["bird_species"] = species
    return meta


def _class_cap() -> int:
    return max(1, int(DAILY_BUDGET * CLASS_SHARE_MAX))


@pytest.fixture
def bot(tmp_storage_root):
    return _Bot(tmp_storage_root, dict(CAM), storage={"bird_species_ask_until_count": 5})


# ── (a) the class daily/share budget cannot swallow a rare species ─────


def test_a_rare_species_is_asked_through_an_exhausted_class_budget(bot):
    cap = _class_cap()
    for i in range(cap):
        bot._question_last = {}
        assert bot.send_question(_meta(f"p-{i}", 0.62), CAM_ID) is None
    # The class share IS exhausted — an ordinary bird question confirms it.
    bot._question_last = {}
    assert bot.send_question(_meta("would-block", 0.62), CAM_ID) == "class_budget"

    # A first-ever mallard, 0 confirmed videos, must go through anyway.
    bot._question_last = {}
    result = bot.on_finalized_event(_meta("mallard-1", 0.62, species="Stockente"), CAM_ID)
    assert result == "frage"
    assert len(bot.sent) == cap + 1

    # Bookkeeping still ran on the forced path — the spend is real, not
    # invisible, or later budget analysis would be silently wrong.
    per = bot.settings_store.runtime["netz_question_budget"]["per"]
    assert per["bird"] == cap + 1


# ── (b) the per-(camera, class) gap cannot swallow a rare species ──────


def test_a_rare_species_is_asked_through_the_per_class_gap(bot):
    assert bot.send_question(_meta("g0", 0.62), CAM_ID) is None
    # Same camera, same class, no time elapsed — the ordinary gap bites.
    assert bot.send_question(_meta("g0b", 0.62), CAM_ID) == "gap"

    # A first-ever mallard right on top of it must still be asked.
    result = bot.on_finalized_event(_meta("mallard-2", 0.62, species="Stockente"), CAM_ID)
    assert result == "frage"
    assert len(bot.sent) == 2
    assert (CAM_ID, "bird") in bot._question_last  # gap-mark still ran


# ── (c) a species that already has enough confirmed videos is NOT forced ──


def test_a_well_documented_species_falls_back_to_ordinary_gating(bot):
    for _ in range(5):
        record_confirmed_video(bot._root, "Stockente")
    # ask_until_count is 5 on the fixture bot: 5 confirmed >= 5 required
    # means the override does not apply — this is an ordinary event.
    assert bot._species_rare_override(_meta("x", 0.62, species="Stockente"), CAM_ID) is False

    bot.send_question(_meta("pre", 0.62), CAM_ID)  # marks the gap
    result = bot.on_finalized_event(_meta("mallard-3", 0.62, species="Stockente"), CAM_ID)
    assert result == "gap"
    assert len(bot.sent) == 1


# ── (d) 0 disables the override entirely ────────────────────────────────


def test_zero_disables_the_override(tmp_storage_root):
    bot = _Bot(tmp_storage_root, dict(CAM), storage={"bird_species_ask_until_count": 0})
    assert bot._species_rare_override(_meta("x", 0.62, species="Stockente"), CAM_ID) is False

    cap = _class_cap()
    for i in range(cap):
        bot._question_last = {}
        bot.send_question(_meta(f"p-{i}", 0.62), CAM_ID)
    bot._question_last = {}
    # With the override off, a novel species is an ordinary bird event —
    # the exhausted class share blocks it exactly like any other.
    result = bot.on_finalized_event(_meta("mallard-4", 0.62, species="Stockente"), CAM_ID)
    assert result == "class_budget"
    assert len(bot.sent) == cap


def test_an_absent_setting_key_falls_back_to_the_shipped_default(tmp_storage_root):
    """`None`-check, not `or` — an install with no `bird_species_ask_
    until_count` key at all must read as the shipped default (5), not as
    an unset-so-falsy 0. The exact bug already fixed once this session
    for `post_motion_tail_s` (see CLAUDE.md's note on
    `resolve_pre_motion_seconds`)."""
    bot = _Bot(tmp_storage_root, dict(CAM), storage={})
    assert BIRD_SPECIES_ASK_UNTIL_DEFAULT > 0
    assert bot._species_rare_override(_meta("x", 0.62, species="Stockente"), CAM_ID) is True


# ── (e) a confident (ALARM-band) rare species is no longer silent ──────


def test_a_confident_rare_species_is_asked_not_silently_archived(bot, tmp_storage_root):
    """THE second blind spot. `push.threshold` for bird is 0.90 — a 0.95
    score used to be filed straight into KIND_ALARM and archived, with
    no message at all (bird ships `push: false`). It must now go through
    `send_question` instead."""
    result = bot.on_finalized_event(_meta("mallard-alarm", 0.95, species="Stockente"), CAM_ID)
    assert result == "frage"
    assert len(bot.sent) == 1
    assert "Unsicher" in bot.sent[0]["text"]
    rec = net_archive.get_record(tmp_storage_root, "mallard-alarm")
    assert rec["kind"] == net_archive.KIND_FRAGE


# ── (f) mute / quiet-hours / camera-off still block a forced question ──


def test_a_disarmed_camera_still_blocks_a_forced_question(tmp_storage_root):
    bot = _Bot(tmp_storage_root, {**CAM, "armed": False})
    result = bot.on_finalized_event(_meta("mallard-5", 0.95, species="Stockente"), CAM_ID)
    assert result == "camera_off"
    assert bot.sent == []


def test_a_mute_still_blocks_a_forced_question(tmp_storage_root):
    bot = _Bot(tmp_storage_root, dict(CAM), muted="manual")
    result = bot.on_finalized_event(_meta("mallard-6", 0.95, species="Stockente"), CAM_ID)
    assert result == "muted"
    assert bot.sent == []


def test_quiet_hours_still_hold_a_forced_question(tmp_storage_root):
    """A forced question still queues to 07:00 rather than buzzing at
    night — only an alarm earns that, and this one was routed away from
    the alarm path specifically so it would NOT buzz."""
    bot = _Bot(tmp_storage_root, dict(CAM), quiet=True)
    result = bot.on_finalized_event(_meta("mallard-7", 0.95, species="Stockente"), CAM_ID)
    assert result == "quiet_hold"
    assert bot.sent == []
    assert len(bot.settings_store.runtime["netz_question_queue"]) == 1
