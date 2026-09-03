"""An /api/ route must fail as JSON, never as an HTML error page.

The app registered no error handler at all, so Flask's defaults applied:
a raised exception became a text/html 500 page and `abort(404)` — which
`routes.__init__._reject_traversal_cam_ids` issues on every request — an
HTML 404 page.

The frontend half of that is already known: `apiGet` returns `null` when
the body will not parse as JSON instead of throwing. So a route that
blew up did not surface as an error anywhere. The caller got `null`,
rendered an empty panel, and the only trace was in `docker logs` — if
the reader knew to look. Same shape as the swallowed exceptions
elsewhere in this sweep: a real failure wearing the costume of an empty
result.

Scoped to `/api/` on purpose. The dashboard's own pages are HTML and
should keep Flask's HTML error pages; it is only the JSON surface whose
contract is broken by an HTML body.
"""

from __future__ import annotations

import sys
from pathlib import Path

import flask
import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.routes import register_blueprints  # noqa: E402


@pytest.fixture
def app():
    app = flask.Flask(__name__)
    register_blueprints(app)
    # Flask re-raises through the test client unless this is off, which
    # would bypass the very handler under test.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/api/_boom")
    def _boom():
        raise RuntimeError("detector exploded")

    @app.get("/_page_boom")
    def _page_boom():
        raise RuntimeError("not an api route")

    return app


def test_an_unhandled_exception_answers_json(app):
    r = app.test_client().get("/api/_boom")
    assert r.status_code == 500
    assert r.is_json, f"got {r.content_type}: {r.get_data(as_text=True)[:200]}"
    assert r.get_json()["ok"] is False


def test_an_unknown_api_path_answers_json(app):
    r = app.test_client().get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.is_json, f"got {r.content_type}: {r.get_data(as_text=True)[:200]}"
    assert r.get_json()["ok"] is False


def test_the_traversal_guards_404_is_json(app):
    """`_reject_traversal_cam_ids` aborts before any handler runs, so its
    404 came back as HTML on a path the frontend polls as JSON."""
    r = app.test_client().get("/api/camera/..%2f..%2fetc/media")
    assert r.status_code == 404
    assert r.is_json, f"got {r.content_type}: {r.get_data(as_text=True)[:200]}"


def test_a_non_api_page_keeps_its_html_error(app):
    """Only the JSON surface changes. The dashboard's pages are HTML and
    an HTML error page is the right answer there."""
    r = app.test_client().get("/_page_boom")
    assert r.status_code == 500
    assert not r.is_json


def test_the_error_body_does_not_leak_the_exception_text(app):
    """The message can carry a path or a URL with credentials in it. The
    detail belongs in the log, not in an unauthenticated response."""
    r = app.test_client().get("/api/_boom")
    assert "detector exploded" not in r.get_data(as_text=True)


def test_the_failure_is_logged_with_its_traceback(app, caplog):
    """Answering politely must not make the failure quieter than the
    HTML page was."""
    with caplog.at_level("ERROR"):
        app.test_client().get("/api/_boom")
    assert any(r.exc_info for r in caplog.records), "the traceback was dropped"
