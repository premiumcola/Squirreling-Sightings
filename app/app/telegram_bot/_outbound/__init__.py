"""The outbound half of TelegramService — composition only.

This file was 922 lines with a 247-line `send_event_alert` inside it.
It is now the seam list: one module per concern, composed into the single
`OutboundMixin` that `service.py` has always imported.

  _send.py        the transport — send(), send_alert(), the markup
  _payload.py     upload payload + the one API call it feeds
  _retry.py       bounded retry around that call
  _gates.py       the cheap push predicates (suppress, rate limit, quiet)
  _best_frame.py  the strongest frame of a clip, boxes burnt on
  _event_alert.py the event push path: nine gates, then one message
  _jobs.py        daily report, highlight, watchdog + system notices

Nothing but composition and re-exports belongs here. `EventAlertResult`
is re-exported because it is the return type of the package's most
public method.
"""

from __future__ import annotations

from ._best_frame import BestFrameMixin
from ._event_alert import EventAlertMixin, EventAlertResult
from ._gates import GatesMixin
from ._jobs import JobsMixin
from ._send import SendMixin

__all__ = ["EventAlertResult", "OutboundMixin"]


class OutboundMixin(SendMixin, GatesMixin, BestFrameMixin, EventAlertMixin, JobsMixin):
    """Send pipeline: low-level send, alerts, scheduled-job bodies (daily/highlight/watchdog).

    Mixin for TelegramService. Methods access shared state via `self.*`
    (cfg, bot, store, runtimes, scheduler, etc.) which live on the
    concrete class.
    """
