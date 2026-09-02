"""``TrackerState`` — the per-run mutable container the per-frame
helpers thread through.

Split out of the package root so the growth-bounding logic that keeps
the live runtime from leaking (see ``closed_cap``) sits next to the
list it bounds rather than three hundred lines away from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrackerState:
    """Per-run mutable state shared across the per-frame helpers. The
    live runtime uses ONE instance per camera (lives the session); the
    post-clip worker creates ONE instance per clip.

    ``closed`` grows for as long as the instance lives, and the live
    runtime's instance lives for the whole camera session — potentially
    days. Its only reader (``_adopt.try_reidentify``) ever looks at
    ``closed[-32:]``, so an unbounded list was pure growth with nothing
    reading the tail: ~630 B/track x a handful of tracks/minute adds up
    to roughly 1 GB/month per camera, the one genuine memory leak this
    project's resource audit found. ``closed_cap`` bounds it for callers
    that want that — set it, and every close_track/close_tracks call
    trims the list back down. The post-clip worker leaves it ``None``:
    it genuinely needs every track from the one clip it is processing,
    not a 32-entry tail of it.
    """

    active: list = field(default_factory=list)  # list[Track]
    closed: list = field(default_factory=list)  # list[Track]
    samples_emitted: int = 0
    best_top: dict | None = None
    closed_cap: int | None = None

    def _trim_closed(self) -> None:
        if self.closed_cap is not None and len(self.closed) > self.closed_cap:
            del self.closed[: -self.closed_cap]

    def close_track(self, track) -> None:
        """Append one track to ``closed`` and enforce the cap."""
        self.closed.append(track)
        self._trim_closed()

    def close_tracks(self, tracks) -> None:
        """Extend ``closed`` with several tracks and enforce the cap."""
        self.closed.extend(tracks)
        self._trim_closed()
