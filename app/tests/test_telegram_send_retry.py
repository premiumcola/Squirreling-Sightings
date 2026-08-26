"""C6 · send_alert must survive a transient failure instead of dropping the alert.

The old send_alert wrapped the whole API call in one `except Exception`
that logged and returned None. RetryAfter (HTTP 429) was never imported
anywhere in the package, and every real caller throws away the Future
that send() returns — so one flood-control response during a burst of
detections, or a two-second network blip, lost that alert for good and
nothing upstream ever knew.

Stub-only: `bot` is a fake object that raises canned telegram.error
exceptions. No token, no network, no event loop beyond asyncio.run.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from app.telegram_bot import TelegramService


class _FakeBot:
    """Records every call and replays a scripted list of outcomes.
    An exception in the script is raised, anything else is returned."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, dict]] = []
        self.payloads: list[bytes] = []

    async def _next(self, kind: str, **kwargs):
        self.calls.append((kind, kwargs))
        # Drain any upload stream exactly like httpx would, so a retry
        # that reused the spent handle would show up as empty bytes.
        for value in kwargs.values():
            if hasattr(value, "read"):
                self.payloads.append(value.read())
        outcome = self.script.pop(0) if self.script else "sent"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def send_message(self, **kwargs):
        return await self._next("message", **kwargs)

    async def send_photo(self, **kwargs):
        return await self._next("photo", **kwargs)

    async def send_document(self, **kwargs):
        return await self._next("document", **kwargs)

    async def send_video(self, **kwargs):
        return await self._next("video", **kwargs)


class _Service(TelegramService):
    """Real service class with hand-built state — __init__ is skipped so
    no telegram.Bot is constructed and nothing can reach the network."""

    def __init__(self, script):
        self.enabled = True
        self.chat_id = "4711"
        self.bot = _FakeBot(script)
        self._last_push_ts = None


@pytest.fixture
def sleeps(monkeypatch):
    """Swallow the backoff sleeps and record how long each one asked for,
    so the test asserts on the delay without waiting it out."""
    recorded: list[float] = []

    async def _fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return recorded


def _run(svc, **kwargs):
    return asyncio.run(svc.send_alert("hi", parse_mode=None, **kwargs))


def test_first_attempt_success_does_not_retry(sleeps):
    svc = _Service(["ok"])
    assert _run(svc) == "ok"
    assert len(svc.bot.calls) == 1
    assert sleeps == []
    assert svc._last_push_ts is not None


def test_retry_after_is_retried_once_and_delivers(sleeps):
    svc = _Service([RetryAfter(3), "ok"])
    assert _run(svc) == "ok"
    assert len(svc.bot.calls) == 2
    assert sleeps == [3.0]
    assert svc._last_push_ts is not None


def test_retry_after_delay_is_capped(sleeps):
    """Telegram can ask for minutes. Waiting that long parks the send
    loop, so the wait is capped."""
    svc = _Service([RetryAfter(600), "ok"])
    assert _run(svc) == "ok"
    assert sleeps == [15.0]  # _retry.RETRY_AFTER_CAP_S


def test_network_error_is_retried_once_and_delivers(sleeps):
    svc = _Service([NetworkError("connection reset"), "ok"])
    assert _run(svc) == "ok"
    assert len(svc.bot.calls) == 2
    assert sleeps == [2.0]  # _retry.NETWORK_BACKOFF_S


def test_timed_out_is_retried_once_and_delivers(sleeps):
    svc = _Service([TimedOut(), "ok"])
    assert _run(svc) == "ok"
    assert len(svc.bot.calls) == 2


def test_photo_payload_is_rebuilt_for_the_retry(sleeps):
    """The retry must not reuse the BytesIO the failed request consumed —
    that would upload an empty file. Both attempts get a fresh, full
    stream."""
    svc = _Service([RetryAfter(1), "ok"])
    assert asyncio.run(svc.send_alert("cap", photo=b"\xff\xd8jpegbytes", parse_mode=None)) == "ok"
    assert [kind for kind, _ in svc.bot.calls] == ["photo", "photo"]
    assert svc.bot.payloads == [b"\xff\xd8jpegbytes", b"\xff\xd8jpegbytes"]


def test_each_class_retries_only_once(sleeps):
    """Two 429s in a row give up — a bounded retry, not a loop."""
    svc = _Service([RetryAfter(1), RetryAfter(1), "ok"])
    assert _run(svc) is None
    assert len(svc.bot.calls) == 2


def test_network_then_flood_each_get_their_one_retry(sleeps):
    """The two classes count separately, so a blip followed by a 429
    still lands. Worst case is three attempts total."""
    svc = _Service([NetworkError("blip"), RetryAfter(1), "ok"])
    assert _run(svc) == "ok"
    assert len(svc.bot.calls) == 3


def test_permanent_error_is_not_retried(sleeps):
    """A revoked token / blocked chat must fail fast — same behaviour as
    before the retry landed: logged, None, no second attempt."""
    svc = _Service([Forbidden("bot was blocked by the user")])
    assert _run(svc) is None
    assert len(svc.bot.calls) == 1
    assert sleeps == []
    assert svc._last_push_ts is None


def test_bad_request_is_not_retried(sleeps):
    """BadRequest subclasses NetworkError in python-telegram-bot, but a
    malformed payload never becomes valid by resending it."""
    svc = _Service([BadRequest("chat not found")])
    assert _run(svc) is None
    assert len(svc.bot.calls) == 1
    assert sleeps == []


# ── HYG-2 · giving up must leave a trace ──────────────────────────────
#
# Failing fast is right; failing invisibly is not. Nobody checks the
# Future, so the only places a dropped alert can still be noticed are
# the log and the status snapshot.


def test_a_dropped_alert_is_counted_and_named(sleeps):
    svc = _Service([Forbidden("bot was blocked by the user")])
    assert _run(svc) is None
    assert svc._send_failures == 1
    assert svc._last_send_error == "Forbidden: bot was blocked by the user"


def test_failures_accumulate_across_sends(sleeps):
    svc = _Service([Forbidden("blocked"), BadRequest("chat not found")])
    _run(svc)
    _run(svc)
    assert svc._send_failures == 2
    assert svc._last_send_error.startswith("BadRequest")


def test_a_delivered_alert_leaves_the_counter_alone(sleeps):
    """A retried-then-delivered alert is not a failure — the counter is
    for alerts that never arrived."""
    svc = _Service([RetryAfter(1), "ok"])
    assert _run(svc) == "ok"
    assert not hasattr(svc, "_send_failures")


def test_the_dropped_alert_logs_its_traceback(sleeps, caplog):
    """`log.error("...: %s", e)` alone loses the stack — and the stack is
    the whole diagnostic value when the exception type is a generic
    transport error."""
    svc = _Service([Forbidden("bot was blocked by the user")])
    with caplog.at_level(logging.ERROR, logger="app.telegram_bot"):
        _run(svc)
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a dropped alert must log at ERROR"
    assert errors[-1].exc_info is not None
