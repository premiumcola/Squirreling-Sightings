"""C6 · bounded retry around a single outbound Telegram call.

send_alert used to wrap the whole API call in one `except Exception`
that logged and returned None, and no caller checks the Future that
send() hands back. So a flood-control 429 during a burst of detections,
or a two-second network blip, dropped that alert for good — silently.

One retry per transient error class:

  RetryAfter (HTTP 429)   → sleep min(retry_after, RETRY_AFTER_CAP_S), once
  NetworkError / TimedOut → sleep NETWORK_BACKOFF_S, once

Deliberately one, not a loop: a genuinely broken token, a wrong chat_id
or an oversized upload must fail fast instead of hammering the API. The
two classes count separately, so the worst case is two extra attempts.

BadRequest is a NetworkError subclass in python-telegram-bot but is
never transient (malformed payload, unknown chat) — it is re-raised
untouched rather than retried. Everything else propagates to
send_alert's handler, which keeps logging and giving up.

Threading: send() dispatches send_alert onto the dedicated send-loop
(`tg-send-loop`, started in _lifecycle.start), never onto the polling
loop — so the sleeps below cannot stall getUpdates. They do delay the
alerts queued behind this one on that same loop, which is the intended
trade: late beats lost.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from .._consts import log

# Telegram's retry_after can be minutes long during heavy flood control.
# Capped so one throttled alert can't park the send loop indefinitely.
RETRY_AFTER_CAP_S = 15.0
NETWORK_BACKOFF_S = 2.0


async def send_with_retry(attempt: Callable[[], Awaitable[Any]]) -> Any:
    """Await ``attempt()``, retrying once per transient error class.

    ``attempt`` is a zero-arg coroutine *factory*, not a coroutine: every
    try must rebuild its own upload payload. A BytesIO or file handle
    consumed by the failed request would upload zero bytes on the retry.
    """
    retried_flood = False
    retried_network = False
    while True:
        try:
            return await attempt()
        except RetryAfter as e:
            if retried_flood:
                raise
            retried_flood = True
            delay = min(float(getattr(e, "retry_after", 0) or 0), RETRY_AFTER_CAP_S)
            log.warning("[tg] flood control — one retry in %.1fs (%s)", delay, e)
            await asyncio.sleep(delay)
        except BadRequest:
            raise
        except (NetworkError, TimedOut) as e:
            if retried_network:
                raise
            retried_network = True
            log.warning("[tg] network error — one retry in %.1fs (%s)", NETWORK_BACKOFF_S, e)
            await asyncio.sleep(NETWORK_BACKOFF_S)
