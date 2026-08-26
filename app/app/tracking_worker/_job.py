"""The queue item and the sidecar path convention.

Kept apart from the worker so the enqueue side (``camera_runtime``,
``routes/tracking``) and the read side (``routes/detection_cloud``,
the Telegram best-frame picker) can name a sidecar without importing
the thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TrackingJob:
    event_id: str
    video_path: Path
    snapshot_path: Path | None
    camera_id: str


def tracks_path_for(video_path: Path) -> Path:
    """Conventional sidecar path: `<video>.tracks.json` next to the mp4."""
    return video_path.with_name(video_path.stem + ".tracks.json")


def safe_relpath(p: Path, root: Path) -> str:
    """``p`` relative to ``root`` as a posix string, or the absolute
    posix path when ``p`` lives outside ``root``."""
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()
