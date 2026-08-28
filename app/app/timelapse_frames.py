"""Which frames on disk belong to a given day.

Its own module rather than more weight on ``timelapse.py`` (711 lines
against a 500-line ceiling before this was added to it): discovery is a
filesystem question about two on-disk layouts, encoding is an ffmpeg
question, and only the encoder needs cv2.

Two layouts coexist:

* ``timelapse_frames/<cam>/<day>/`` — flat, written only by the legacy
  loop, which starts only when NO profile is enabled. The directory name
  IS the day.
* ``timelapse_frames/<cam>/<profile>/<window>/`` — what the profile
  loops write. The window key spans the period the profile is named
  after, so a weekly window holds seven days of frames in one directory
  whose names (``HHMMSS_ff.jpg``) say nothing about which day they are.
"""

from __future__ import annotations

from pathlib import Path

from .timelapse_windows import day_bounds, window_covers_day

# Profiles whose single window directory spans more than one calendar
# day, so "the frames of day X" has to be carved out by mtime.
_MULTI_DAY_PROFILES = ("weekly", "monthly", "quarterly", "yearly")


def _collect(window_dir: Path, bounds: tuple[float, float] | None) -> list[tuple[float, Path]]:
    """Every ``*.jpg`` in one window dir, optionally clipped to a day."""
    out: list[tuple[float, Path]] = []
    for p in window_dir.glob("*.jpg"):
        try:
            ts = p.stat().st_mtime
        except OSError:
            continue
        if bounds and not (bounds[0] <= ts < bounds[1]):
            continue
        out.append((ts, p))
    return out


def frames_for_day_stamped(base: Path, day: str) -> list[tuple[float, Path]]:
    """``(mtime, path)`` for every frame of ``day``, oldest first.

    Two things the plain prefix scan got wrong:

    * **Four of six profiles were invisible.** A window directory was
      matched with ``name.startswith(day)``, which only ever holds for
      ``daily`` and ``custom`` — ``2026-W35``, ``2026-08``, ``2026-Q3``
      and ``2026`` never start with an ISO date. The calendar profiles
      therefore made /api/camera/<id>/timelapse and /rolling answer
      ``no_frames``. :func:`window_covers_day` recomputes the profile's
      own key for the day instead, which is right for all six.

    * **The order was per-directory, not chronological.** Sorting by
      ``(parent.name, name)`` concatenated the sets, so a camera with
      daily *and* custom enabled produced an MP4 that played the day and
      then replayed the last custom window. mtime is the one ordering
      comparable across window directories.

    A multi-day window's frames are additionally intersected with the
    day's bounds — otherwise "build the timelapse for 2026-08-28" would
    hand the encoder a whole year.

    Stamps are returned rather than dropped so callers that need the
    mtime again (the rolling endpoint's cutoff) don't re-``stat``
    every candidate.
    """
    base = Path(base)
    if not base.is_dir():
        return []
    bounds = day_bounds(day)
    out: list[tuple[float, Path]] = []
    # Legacy flat layout — the directory name IS the day, so every frame
    # in it belongs to the day by construction.
    flat = base / day
    if flat.is_dir():
        out.extend(_collect(flat, None))
    for profile_dir in base.iterdir():
        if not profile_dir.is_dir() or profile_dir.name == day:
            continue
        # Windows narrower than a day (daily, custom) already ARE the
        # day; only multi-day calendar windows need the mtime clip.
        clip = bounds if profile_dir.name in _MULTI_DAY_PROFILES else None
        for window_dir in profile_dir.iterdir():
            if window_dir.is_dir() and window_covers_day(profile_dir.name, window_dir.name, day):
                out.extend(_collect(window_dir, clip))
    out.sort(key=lambda t: (t[0], t[1].name))
    return out
