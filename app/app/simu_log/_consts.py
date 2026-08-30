"""Layout and quotas for the SIMU run log.

Written on every "Debug kopieren" tap, so it accumulates at the rate the
operator debugs — which is precisely the shape of directory this project
has already had to clean up once elsewhere. Two quotas, whichever bites
first, enforced on every write.
"""

from __future__ import annotations

import re

#: Under ``storage/``. ``storage/logs/`` is already gitignored, so a run
#: cannot reach the public repo by being written to the wrong tree; the
#: ``simu`` sub-directory keeps it out of the ``*.log`` tail that
#: ``/api/logs`` serves.
LOG_DIRNAME = "logs/simu"

#: Runs kept per camera. A run is ~20–60 kB (40 log lines plus the
#: decision trace), so 20 per camera is well under a megabyte each — and
#: 20 taps is far more history than a debugging session ever revisits.
MAX_RUNS_PER_CAMERA = 20

#: …and an age cap, because a run describes threshold state. Past a
#: month the numbers in it describe a configuration that has moved on,
#: which makes the file misleading rather than merely stale.
MAX_AGE_DAYS = 30

#: The browser-owned block is the only part of a stored run that does not
#: come from this process. Cap it: an unbounded client write is how a
#: log directory becomes a disk-space incident.
MAX_FRONTEND_BYTES = 8192

#: ``YYYYMMDD-HHMMSS-ffffff.json`` — the same id shape ``storage`` uses
#: for events, so a run sorts chronologically by name alone. Also the
#: traversal gate on the fetch route: nothing that fails this pattern is
#: ever joined onto a path.
RUN_NAME_RE = re.compile(r"^\d{8}-\d{6}-\d{6}\.json$")
