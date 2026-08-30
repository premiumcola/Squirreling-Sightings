"""The cheap push predicates: suppression, rate limit, night, quiet hours.

Split out of `_outbound/__init__.py` (far past the 500-line file budget)
as a concern of its own: these five decide nothing but yes/no over
runtime state, they send nothing, and the ordered gate chain in
`_event_alert.py` is only one of their callers.

Kept as a mixin rather than free functions because every one of them
reads shared service state — the settings store, the push config, the
per-camera rate cache — which lives on the concrete class.
"""

from __future__ import annotations

import time

from ...telegram_helpers import is_night, is_quiet_now


def _epoch(read) -> float:
    """A runtime "_until" value as a float epoch; 0.0 when unset or junk.

    A malformed mute must read as "no mute": failing the other way would
    silence the whole system on a single bad settings write.
    """
    try:
        return float(read() or 0)
    except Exception:  # noqa: BLE001 — a diagnostic read must not raise
        return 0.0


class GatesMixin:
    """Push gates for TelegramService. Mixin — reads shared state via
    `self.*` (see service.__init__ for the attribute list)."""

    def mute_state(self, cam_id: str) -> tuple[str | None, float]:
        """``(reason, until_epoch)`` for the two mutes — global first.

        Both honour the same "_until" epoch contract: 0 / past = no mute,
        future = active. ``reason`` is ``global_mute`` / ``cam_mute`` /
        None, matching ``EventAlertResult.blocked_by``.

        Public and deliberately LOG-FREE. The Simulieren panel's decision
        trace needs the same answer the push path acts on — a mute is the
        most common cause of "I get no notifications" and the panel used
        to deny it existed — but a diagnostic read must not leave a
        "[tg] skip:" line behind for an alert nobody tried to send.
        ``_mute_reason`` wraps this with production's logging.
        """
        if not self.settings_store:
            return None, 0.0
        now = time.time()
        global_until = _epoch(lambda: self.settings_store.runtime_get("global_mute_until"))
        if global_until and now < global_until:
            return "global_mute", global_until
        cam_until = _epoch(
            lambda: self.settings_store.runtime_get_subkey("cam_mute_until", cam_id, 0)
        )
        if cam_until and now < cam_until:
            return "cam_mute", cam_until
        return None, 0.0

    def _is_suppressed(self, cam_id: str, label: str) -> bool:
        key = f"{cam_id}|{label}"
        suppress = self.settings_store.runtime_get("suppress") if self.settings_store else None
        if not isinstance(suppress, dict):
            return False
        until = suppress.get(key, 0) or 0
        return time.time() < float(until)

    def _is_rate_limited(self, cam_id: str) -> bool:
        rl = float(self.push_cfg.get("rate_limit_seconds", 30) or 0)
        if rl <= 0:
            return False
        with self._rate_lock:
            last = self._rate_cache.get(cam_id, 0.0)
            return (time.time() - last) < rl

    def _record_rate_limit(self, cam_id: str):
        with self._rate_lock:
            self._rate_cache[cam_id] = time.time()
            # LRU-bound the cache so a long list of camera ids can't grow forever.
            while len(self._rate_cache) > self._RATE_CACHE_MAX:
                self._rate_cache.pop(next(iter(self._rate_cache)))

    def _is_night_for_camera(self, cam_id: str | None) -> bool:
        return is_night(self.push_cfg.get("night_alert") or {})

    def _is_quiet_now(self) -> bool:
        return is_quiet_now(self.push_cfg.get("quiet_hours") or {})
