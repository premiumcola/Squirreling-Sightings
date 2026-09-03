"""Timelapse video building.

Was a single 771-line module; split at its own seams to get back under
CLAUDE.md's 500-line file and 80-line function ceilings. The import site
is unchanged — ``from .timelapse import TimelapseBuilder`` still works,
and ``TimelapseBuilder`` still carries every method the build tests
monkeypatch (``_write_video_ffmpeg``, ``_write_video_opencv``,
``_ffprobe_validate``), now inherited from the mixins.

  _consts.py    — the shared logger
  _labels.py    — filename fragments
  _geometry.py  — output box + aspect-preserving fit
  _scan.py      — pass 1: validate, deduplicate, tally frame sizes
  _encode.py    — pass 2: ffmpeg, with the OpenCV fallback
  _probe.py     — pass 3: ffprobe validation + rejection sidecar
  _builder.py   — TimelapseBuilder, composing the above
"""

from __future__ import annotations

from ._builder import TimelapseBuilder

__all__ = ["TimelapseBuilder"]
