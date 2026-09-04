"""weather/stats.js's zoom orchestration — onWeatherChartRangeSelect /
resetWeatherChartZoom actually flip the shared weather/_zoom.js state
they're supposed to drive.

Runs the real modules under node (see _node_js.py); the generic DOM
stub tolerates the render side-effects (proven already by
test_weather_stats_selection.py) without actually exercising them —
what this file pins is the STATE change, which the stub can't fake.
"""

from __future__ import annotations

import pytest

import re
from pathlib import Path

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

#: The frontend tree these source-text checks read.
_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js"


def _code(src: str) -> str:
    """JavaScript with its comments removed.

    These checks scan for words like `since` and `until` — and the code
    that removed them explains itself using exactly those words. Reading
    the raw text makes the documentation fail the test, which happened
    on the first run.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in src.splitlines())


pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


def test_range_select_activates_the_shared_zoom_state():
    out = _js(
        """
        const stats = await import(JS + '/weather/stats.js');
        const zoom = await import(JS + '/weather/_zoom.js');
        stats.onWeatherChartRangeSelect('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        console.log(JSON.stringify({
          active: zoom.isZoomActive(),
          range: zoom.getZoomRange(),
        }));
        """
    )
    assert out["active"] is True
    assert out["range"] == {"start": "2026-08-29T14:00:00", "end": "2026-08-29T18:00:00"}


def test_reset_clears_the_shared_zoom_state():
    out = _js(
        """
        const stats = await import(JS + '/weather/stats.js');
        const zoom = await import(JS + '/weather/_zoom.js');
        stats.onWeatherChartRangeSelect('2026-08-29T14:00:00', '2026-08-29T18:00:00');
        stats.resetWeatherChartZoom();
        console.log(JSON.stringify({ active: zoom.isZoomActive() }));
        """
    )
    assert out["active"] is False


def test_the_chart_zoom_does_not_reach_the_library_at_all():
    """Der Wettergraph filtert die Mediathek nicht mehr.

    Er tat es: eine im Graphen gezogene Spanne setzte `since`/`until` in
    die Abfrage des Rasters. Die beiden stehen in verschiedenen
    Abschnitten der Seite, also zoomte der Betreiber unten, scrollte
    hoch und fand „Keine Einträge im gewählten Zeitraum" — ohne dass
    irgendetwas auf dem Bildschirm den Grund nannte.

    „der Zeitraum von dem Wettergrafen darf nicht die Mediathek
    bestimmen, also lös da die Verbindung."

    Diese Datei hielt vorher die Brücke fest. Sie hält jetzt fest, dass
    es keine gibt — eine Bequemlichkeit, die stillschweigend die
    Mediathek leert, ist schlechter als gar keine.
    """
    filt = _code((_JS / "library" / "_filter-state.js").read_text(encoding="utf-8"))
    body = filt[filt.index("export function libraryQueryParams") :]
    body = body[: body.index("\n}")]
    assert "getZoomRange" not in body, "das Raster liest wieder den Zoom des Graphen"
    assert "since" not in body and "until" not in body


def test_the_library_keeps_its_own_filters():
    """Der Schnitt darf NUR den Zoom entfernen."""
    filt = _code((_JS / "library" / "_filter-state.js").read_text(encoding="utf-8"))
    body = filt[filt.index("export function libraryQueryParams") :]
    for own in ("camera_ids", "labels", "categories"):
        assert own in body, f"{own} ist mit weggefallen"


def test_the_chart_no_longer_reloads_the_grid():
    """Ohne den Filter wäre ein Neuladen des Rasters nur noch ein
    Flackern ohne Wirkung — die drei Aufrufe und ihr Helfer sind weg."""
    stats = _code((_JS / "weather" / "stats.js").read_text(encoding="utf-8"))
    assert "_reloadLibraryKeepingChartAnchored" not in stats
    assert "reloadLibraryPage" not in stats, "der Graph greift wieder ins Raster"


def test_no_dead_import_survived_the_cut():
    """withScrollAnchor war nur für diesen Helfer da. Git-Historie ist
    das Archiv (CLAUDE.md) — Leichen bleiben nicht im Quelltext."""
    stats = _code((_JS / "weather" / "stats.js").read_text(encoding="utf-8"))
    assert "withScrollAnchor" not in stats
