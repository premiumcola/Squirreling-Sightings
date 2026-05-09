"""Ground-truth regression tests for is_valid_frame.

Each JPEG under fixtures/frame_validation/ is real camera output
from a Squirrel-Town night capture, hand-classified by the user as
either a corruption case the validator MUST reject (corrupt/) or a
genuine scene the validator MUST accept (clean/). Future tuning
runs against this set to make sure nothing regresses silently.

Calibration policy: thresholds in frame_helpers.py may move ONLY
when this suite stays green for every fixture. If you can't get a
clean/corrupt separation, surface which fixture is the holdout
rather than relaxing the test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import pytest

# Make `app` package importable.
_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.frame_helpers import is_valid_frame  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "frame_validation"
CORRUPT_DIR = FIXTURES / "corrupt"
CLEAN_DIR = FIXTURES / "clean"


def _load_corrupt():
    if not CORRUPT_DIR.exists():
        return []
    return sorted(CORRUPT_DIR.glob("*.jpg"))


def _load_clean():
    if not CLEAN_DIR.exists():
        return []
    return sorted(CLEAN_DIR.glob("*.jpg"))


@pytest.mark.parametrize("path", _load_corrupt(),
                         ids=lambda p: p.name)
def test_corrupt_frame_rejected(path):
    """The corruption fixtures must be rejected by is_valid_frame.
    Reason head is informational — what matters is `ok=False`."""
    img = cv2.imread(str(path))
    assert img is not None, f"could not read {path}"
    ok, reason = is_valid_frame(img)
    assert not ok, (
        f"{path.name} expected REJECT but passed validation. "
        f"reason={reason!r}"
    )


@pytest.mark.parametrize("path", _load_clean(),
                         ids=lambda p: p.name)
def test_clean_frame_accepted(path):
    """The clean fixtures (genuine night IR scenes, including the
    00120 yellow-lamp false-positive trap) must pass validation."""
    img = cv2.imread(str(path))
    assert img is not None, f"could not read {path}"
    ok, reason = is_valid_frame(img)
    assert ok, (
        f"{path.name} expected PASS but rejected by validation. "
        f"reason={reason!r}"
    )
