"""The recording ticker — a walk-in test aid, not an alert.

The user's ask: "wenn eine Detektion dazu geführt hat, dass ein Video
aufgenommen wird … und dann auch, wenn das Video zu Ende ist … dann kann
ich genau abschätzen, wann kann ich denn wieder reinlaufen."

The load-bearing design decision is that it must NOT go through the push
pipeline. Severity matrix, per-label push thresholds, quiet hours and
the notify schedule are frequently the very things being diagnosed when
someone walks in front of a camera — routing the diagnostic through them
would silence it exactly when it is needed.

WHY THIS FILE CHANGED: the fixture used to build its config as
``{"telegram": {"recording_ticker": …}}``, mirroring the reader. But the
default is written one level down, at ``telegram.push.recording_ticker``
(``settings/_consts.TELEGRAM_PUSH_DEFAULTS``), and nothing ever wrote the
top-level key. So the setting was unreachable: the ticker could not be
switched off, and it is documented as a walk-in-test aid meant to be off
in normal operation — two extra Telegram messages per event, forever.
The suite passed the whole time, because it asserted against the reader's
own wrong path instead of against where the value is stored. The fixture
now writes where the writer writes; ``test_the_legacy_top_level_path_is_
still_honoured`` covers a hand-edited install carrying the old key.
"""

from __future__ import annotations

import pytest

from app.camera_runtime._recording._publish import PublishMixin


class _Notifier:
    def __init__(self):
        self.sent = []

    def send_alert_sync(self, caption=None, camera_id=None, **kw):
        self.sent.append(caption)


class _Cam(PublishMixin):
    def __init__(self, *, tg_default=True, **cfg):
        self.camera_id = "cam-test"
        self.notifier = _Notifier()
        self.cfg = {"name": "Werkstatt", "armed": True, "telegram_enabled": True, **cfg}
        self.global_cfg = {"telegram": {"push": {"recording_ticker": tg_default}}}

    def _send_ticker(self, text):  # run inline instead of in a thread
        import time as _t

        now = _t.monotonic()
        from app.camera_runtime._recording._publish import _TICKER_MIN_GAP_S

        if now - getattr(self, "_ticker_last_ts", 0.0) < _TICKER_MIN_GAP_S:
            return
        self._ticker_last_ts = now
        self.notifier.send_alert_sync(caption=text, camera_id=self.camera_id)


def test_start_message_names_camera_and_detection():
    cam = _Cam()
    cam.notify_recording_started(["person"])

    assert len(cam.notifier.sent) == 1
    msg = cam.notifier.sent[0]
    assert "Aufnahme gestartet" in msg
    assert "Werkstatt" in msg
    assert "person" in msg


def test_end_message_carries_the_duration():
    """The duration is the whole point — it says when to walk in again."""
    cam = _Cam()
    cam.notify_recording_finished({"labels": ["person"]}, 12.4)

    msg = cam.notifier.sent[0]
    assert "Aufnahme beendet" in msg
    assert "12 s" in msg


def test_the_end_message_is_never_swallowed_by_the_gap_floor():
    """A start without its matching end leaves the user waiting for a
    signal that never comes — worse than one message too many."""
    cam = _Cam()
    cam.notify_recording_started(["person"])
    cam.notify_recording_finished({"labels": ["person"]}, 3.0)

    assert len(cam.notifier.sent) == 2


def test_repeated_starts_are_rate_limited():
    """A busy scene must not turn the ticker into the noise it cuts through."""
    cam = _Cam()
    for _ in range(5):
        cam.notify_recording_started(["person"])

    assert len(cam.notifier.sent) == 1


def test_disabled_globally_sends_nothing():
    cam = _Cam(tg_default=False)
    cam.notify_recording_started(["person"])
    assert cam.notifier.sent == []


def test_per_camera_override_wins():
    cam = _Cam(tg_default=False, recording_ticker=True)
    cam.notify_recording_started(["person"])
    assert len(cam.notifier.sent) == 1

    off = _Cam(tg_default=True, recording_ticker=False)
    off.notify_recording_started(["person"])
    assert off.notifier.sent == []


@pytest.mark.parametrize("cfg", [{"armed": False}, {"telegram_enabled": False}])
def test_the_operators_off_switches_are_respected(cfg):
    """The ticker bypasses the push GATES, not the camera's own off switch."""
    cam = _Cam(**cfg)
    cam.notify_recording_started(["person"])
    assert cam.notifier.sent == []


def test_no_notifier_is_safe():
    cam = _Cam()
    cam.notifier = None
    cam.notify_recording_started(["person"])  # must not raise


def test_motion_only_event_still_reads_sensibly():
    cam = _Cam()
    cam.notify_recording_started([])
    assert "Bewegung" in cam.notifier.sent[0]


def test_the_switch_is_read_where_the_default_is_written():
    """The drift itself. TELEGRAM_PUSH_DEFAULTS is the single source of the
    key's location; a reader that looks anywhere else cannot be switched."""
    from app.settings._consts import TELEGRAM_PUSH_DEFAULTS

    assert "recording_ticker" in TELEGRAM_PUSH_DEFAULTS

    cam = _Cam()
    cam.global_cfg = {"telegram": {"push": dict(TELEGRAM_PUSH_DEFAULTS, recording_ticker=False)}}
    cam.notify_recording_started(["person"])
    assert cam.notifier.sent == []


def test_the_legacy_top_level_path_is_still_honoured():
    """A hand-edited install can carry the value where the old reader looked.
    It keeps working until migrate_telegram_push_defaults lifts it across."""
    cam = _Cam()
    cam.global_cfg = {"telegram": {"recording_ticker": False}}
    cam.notify_recording_started(["person"])
    assert cam.notifier.sent == []


def test_push_wins_over_the_legacy_path():
    cam = _Cam()
    cam.global_cfg = {"telegram": {"recording_ticker": True, "push": {"recording_ticker": False}}}
    cam.notify_recording_started(["person"])
    assert cam.notifier.sent == []


def test_the_migration_lifts_a_legacy_value_into_push():
    """Additive: the hand-edited False must survive the True default."""
    from app.settings.migrations import migrate_telegram_push_defaults

    data = {"telegram": {"token": "<BOT_TOKEN>", "recording_ticker": False}}
    migrate_telegram_push_defaults(data)

    assert data["telegram"]["push"]["recording_ticker"] is False
    # The dead key goes, so nothing can read the drifted path again.
    assert "recording_ticker" not in data["telegram"]
    assert data["telegram"]["token"] == "<BOT_TOKEN>"


def test_the_migration_leaves_an_already_migrated_value_alone():
    from app.settings.migrations import migrate_telegram_push_defaults

    data = {"telegram": {"recording_ticker": True, "push": {"recording_ticker": False}}}
    migrate_telegram_push_defaults(data)

    assert data["telegram"]["push"]["recording_ticker"] is False


def test_the_migration_is_idempotent():
    from app.settings.migrations import migrate_telegram_push_defaults

    data = {"telegram": {"recording_ticker": False}}
    migrate_telegram_push_defaults(data)
    migrate_telegram_push_defaults(data)

    assert data["telegram"]["push"]["recording_ticker"] is False


def test_the_ticker_does_not_run_through_the_push_pipeline():
    """send_event_alert applies nine gates; send_alert_sync applies none.
    Using the former would silence the diagnostic under exactly the
    conditions it exists to diagnose."""
    import inspect

    src = inspect.getsource(PublishMixin._send_ticker)
    assert "send_alert_sync" in src
    assert "send_event_alert" not in src
