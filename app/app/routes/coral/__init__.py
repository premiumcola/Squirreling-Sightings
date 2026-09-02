"""Coral test panel + model selection.

Migrated from server.py during R01.5. R04 decomposed the 421-line
`api_coral_test_batch` into a route shell plus per-mode pipeline
helpers in `_coral_pipeline.py`. The detector / classifier classes
are still constructed per request because the test panel intentionally
mirrors what each model would say *with override flags* (force-enabled
second-stage classifiers), and reusing a long-lived instance would lose
that override semantic.

Split from a single 629-line module into this package to get back under
the 500-line file ceiling. Pure move: every route kept its rule, method,
endpoint name and response shape, and the blueprint is still registered
once as `coral.bp`. The concerns are:

    _test_single · /api/coral/test
    _test_batch  · /api/coral/test-images, /api/coral/test-batch
    _models      · /api/coral/models, /api/coral/models/select

with `_stages` (the per-classifier stage runners behind the
single-frame test) underneath them. The batch pipeline helpers stay
where they were, in the sibling `.._coral_pipeline`.
"""

from __future__ import annotations

from ._blueprint import bp

# Imported for the registration side effect: each module decorates its
# handlers onto `bp` at import time, so `bp` is only fully populated once
# all three have been imported. Listed in the order the routes stood in
# the pre-split module — Werkzeug sorts the map itself, so the order is
# documentation, not behaviour.
from . import _test_single, _test_batch, _models  # noqa: F401

__all__ = ["bp"]
