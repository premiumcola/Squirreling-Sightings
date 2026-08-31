"""The Mediathek-Verwaltung panel's data — one source, server-side.

The two maintenance panels hydrated from two different places and one of
them did not work: ``weather/maintenance.js`` painted its sliders from
``/api/bootstrap``'s ``data.app.weather``, but ``bootstrap_state()``
returns five keys and ``app`` is not one of them, so every weather slider
showed the Jinja literal forever — a saved 30 came back as the shipped
90 on the next reload. The Mediathek slider hydrated from
``state.config.storage`` inside the cam-edit hydrate path, a third route
through a fourth object.

Now the panel is rendered with its values already in it. The context
processor below injects :func:`~retention_catalog.panel_groups` into
every template render, so the markup Flask sends already carries the
resolved numbers and toggle states — no fetch, no paint-then-repaint,
and nothing to forget when a category is added.

No accompanying ``GET`` endpoint: nothing would call it. The panel is
complete when Flask sends the page, and the save path
(``POST /api/settings/app``) already echoes success — an endpoint whose
only caller is a future refactor is the same dead surface as
``POST /api/media/cleanup``'s button that no template renders.

Its own module rather than a few more lines in ``routes/bootstrap.py``
(711 lines against a 500-line ceiling) or ``routes/weather.py`` (746, and
an extraction in flight).
"""

from __future__ import annotations

from flask import Blueprint

from ..retention_catalog import panel_groups

bp = Blueprint("retention_panel", __name__)


@bp.app_context_processor
def inject_retention_groups() -> dict:
    """``retention_groups`` for ``partials/_maintenance_panel.html``.

    Registered app-wide from this blueprint so the partial does not
    depend on which view rendered it. The template guards with
    ``retention_groups or []`` anyway, so a render in a context where
    this blueprint is not registered degrades to "no retention block"
    instead of raising.
    """
    return {"retention_groups": panel_groups()}
