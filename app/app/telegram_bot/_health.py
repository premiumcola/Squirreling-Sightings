"""Health snapshot of the service's two threads.

Split out of `_lifecycle.py` (which owns start/stop and was already past
the 500-line budget): lifecycle *changes* thread state, this module only
*reports* it. The reporting side grew its own concern with C8 — the
status used to describe the polling thread only, so a dead send loop was
invisible to /api/telegram/status, to the cam-edit health strip and to
the watchdog heartbeat alike.
"""

from __future__ import annotations

import time


class HealthMixin:
    """Read-only thread health for TelegramService. Mixin — reads shared
    state via `self.*` (see service.__init__ for the attribute list),
    mutates nothing."""

    def send_loop_alive(self) -> bool:
        """True while the dedicated send-loop thread (``tg-send-loop``,
        started in LifecycleMixin.start) is running. send() hands every
        alert to that thread via run_coroutine_threadsafe; if it has
        died, the coroutines are queued onto a loop nobody runs, the
        alert silently no-ops, and polling — and therefore the state
        field below — still reads "active"."""
        t = getattr(self, "_loop_thread", None)
        return bool(t is not None and t.is_alive())

    def get_polling_status(self) -> dict:
        """Snapshot of the polling state for /api/telegram/status.

        States:
          off                  — service disabled or polling not running
          starting             — thread alive, getUpdates not yet confirmed
          active               — getUpdates running, no recent conflict
          conflict             — Telegram returned Conflict in the last 30s
          conflict_quarantine  — 3 Conflicts in 60 s tripped the kill-switch;
                                 polling stays down until a manual restart
          stale                — stop() left an orphan polling thread; start() is
                                 refusing to spawn a second one until restart

        Every state carries ``send_loop_alive`` next to it: the state
        field describes the polling thread alone, so send-loop death has
        no state of its own to be spotted in.
        """
        status = self._poll_state()
        status["send_loop_alive"] = self.send_loop_alive()
        return status

    def _poll_state(self) -> dict:
        """The polling thread's state alone — vocabulary as documented on
        get_polling_status. Kept separate so the public snapshot can
        decorate every branch with send-loop health in one place."""
        if not self.enabled:
            return {"state": "off", "since_seconds": 0, "enabled": False}
        now = time.time()
        if getattr(self, "_conflict_quarantine", False):
            ts = self._last_conflict_ts or now
            return {
                "state": "conflict_quarantine",
                "since_seconds": int(now - ts),
                "enabled": True,
            }
        stale = getattr(self, "_stale_poll_thread", None)
        if stale is not None and stale.is_alive():
            since = getattr(self, "_stale_since", None) or now
            return {
                "state": "stale",
                "since_seconds": int(now - since),
                "enabled": True,
            }
        if not (self._poll_thread and self._poll_thread.is_alive()):
            return {"state": "off", "since_seconds": 0, "enabled": True}
        if self._last_conflict_ts and (now - self._last_conflict_ts) < 30:
            return {
                "state": "conflict",
                "since_seconds": int(now - self._last_conflict_ts),
                "enabled": True,
            }
        if self._polling_active_since:
            return {
                "state": "active",
                "since_seconds": int(now - self._polling_active_since),
                "enabled": True,
            }
        return {"state": "starting", "since_seconds": 0, "enabled": True}
