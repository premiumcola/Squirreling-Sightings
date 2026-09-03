"""Filename fragments for a built timelapse.

Pure string helpers, used only by ``TimelapseBuilder.make_output_name``.
"""

from __future__ import annotations


def _period_label(period_s: int) -> str:
    """Convert period seconds to a short human-readable label for filenames."""
    if period_s <= 0:
        return "custom"
    if period_s < 3600:
        mins = round(period_s / 60)
        return f"{mins}min" if mins > 0 else f"{period_s}s"
    if period_s < 86400:
        hours = round(period_s / 3600)
        return f"{hours}h"
    if period_s < 604800:
        return "daily"
    if period_s < 2592000:
        return "weekly"
    return "monthly"


def _duration_label(target_s: int) -> str:
    """Convert target duration seconds to a short label for filenames."""
    if target_s < 60:
        return f"{target_s}sec"
    mins = target_s // 60
    return f"{mins}min"
