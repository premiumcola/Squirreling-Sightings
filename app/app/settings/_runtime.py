"""The ``runtime`` section of settings.json.

Scratch state the app keeps across restarts — last-seen timestamps,
alert indices, per-camera counters. Touched from Telegram callback
threads, scheduler jobs and the camera threads, so every read-modify-
write goes through ``_runtime_lock``; callers never reach into
``data["runtime"]`` directly.
"""

from __future__ import annotations

from copy import deepcopy


class RuntimeMixin:
    """Thread-safe accessors for ``data["runtime"]``."""

    def runtime_get(self, key: str, default=None):
        with self._runtime_lock:
            return deepcopy(self.data.setdefault("runtime", {}).get(key, default))

    def runtime_set(self, key: str, value):
        with self._runtime_lock:
            self.data.setdefault("runtime", {})[key] = value
            self.save()

    def runtime_set_subkey(self, key: str, subkey: str, value):
        """Set runtime[key][subkey] = value. Creates the dict if absent."""
        with self._runtime_lock:
            sec = self.data.setdefault("runtime", {}).setdefault(key, {})
            if not isinstance(sec, dict):
                sec = {}
                self.data["runtime"][key] = sec
            sec[subkey] = value
            self.save()

    def runtime_get_subkey(self, key: str, subkey: str, default=None):
        with self._runtime_lock:
            sec = self.data.setdefault("runtime", {}).get(key) or {}
            if not isinstance(sec, dict):
                return default
            return deepcopy(sec.get(subkey, default))

    def runtime_set_subkey_lru(self, key: str, subkey: str, value, cap: int):
        """LRU-bounded write to runtime[key][subkey].

        The cap is what keeps settings.json from growing one entry per
        event forever. Every bounded runtime map goes through this one
        method — `alert_index` and `event_feedback` differ only in their
        cap, and two hand-rolled eviction loops is one more than the
        number that can stay correct.
        """
        with self._runtime_lock:
            idx = self.data.setdefault("runtime", {}).setdefault(key, {})
            if not isinstance(idx, dict):
                idx = {}
                self.data["runtime"][key] = idx
            idx[subkey] = value
            while len(idx) > cap:
                # Python 3.7+ dicts preserve insertion order
                idx.pop(next(iter(idx)))
            self.save()

    def runtime_alert_index_set(self, eid: str, payload: dict, cap: int = 200):
        """LRU-bounded write to runtime.alert_index. Cap protects against
        unbounded growth — at cap, the oldest insertion is evicted."""
        self.runtime_set_subkey_lru("alert_index", eid, payload, cap)
