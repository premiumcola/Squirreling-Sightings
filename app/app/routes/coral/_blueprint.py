"""The coral blueprint object, alone in its own module.

Every concern module in this package registers its routes on ``bp``.
Keeping the object here rather than in ``__init__`` is what stops an
import cycle: ``__init__`` imports the concern modules for their
registration side effect, so a concern module reaching back into
``__init__`` for ``bp`` would close the loop.
"""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("coral", __name__)
