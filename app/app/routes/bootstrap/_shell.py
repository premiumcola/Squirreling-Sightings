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
    """Tiny shell-version endpoint consumed by the service worker on
    install. We hash the compiled app.css — its content already shifts
    on every commit that touches a CSS partial (css_builder.py
    concatenates them) so it's a faithful proxy for the entire
    front-end shell. The SW uses this value to derive its cache
    name; bumping the hash invalidates the PWA shell cache without
    the user having to re-add the app from their home screen."""
    # _file_hash lives on the jinja env — pull it through the
    # current Flask app so this stays in lock-step with the
    # ?v= cache-bust query the templates already use.
    from flask import current_app

    hasher = current_app.jinja_env.globals.get("static_v")
    shell_hash = hasher("app.css") if callable(hasher) else "v1"
    return jsonify({"shell_hash": shell_hash})
