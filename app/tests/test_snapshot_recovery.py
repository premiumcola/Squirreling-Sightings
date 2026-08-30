"""A camera tile must come back on its own after the backend restarts.

The dead-id mark exists to stop a 404 storm after a camera rename: two
consecutive snapshot failures and the preview-refresh loop stops bumping
that id. It was only ever SET. The single reset lived in `loadAll()`, so
nothing short of a page reload cleared it.

A deploy makes every camera fail twice within half a second at 5 fps, so
all three were marked dead. The 3 s status poll then redrew the tiles,
each <img> loaded exactly ONE frame — and the refresh loop skipped them
from then on. Three pictures frozen at the second of the restart, still
captioned "Live · 15 fps", until F5.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_IMPORT = "const m = await import(JS + '/dashboard/snapshot-poll.js');"


def test_two_failures_still_mark_the_id_dead():
    """The rename protection must survive the fix."""
    out = _js(
        f"""
        {_IMPORT}
        const img = {{ dataset: {{}}, style: {{}}, closest: (sel) => (sel === '[data-camid]' ? {{ dataset: {{ camid: 'cam_a' }} }} : null) }};
        m._camImgRetry(img);
        m._camImgRetry(img);
        console.log(JSON.stringify(m._isSnapshotIdDead('cam_a')));
        """
    )
    assert out is True


def test_a_decoded_frame_revives_a_dead_id():
    """THE regression test — this edge did not exist."""
    out = _js(
        f"""
        {_IMPORT}
        const mk = () => ({{
          dataset: {{}}, style: {{}},
          classList: {{ add() {{}}, remove() {{}} }},
          previousElementSibling: null,
          naturalWidth: 1920, naturalHeight: 1080,
          closest: (sel) => (sel === '[data-camid]' ? {{ dataset: {{ camid: 'cam_a' }} }} : null),
        }});
        const img = mk();
        m._camImgRetry(img);
        m._camImgRetry(img);
        const deadBefore = m._isSnapshotIdDead('cam_a');
        m._cvImgLoaded(mk());
        console.log(JSON.stringify({{ deadBefore, deadAfter: m._isSnapshotIdDead('cam_a') }}));
        """
    )
    assert out["deadBefore"] is True
    assert out["deadAfter"] is False, "a camera that is answering again stays skipped forever"


def test_a_revived_image_is_shown_again():
    """The second failure also hides the element; reviving must undo that
    or the tile stays blank while the stream is fine."""
    out = _js(
        f"""
        {_IMPORT}
        const img = {{
          dataset: {{ snapRetry: '3' }}, style: {{ display: 'none' }},
          classList: {{ add() {{}}, remove() {{}} }},
          previousElementSibling: null,
          naturalWidth: 1920, naturalHeight: 1080,
          closest: (sel) => (sel === '[data-camid]' ? {{ dataset: {{ camid: 'cam_b' }} }} : null),
        }};
        m._cvImgLoaded(img);
        console.log(JSON.stringify({{ display: img.style.display, retry: img.dataset.snapRetry }}));
        """
    )
    assert out["display"] == ""
    assert out.get("retry") in (None, "")


def test_an_unrelated_camera_is_not_revived():
    out = _js(
        f"""
        {_IMPORT}
        const img = {{ dataset: {{}}, style: {{}}, closest: (sel) => (sel === '[data-camid]' ? {{ dataset: {{ camid: 'cam_x' }} }} : null) }};
        m._camImgRetry(img);
        m._camImgRetry(img);
        const other = {{
          dataset: {{}}, style: {{}},
          classList: {{ add() {{}}, remove() {{}} }},
          previousElementSibling: null,
          naturalWidth: 1, naturalHeight: 1,
          closest: (sel) => (sel === '[data-camid]' ? {{ dataset: {{ camid: 'cam_y' }} }} : null),
        }};
        m._cvImgLoaded(other);
        console.log(JSON.stringify(m._isSnapshotIdDead('cam_x')));
        """
    )
    assert out is True
