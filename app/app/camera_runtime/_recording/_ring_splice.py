"""Splicing REAL stream-copied footage (see ``_ring_buffer.py``) onto a
finished clip — the counterpart to ``_preroll.py``'s stills-based splice,
split into its own file once ``_preroll.py`` crossed CLAUDE.md's 500-line
ceiling. ``_preroll.py::_splice_preroll_onto_clip`` calls
``self._splice_ring_preroll_onto_clip`` first and only falls back to its
own stills-based method when this returns 0.0 — the two mixins are always
composed together (see ``_recording/__init__.py``), so that call resolves
at runtime regardless of which file defines which method.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

from .._consts import log
from ._preroll import preroll_audio_wanted


class RingPrerollSpliceMixin:
    """Mixin for RecordingMixin, alongside MotionPrerollMixin — see this
    module's own docstring for why the two are split but always paired."""

    def _splice_ring_preroll_onto_clip(
        self,
        vid_path: Path,
        ring_segments: list[Path],
        event_id: str,
        day_dir: Path,
    ) -> float:
        """The real-footage counterpart to ``_splice_preroll_onto_clip``'s
        stills-based splice. Two concat passes, both reusing
        ``_concat_segments`` (the same stream-copy-then-verify-then-
        reencode-fallback machinery the stills path already trusts, just
        generalised from exactly-2 inputs to a list):

          1. join the ring segments into one pre-roll file — they share
             one continuous source (see ``_ring_buffer.py``), so this
             concat is between homogeneous material and should always
             succeed as a plain stream copy;
          2. splice THAT onto ``vid_path``, same as the stills path.

        The ring buffer runs ``-an`` (video only, see ``_ring_buffer.py``
        — cheaper to keep 24/7), so an audio-recording camera's pre-roll
        here has a different stream layout than the main clip and the
        step-2 stream copy will legitimately fail — ``_concat_segments``
        already falls back to a full re-encode for exactly that case, so
        nothing extra is needed here for it.

        Returns the ACHIEVED duration, measured from the joined pre-roll
        file itself — never assumed, never the requested window, since a
        short buffer (camera just (re)connected) or GOP overshoot can
        both make the real number differ from what was asked for.
        """
        if not ring_segments:
            return 0.0
        preroll_path = day_dir / f"{event_id}.ringpre.mp4"
        spliced_path = day_dir / f"{event_id}.ringspliced.mp4"
        try:
            if len(ring_segments) == 1:
                shutil.copyfile(ring_segments[0], preroll_path)
                joined = preroll_path.exists() and preroll_path.stat().st_size >= 1024
            else:
                joined = self._concat_segments(list(ring_segments), preroll_path, want_audio=False)
            if not joined:
                return 0.0
            achieved_pre_s = self._probe_duration_s(preroll_path)
            if achieved_pre_s <= 0:
                return 0.0
            want_audio = preroll_audio_wanted(self.cfg, vid_path)
            if not self._concat_segments(
                [preroll_path, vid_path], spliced_path, want_audio=want_audio
            ):
                return 0.0
            if not self._is_playable(spliced_path):
                log.warning(
                    "[%s] ring-spliced clip %s unreadable — keeping trigger-only clip",
                    self.camera_id,
                    event_id,
                )
                return 0.0
            spliced_path.replace(vid_path)
            return round(achieved_pre_s, 2)
        except Exception as e:
            log.warning("[%s] ring pre-roll splice error for %s: %s", self.camera_id, event_id, e)
            return 0.0
        finally:
            with contextlib.suppress(Exception):
                preroll_path.unlink(missing_ok=True)
            with contextlib.suppress(Exception):
                if spliced_path.exists():
                    spliced_path.unlink()
