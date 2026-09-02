"""Bootstrap, config, system, discover, wizard, and import/export.

Migrated from server.py during R01.3. Verbatim route bodies; state
references rewritten to flow through `app_state`. The wizard endpoint
calls `_auto_detect_device_info` from `_camera_helpers` because both
this blueprint and the cameras blueprint touch the same auto-detect
flow.

Split from a single 721-line module into this package to get back under
the 500-line file ceiling. Pure move: every route kept its rule, method,
endpoint name and response shape, and the blueprint is still registered
once as `bootstrap.bp`. The concerns are:

    _shell      · /, /media/<path>, /sw.js, /version.json
    _config     · /api/bootstrap, /api/config
    _discovery  · /api/discover[/stream], /api/discover/test-credentials
    _system     · status_payload, /api/status, /api/system
    _setup      · /api/wizard/complete, /api/settings/{export,import}

with `_probes` (credential probes), `_helpers` (pure helpers) and
`_consts` (the German detail strings) underneath them.
"""

from __future__ import annotations

from ._blueprint import bp

# Imported for the registration side effect: each module decorates its
# handlers onto `bp` at import time, so `bp` is only fully populated once
# all five have been imported. Listed in the order the routes stood in
# the pre-split module — Werkzeug sorts the map itself, so the order is
# documentation, not behaviour.
from . import _shell, _config, _discovery, _system, _setup  # noqa: F401
from ._system import status_payload

__all__ = ["bp", "status_payload"]
