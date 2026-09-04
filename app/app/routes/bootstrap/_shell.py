"""The app shell: index page, media files, service worker, shell version."""

from __future__ import annotations

from pathlib import Path

from flask import jsonify, render_template, send_from_directory

from ... import app_state
from ._blueprint import bp


@bp.get('/')
def index():
    return render_template('index.html')


@bp.get('/media/<path:subpath>')
def media_file(subpath):
    return send_from_directory(app_state.storage_root, subpath)


@bp.get('/sw.js')
def service_worker():
    """Serve the service worker from the app root so its scope covers
    the entire site. max_age=0 stops the browser from caching the SW
    itself — otherwise updates land 24h late."""
    # parents[3] — this file sits at app/app/routes/bootstrap/_shell.py,
    # so four levels up is the `app/` root that holds `web/static`. It
    # was parents[2] while this lived in routes/bootstrap.py; the count
    # tracks the file's depth, not the target.
    web_static = Path(__file__).resolve().parents[3] / "web" / "static"
    return send_from_directory(
        str(web_static),
        "sw.js",
        mimetype="application/javascript",
        max_age=0,
    )


@bp.get('/version.json')
def app_version():
    """The shell version the service worker derives its cache name from.

    Hashes the compiled ``app.css`` AND every file under ``static/js``
    (see ``lifecycle.shell_hash``). The css-only version of this claimed
    to be "a faithful proxy for the entire front-end shell" and was not:
    a JavaScript-only deploy left the hash untouched, so the SW kept its
    old cache and the browser kept the old modules.
    """
    from ...lifecycle import shell_hash

    return jsonify({"shell_hash": shell_hash()})
