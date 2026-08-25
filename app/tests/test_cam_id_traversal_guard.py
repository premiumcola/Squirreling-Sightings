"""Regression guard for the cam_id path-traversal check.

``routes/_helpers.safe_cam_id`` was written for this job but never
adopted — every route took ``cam_id`` straight from the URL into a
``storage_root / cam_id`` join. The guard now lives in
``routes.__init__._reject_traversal_cam_ids`` and runs as a
``before_request`` hook so it covers every blueprint at once.

These tests exercise the predicate directly against a Flask request
context rather than booting the real app, which would construct camera
runtimes and a Telegram poller.
"""

from __future__ import annotations

import pytest

from app.routes import _reject_traversal_cam_ids

flask = pytest.importorskip("flask")


def _run_guard(view_args):
    """Invoke the hook inside a request context with the given view args.

    Returns True when the request was allowed, False when it 404'd.
    """
    app = flask.Flask(__name__)
    with app.test_request_context("/"):
        flask.request.view_args = view_args
        try:
            _reject_traversal_cam_ids()
        except Exception as exc:  # werkzeug NotFound
            if getattr(exc, "code", None) == 404:
                return False
            raise
    return True


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        "../etc",
        "foo/../../bar",
        "foo/bar",
        "foo\\bar",
        "cam\x00id",
    ],
)
def test_traversal_shapes_are_rejected(bad):
    assert _run_guard({"cam_id": bad}) is False


@pytest.mark.parametrize(
    "good",
    [
        "reolink_cx810_werkstatt_172",
        "reolink_rlc811a_squirreltownnutbar_183",
        "unknown_unknown_unknown_unknown",
        "a",
        # No length cap: build_camera_id() does not truncate, so a long
        # camera name must still resolve. This is why the guard checks
        # traversal shapes rather than safe_cam_id's 64-char grammar.
        "reolink_" + "x" * 90 + "_181",
    ],
)
def test_legitimate_ids_pass(good):
    assert _run_guard({"cam_id": good}) is True


def test_absent_cam_id_is_ignored():
    assert _run_guard({}) is True
    assert _run_guard(None) is True


def test_non_string_cam_id_is_ignored():
    # Flask converters can hand back an int for `<int:...>` routes; the
    # guard must not blow up on a non-str value.
    assert _run_guard({"cam_id": 42}) is True
