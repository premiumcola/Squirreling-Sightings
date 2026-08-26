"""HYG-2 · a path upload must not leak the handle the retry loop opens.

`prepare_input` hands `dispatch_send` a live ``open(path, "rb")`` for a
path input, and nobody ever closed it. Since C6 the payload is rebuilt
once per attempt — deliberately, a drained handle would upload zero
bytes on the retry — so a network blip followed by a flood-control 429
left *three* open handles behind, two of them unreachable. The affected
callers are the hot ones: the snapshot fallback in the event alert, the
highlight job and the timelapse push all pass a filesystem path.

Ownership is the rule under test: what this module opens, this module
closes; a stream the caller built stays the caller's.

Stub-only — the module-level ``open`` in `_payload` is swapped for a
counting fake, so no real file is ever opened. No bot, no token, no
network, no event loop beyond asyncio.run.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from telegram.error import Forbidden, NetworkError, RetryAfter

from app.telegram_bot import TelegramService
from app.telegram_bot._outbound import _payload

JPEG = b"\xff\xd8jpegbytes"


class _Handle(io.BytesIO):
    """A stand-in for the file object ``open`` returns, counting closes."""

    def __init__(self, tracker: _OpenTracker, data: bytes):
        super().__init__(data)
        self._tracker = tracker

    def close(self):
        if not self.closed:
            self._tracker.closed += 1
        super().close()


class _OpenTracker:
    """Counting replacement for the builtin ``open`` inside _payload."""

    def __init__(self, data: bytes = JPEG):
        self.data = data
        self.opened = 0
        self.closed = 0
        self.paths: list[str] = []

    def __call__(self, path, mode="rb", *args, **kwargs):
        self.opened += 1
        self.paths.append(str(path))
        return _Handle(self, self.data)

    @property
    def leaked(self) -> int:
        return self.opened - self.closed


class _FakeBot:
    """Replays a scripted list of outcomes and drains every upload stream
    the way httpx would, so a reused handle shows up as empty bytes."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[str] = []
        self.payloads: list[bytes] = []
        self.streams: list = []

    async def _next(self, kind: str, **kwargs):
        self.calls.append(kind)
        for value in kwargs.values():
            if hasattr(value, "read"):
                self.streams.append(value)
                self.payloads.append(value.read())
        outcome = self.script.pop(0) if self.script else "sent"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def send_message(self, **kwargs):
        return await self._next("message", **kwargs)

    async def send_photo(self, **kwargs):
        return await self._next("photo", **kwargs)

    async def send_video(self, **kwargs):
        return await self._next("video", **kwargs)

    async def send_document(self, **kwargs):
        return await self._next("document", **kwargs)


class _Service(TelegramService):
    """Real service class with hand-built state — __init__ is skipped so
    no telegram.Bot is constructed and nothing can reach the network."""

    def __init__(self, script):
        self.enabled = True
        self.chat_id = "4711"
        self.bot = _FakeBot(script)
        self._last_push_ts = None


@pytest.fixture
def opener(monkeypatch):
    """Shadow the builtin ``open`` in _payload's own namespace — module
    globals win over builtins, so nothing else in the process is
    affected and no real descriptor is ever handed out."""
    tracker = _OpenTracker()
    monkeypatch.setattr(_payload, "open", tracker, raising=False)
    return tracker


@pytest.fixture
def sleeps(monkeypatch):
    """Swallow the retry backoff so the test doesn't wait it out."""
    recorded: list[float] = []

    async def _fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return recorded


def test_path_photo_handle_is_closed_after_a_successful_send(opener):
    svc = _Service(["ok"])
    assert asyncio.run(svc.send_alert("cap", photo="/tmp/snap.jpg", parse_mode=None)) == "ok"
    assert opener.opened == 1
    assert opener.leaked == 0


def test_every_retry_attempt_closes_its_own_handle(opener, sleeps):
    """The regression this closes. Three attempts, three fresh handles —
    and three closes. Before the fix all three stayed open, two of them
    with no reference left to close them by."""
    svc = _Service([NetworkError("blip"), RetryAfter(1), "ok"])
    assert asyncio.run(svc.send_alert("cap", photo="/tmp/snap.jpg", parse_mode=None)) == "ok"
    assert opener.opened == 3
    assert opener.leaked == 0


def test_handle_is_closed_when_the_send_finally_fails(opener):
    """A revoked token / blocked chat drops the alert — it must not also
    drop the descriptor."""
    svc = _Service([Forbidden("bot was blocked by the user")])
    assert asyncio.run(svc.send_alert("cap", photo="/tmp/snap.jpg", parse_mode=None)) is None
    assert opener.opened == 1
    assert opener.leaked == 0


def test_video_path_handle_is_closed(opener):
    svc = _Service(["ok"])
    assert asyncio.run(svc.send_alert("cap", video="/tmp/clip.mp4", parse_mode=None)) == "ok"
    assert svc.bot.calls == ["video"]
    assert opener.leaked == 0


def test_each_attempt_uploads_the_full_file(opener, sleeps):
    """Closing must not turn into closing too early: every attempt still
    sees the whole payload, which is the property C6 bought."""
    svc = _Service([RetryAfter(1), "ok"])
    asyncio.run(svc.send_alert("cap", photo="/tmp/snap.jpg", parse_mode=None))
    assert svc.bot.payloads == [JPEG, JPEG]


def test_caller_owned_stream_is_left_open(opener):
    """prepare_input passes a ready-made stream straight through — that
    one belongs to the caller, and closing it would break re-use."""
    stream = io.BytesIO(JPEG)
    svc = _Service(["ok"])
    asyncio.run(svc.send_alert("cap", photo=stream, parse_mode=None))
    assert opener.opened == 0
    assert stream.closed is False


def test_bytes_payload_stream_is_released(opener):
    """Bytes get a BytesIO built for them, so that one is ours to close."""
    svc = _Service(["ok"])
    asyncio.run(svc.send_alert("cap", photo=JPEG, parse_mode=None))
    assert svc.bot.payloads == [JPEG]
    assert opener.opened == 0
    assert svc.bot.streams[0].closed is True
