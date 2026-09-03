"""Module-level constants shared across the timelapse package.

The logger name is pinned to ``app.timelapse`` — the name the module
carried before it became a package — so existing log filters and the
``[timelapse]`` tag convention keep matching.
"""

from __future__ import annotations

import logging

log = logging.getLogger("app.timelapse")
