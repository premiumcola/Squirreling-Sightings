"""C8 · the status snapshot must report send-loop health, not just polling.

TelegramService runs two threads: ``tg-polling`` (getUpdates) and
``tg-send-loop`` (the asyncio loop every send() dispatches into).
get_polling_status only ever inspected the polling one, so a dead send
loop left /api/telegram/status, the cam-edit health strip and the
watchdog heartbeat all reporting "active" while every alert no-op'd into
a loop nobody was running.

Stub-only: no bot, no token, no network. The threads here are ordinary
sleeping/finished Python threads, never real asyncio loops.
"""

from __future__ import annotations

import threading
import time

import flask
import pytest

from app import app_state
from app.routes.telegram import bp
from app.telegram_bot import TelegramService


class _Service(TelegramService):
    """Real service class, hand-built state. __init__ is deliberately not
    called — it would construct a telegram.Bot — so this sets exactly the
    attributes the status snapshot reads, and nothing that could talk to
    the network. Subclassing the composed class (rather than one mixin)
    keeps the test honest about where the method actually resolves."""

    def __init__(self, *, poll_alive: bool, loop_thread):
        self.enabled = True
        self._poll_thread = _live_thread() if poll_alive else None
        self._loop_thread = loop_thread
        self._polling_active_since = 1.0
        self._last_conflict_ts = None
        self._conflict_quarantine = False
        self._stale_poll_thread = None
        self._stale_since = None


def _live_thread() -> threading.Thread:
    """A thread that stays alive until the test's stop event fires."""
    ev = threading.Event()
    t = threading.Thread(target=ev.wait, daemon=True)
    t._stop_event = ev  # kept so the fixture can join it
    t.start()
    return t


def _dead_thread() -> threading.Thread:
    """A thread that has already run to completion — is_alive() False,
    which is exactly what a crashed send loop leaves behind."""
    t = threading.Thread(target=lambda: None, daemon=True)
    t.start()
    t.join()
    return t


@pytest.fixture
def live_threads():
    made: list[threading.Thread] = []

    def _make():
        t = _live_thread()
        made.append(t)
        return t

    yield _make
    for t in made:
        t._stop_event.set()
        t.join(timeout=2)


@pytest.fixture
def client():
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


def test_status_reports_send_loop_alive(live_threads):
    svc = _Service(poll_alive=True, loop_thread=live_threads())
    status = svc.get_polling_status()
    assert status["state"] == "active"
    assert status["send_loop_alive"] is True


def test_dead_send_loop_visible_while_polling_active(live_threads):
    """The regression this closes: polling healthy, send loop gone. The
    state field cannot express that — send_loop_alive has to."""
    svc = _Service(poll_alive=True, loop_thread=_dead_thread())
    status = svc.get_polling_status()
    assert status["state"] == "active"
    assert status["send_loop_alive"] is False


def test_missing_loop_thread_is_not_alive():
    """Before start() (and after stop()) _loop_thread is None."""
    svc = _Service(poll_alive=False, loop_thread=None)
    assert svc.send_loop_alive() is False
    assert svc.get_polling_status()["send_loop_alive"] is False


def test_disabled_service_still_reports_the_field():
    """The `off` branch returns early — it must carry the key too, or
    consumers have to special-case it."""
    svc = _Service(poll_alive=False, loop_thread=None)
    svc.enabled = False
    status = svc.get_polling_status()
    assert status["state"] == "off"
    assert status["send_loop_alive"] is False


def test_every_state_branch_carries_the_field(live_threads):
    """Six documented states, six early returns — none may drop the key."""
    svc = _Service(poll_alive=True, loop_thread=live_threads())
    snapshots = [svc.get_polling_status()]  # active
    svc.enabled = False
    snapshots.append(svc.get_polling_status())  # off
    svc.enabled = True
    svc._polling_active_since = None
    snapshots.append(svc.get_polling_status())  # starting
    svc._last_conflict_ts = time.time()
    snapshots.append(svc.get_polling_status())  # conflict
    svc._conflict_quarantine = True
    snapshots.append(svc.get_polling_status())  # conflict_quarantine
    svc._conflict_quarantine = False
    svc._stale_poll_thread = live_threads()
    snapshots.append(svc.get_polling_status())  # stale
    assert {s["state"] for s in snapshots} == {
        "active",
        "off",
        "starting",
        "conflict",
        "conflict_quarantine",
        "stale",
    }
    assert all("send_loop_alive" in s for s in snapshots)


def test_system_endpoint_surfaces_send_loop_alive(client, monkeypatch, live_threads):
    monkeypatch.setattr(
        app_state,
        "telegram_service",
        _Service(poll_alive=True, loop_thread=_dead_thread()),
        raising=False,
    )
    body = client.get("/api/system/telegram").get_json()
    assert body["connected"] is True
    assert body["send_loop_alive"] is False

    monkeypatch.setattr(
        app_state,
        "telegram_service",
        _Service(poll_alive=True, loop_thread=live_threads()),
        raising=False,
    )
    body = client.get("/api/system/telegram").get_json()
    assert body["send_loop_alive"] is True


def test_system_endpoint_defaults_field_without_service(client, monkeypatch):
    monkeypatch.setattr(app_state, "telegram_service", None, raising=False)
    assert client.get("/api/system/telegram").get_json()["send_loop_alive"] is False


# ── HYG-2 · failing sends must be countable ───────────────────────────
#
# The blind spot one layer below the send loop: send_alert catches
# everything non-transient, logs it and returns None, and no caller
# checks the Future. A revoked token drops every alert while state,
# send_loop_alive and the polling thread all stay green.


def test_status_reports_zero_failures_before_anything_fails(live_threads):
    svc = _Service(poll_alive=True, loop_thread=live_threads())
    status = svc.get_polling_status()
    assert status["send_failures"] == 0
    assert status["last_send_error"] is None


def test_status_counts_send_failures_and_names_the_last_one(live_threads):
    svc = _Service(poll_alive=True, loop_thread=live_threads())
    svc._send_failures = 2
    svc._last_send_error = "Forbidden: bot was blocked by the user"
    status = svc.get_polling_status()
    assert status["state"] == "active"  # polling is fine — that is the point
    assert status["send_failures"] == 2
    assert status["last_send_error"] == "Forbidden: bot was blocked by the user"


def test_disabled_service_still_reports_the_counter():
    """The `off` branch returns early — it must carry the new keys too."""
    svc = _Service(poll_alive=False, loop_thread=None)
    svc.enabled = False
    status = svc.get_polling_status()
    assert status["send_failures"] == 0
    assert "last_send_error" in status
