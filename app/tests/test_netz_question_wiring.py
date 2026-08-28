"""The question, driven end-to-end — and the corpus it has to reach.

Two defects lived underneath a green unit-test file, because that file
built its ``meta`` by hand and used a shape production never produces.

**It never fired.** ``_motion._build_event_meta`` writes ``labels:
sorted(set(labels))``, so an event that saw a person while motion was
still confirming is filed as ``["motion", "person"]``. ``band_for`` took
``labels[0]`` — alphabetically ``"motion"``, which sorts ahead of both
``person`` and ``squirrel``, the two classes these three cameras exist
for. ``motion`` ships with ``threshold: 0.0`` and carries no detection of
its own, so the comparison was ``0.0 >= 0.0``: every real event was
classified as an ALARM at a 0-percent score, no question was ever sent,
and the archive filled with fabricated alarms about nothing.

**Its answers went nowhere.** ``judged_alerts`` — the only thing the
learner, the axis proposal and the drag preview read — iterates ALERT
records and looks each one's verdict up. ``record_alert`` was written
inside the push chain, which runs only when ``meta["notify"]`` is true;
``cat``, ``bird``, ``fox``, ``hedgehog`` and everything on ``severity:
off`` never notify. Their verdicts were written to disk and counted by
nothing — for exactly the classes with no corpus, which is the set the
whole feature exists to fill.

So these drive the REAL ``PublishMixin._publish_finalized_event`` against
a REAL ``TelegramService``, with the meta shape ``_build_event_meta``
actually emits, and then read the corpus back through the reader the
learner uses.
"""

from __future__ import annotations

import pytest

from app import net_archive
from app.camera_runtime._recording._publish import PublishMixin
from app.detection_feedback import judged_alerts, record_verdict
from app.telegram_bot import TelegramService

CAM_ID = "cam_werkstatt"
# Structurally valid and entirely fictional. Built rather than written
# out so the literal never appears in a tracked file: the public-repo
# audit greps for exactly this shape, and a hit it has to think about is
# a hit that trains everyone to ignore the next one.
_FAKE_TOKEN = "123456789" + ":" + "A" * 35


class _SettingsStub:
    def __init__(self):
        self.runtime = {}

    def runtime_get(self, key, default=None):
        return self.runtime.get(key, default)

    def runtime_set(self, key, value):
        self.runtime[key] = value

    def runtime_get_subkey(self, key, subkey, default=None):
        return (self.runtime.get(key) or {}).get(subkey, default)

    def runtime_set_subkey_lru(self, key, subkey, value, cap):
        self.runtime.setdefault(key, {})[subkey] = value

    def runtime_alert_index_set(self, eid, payload, cap=200):
        self.runtime_set_subkey_lru("alert_index", eid, payload, cap)


class _StoreStub:
    def get_event(self, *_a, **_k):
        return {}

    def update_event(self, *_a, **_k):
        pass

    def add_event(self, *_a, **_k):
        pass


class _Runtime(PublishMixin):
    """Only what ``_publish_finalized_event`` reaches for. The publish
    step itself is the real one — that is the point of the file."""

    def __init__(self, cam, global_cfg, notifier):
        self.camera_id = CAM_ID
        self.cfg = cam
        self.global_cfg = global_cfg
        self.notifier = notifier
        self.store = _StoreStub()
        self.mqtt = None

    def _apply_first_since(self, *_a, **_k):
        pass

    def _publish_achievement(self, *_a, **_k):
        pass

    def _publish_quests(self, *_a, **_k):
        pass

    def _publish_dossiers(self, *_a, **_k):
        pass

    def notify_recording_finished(self, *_a, **_k):
        pass


def _cam(**overrides):
    cam = {
        "id": CAM_ID,
        "name": "Werkstatt",
        "role": "security",
        "object_filter": ["person", "cat", "bird", "squirrel"],
        "armed": True,
        "telegram_enabled": True,
        "recording_ticker": False,
    }
    cam.update(overrides)
    return cam


@pytest.fixture
def rig(tmp_storage_root):
    """(runtime, service, sent-list) wired the way `server.py` wires them."""
    cam = _cam()
    global_cfg = {
        "storage": {"root": str(tmp_storage_root)},
        "cameras": [cam],
        "server": {},
        "telegram": {},
    }
    svc = TelegramService(
        cfg={
            "enabled": True,
            "token": _FAKE_TOKEN,
            "chat_id": "-100000000000",
            "push": {
                "labels": {
                    "person": {"push": True, "threshold": 0.85},
                    "cat": {"push": False, "threshold": 0.80},
                    "motion": {"push": False, "threshold": 0.0},
                }
            },
        },
        store=None,
        runtimes={},
        # A CALLABLE, exactly as `server._reload_telegram_service` passes it.
        global_cfg=lambda: global_cfg,
        settings_store=_SettingsStub(),
    )
    sent = []
    svc.send = lambda text, **kw: sent.append({"text": text, **kw})
    return _Runtime(cam, global_cfg, svc), svc, sent


def _meta(event_id, label, score, *, notify=False):
    """The shape `_motion._build_event_meta` emits, motion included.

    ``sorted(set(...))`` is not decoration here — it IS the bug: it is
    what puts ``"motion"`` in front of ``"person"``.
    """
    return {
        "event_id": event_id,
        "labels": sorted({"motion", label}),
        "top_label": label,
        "detections": [{"label": label, "score": score}],
        "notify": notify,
        "send_telegram": True,
        "alarm_level": "info",
        "severity": "info" if notify else "off",
    }


def _publish(rig, meta):
    rt, _svc, _sent = rig
    rt._publish_finalized_event({"event_id": meta["event_id"]}, meta, None)


# ── B1 · it has to fire ───────────────────────────────────────────────


def test_a_mid_band_person_asks_through_the_real_finalize_chain(rig, tmp_storage_root):
    _rt, _svc, sent = rig
    _publish(rig, _meta("evt-person-mid", "person", 0.62))
    assert len(sent) == 1
    assert "Unsicher" in sent[0]["text"]
    assert "Person" in sent[0]["text"]
    # A question never buzzes — only an alarm earns that.
    assert sent[0]["silent"] is True
    assert net_archive.get_record(tmp_storage_root, "evt-person-mid")["kind"] == (
        net_archive.KIND_FRAGE
    )


def test_a_mid_band_squirrel_asks_too(rig, tmp_storage_root):
    """`squirrel` also sorts after `motion`, so the feeder camera — the
    one class the whole wildlife side of this system is about — was in
    exactly the same hole as `person`."""
    _rt, _svc, sent = rig
    _publish(rig, _meta("evt-squirrel-mid", "squirrel", 0.60))
    assert len(sent) == 1
    assert net_archive.get_record(tmp_storage_root, "evt-squirrel-mid")["kind"] == (
        net_archive.KIND_FRAGE
    )


def test_an_event_above_the_bar_is_archived_as_an_alarm_and_not_re_asked(rig, tmp_storage_root):
    _rt, _svc, sent = rig
    _publish(rig, _meta("evt-person-high", "person", 0.94, notify=True))
    # ONE bubble: the alarm, with its own ✅/❌. A second one asking the
    # same question underneath it would be noise.
    assert len(sent) == 1
    assert "Unsicher" not in sent[0]["text"]
    assert sent[0]["buttons"][0][0] == ("✅ Gültig", "ev:evt-person-high:ok")
    assert net_archive.get_record(tmp_storage_root, "evt-person-high")["kind"] == (
        net_archive.KIND_ALARM
    )


def test_a_motion_only_clip_produces_no_question_and_no_alarm(rig, tmp_storage_root):
    """The regression that hid the whole feature. `motion` resolves to
    push 0.0 and no detection carries the label, so `0.0 >= 0.0` filed
    every clip these cameras record as a 0-percent ALARM."""
    _rt, _svc, sent = rig
    _publish(
        rig,
        {
            "event_id": "evt-motion-only",
            "labels": ["motion"],
            "top_label": "motion",
            "detections": [],
            "notify": False,
            "send_telegram": True,
        },
    )
    assert sent == []
    assert net_archive.get_record(tmp_storage_root, "evt-motion-only") is None
    assert judged_alerts(tmp_storage_root) == []


# ── B2 · the answer has to reach the corpus ───────────────────────────


@pytest.mark.parametrize(
    ("label", "score"),
    [
        # push:true — the alert path would have written a row, but only
        # because `notify` happened to be on.
        ("person", 0.62),
        # push:false, so it never reaches the push chain at all. This is
        # the feeder camera's whole subject and the classifier's whole
        # point, and every answer about it used to be discarded.
        ("cat", 0.62),
        # No entry in `telegram.push.labels` whatsoever.
        ("squirrel", 0.60),
    ],
)
def test_an_answer_reaches_the_corpus_for_every_class_with_an_axis(
    rig, tmp_storage_root, label, score
):
    _rt, svc, _sent = rig
    eid = f"evt-{label}"
    _publish(rig, _meta(eid, label, score))
    # The verdict the Telegram button books, through the real writer.
    svc._book_verdict(eid, correct=True, source="telegram_q")
    pairs = judged_alerts(tmp_storage_root, cam_id=CAM_ID, label=label)
    assert len(pairs) == 1, f"{label}: the answer was written and then dropped"
    alert, correct = pairs[0]
    assert correct is True
    assert alert["score"] == pytest.approx(score)
    assert alert["label"] == label


def test_a_question_the_gap_swallowed_still_counts_as_a_candidate(rig, tmp_storage_root):
    """Otherwise the answer rate is computed against a denominator that
    silently excludes every event the 10-minute spacing dropped."""
    _rt, _svc, sent = rig
    _publish(rig, _meta("gap-1", "person", 0.62))
    _publish(rig, _meta("gap-2", "person", 0.63))
    assert len(sent) == 1
    record_verdict(tmp_storage_root, event_id="gap-2", correct=False, ts=1.0, cam_id=CAM_ID)
    assert len(judged_alerts(tmp_storage_root, cam_id=CAM_ID, label="person")) == 1
