"""Sizes and names for the debug bundle. One place, so the route, the
writer and the tests cannot drift apart."""

from __future__ import annotations

import re

#: Below the storage root, so ``/media/debug/<name>`` serves it without
#: a second static route.
BUNDLE_DIR = "debug"

#: A bundle is a few hundred KB; ten of them is a bounded directory an
#: operator can still read, and the oldest is never the interesting one.
MAX_BUNDLES = 10

#: The tail the operator actually needs — a boot, a couple of reconnects
#: and the event that prompted the bundle. The whole file would be 5 MB.
LOG_TAIL_LINES = 3000

#: Most recent event JSONs, newest first, across all cameras.
EVENT_COUNT = 50

NAME_FMT = "bundle-%Y%m%d-%H%M%S.zip"
BUNDLE_NAME_RE = re.compile(r"^bundle-\d{8}-\d{6}\.zip$")

#: Arc-names inside the ZIP. Fixed, because ``bundle.md`` documents them
#: and a reader unpacks the archive by hand.
ARC_SUMMARY = "bundle.md"
ARC_LOG = "log/app.log"
ARC_CONFIG = "config/effective-config.json"
ARC_STATUS = "status.json"
ARC_TELEMETRY = "telemetry.json"
ARC_EVENTS = "events"
ARC_TUNING = "tuning"
