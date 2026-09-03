"""telegram_bot._formatting — view builders, render helpers, anchor mechanics.

Split into focused mixins per responsibility; FormattingMixin re-exports
them as a single mixin so service.py keeps inheriting one base class.
The import path ``from ._formatting import FormattingMixin`` keeps
working byte-for-byte.
"""

from ._anchor import _AnchorMixin
from ._cam import _CamMixin
from ._erkennungen import _ErkennungenMixin
from ._root import _RootMixin
from ._status_cams import _StatusCamsMixin
from ._status_system import _StatusSystemMixin
from ._wetter import _WetterMixin


class FormattingMixin(
    _AnchorMixin,
    _RootMixin,
    # `_status.py` was one 518-line mixin over the file ceiling. Split
    # along the seam its two views already had: the per-camera blocks
    # (`/status` rows, disk usage, icons) and the system-wide screens
    # that read them. Composed here rather than behind a shim so there
    # is one list of mixins, not two.
    _StatusCamsMixin,
    _StatusSystemMixin,
    _ErkennungenMixin,
    _WetterMixin,
    _CamMixin,
):
    """Aggregate mixin re-exported for service.py. Composition order
    matters only for diamond resolution; current code has no diamonds
    (no two mixins define the same method), so the order is
    alphabetical-ish and stable."""

    pass


__all__ = ["FormattingMixin"]
