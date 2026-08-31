"""Wetter-Ereignisse card builders (sightings/recaps/episodes/manual
events) in weather/_feed.js — pure, DOM-free string builders, each
independently testable without a jsdom harness.

They used to feed weather/sightings.js's own `_renderWeatherGrid`; that
grid was retired in Stage 6 of the Mediathek + Wetter-Ereignisse merge
(the merged `/api/library` grid, `library/_dispatch.js`, dispatches to
these same builders via small per-kind adapters instead — see
`test_library_dispatch.py`/`test_library_adapters.py` if those exist,
or the library/_tests/ node suite). What is pinned here is unchanged:
each builder's own markup contract. See
test_storms_archive.py::test_mobile_dock_is_untouched for why the
in-feed episode card is the archive's mobile discovery path — it
replaced the standalone "Gewitter-Archiv →" jump-chip.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


def test_recap_card_carries_its_own_index_not_the_sighting_lightbox_attribute():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.recapCardHTML({ id: 'r9', period_label: 'August' }, 3);
        console.log(JSON.stringify({
          hasRecapIdx: html.includes('data-recap-idx="3"'),
          hasSightingIdx: html.includes(' data-idx='),
        }));
        """
    )
    assert out["hasRecapIdx"] is True
    assert (
        out["hasSightingIdx"] is False
    ), "a recap card must not carry the sighting lightbox's data-idx"


def test_episode_card_carries_its_id_and_footage_count():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.episodeCardHTML({
          id: 'ep7', started_at: '2026-08-10T18:00:00Z',
          duration_min: 42, footage_count: 3, auto_class: 'thunder',
        });
        console.log(JSON.stringify({
          hasEpId: html.includes('data-ep-id="ep7"'),
          hasFootage: html.includes('3 Aufnahmen'),
        }));
        """
    )
    assert out["hasEpId"] is True
    assert out["hasFootage"] is True


def test_episode_card_omits_the_footage_chip_when_there_is_none():
    """A footage_count of 0/undefined must render no chip at all — the
    same "absent, not zero" rule storms/_list.js's own row uses."""
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.episodeCardHTML({
          id: 'ep8', started_at: '2026-08-10T18:00:00Z', duration_min: 5,
        });
        console.log(JSON.stringify({ hasFootage: html.includes('Aufnahmen') }));
        """
    )
    assert out["hasFootage"] is False


# ── Episode card: character badge + sparkline ───────────────────────────


def test_episode_card_shows_the_character_icon_and_german_label():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.episodeCardHTML({
          id: 'ep9', started_at: '2026-08-10T18:00:00Z', duration_min: 30,
          auto_class: 'thunder', character: 'rain_led_thunder',
        });
        console.log(JSON.stringify({
          hasBadge: html.includes('ws-ep-character'),
          hasLabel: html.includes('Vorlauf-Regen'),
        }));
        """
    )
    assert out["hasBadge"] is True
    assert out["hasLabel"] is True


def test_episode_card_omits_the_character_badge_without_a_character():
    """A bare fixture (or a record fetched before the field existed on
    the wire) must render no character badge at all — see
    `characterMeta`'s own fallback test for the "unbekannt" case."""
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.episodeCardHTML({
          id: 'ep10', started_at: '2026-08-10T18:00:00Z', duration_min: 5,
        });
        console.log(JSON.stringify({ hasBadge: html.includes('ws-ep-character') }));
        """
    )
    assert out["hasBadge"] is False


def test_episode_card_renders_a_sparkline_when_a_curve_preview_is_present():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.episodeCardHTML({
          id: 'ep11', started_at: '2026-08-10T18:00:00Z', duration_min: 20,
          curve_preview: { field: 'precipitation', values: [1, 4, 9, 3, 1] },
        });
        console.log(JSON.stringify({ hasSpark: html.includes('ws-ep-spark') }));
        """
    )
    assert out["hasSpark"] is True


def test_episode_card_omits_the_sparkline_without_a_curve_preview():
    """The list view's own "legacy record" edge case — no preview on
    the wire at all — must render nothing, not a broken/empty chart."""
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.episodeCardHTML({
          id: 'ep12', started_at: '2026-08-10T18:00:00Z', duration_min: 5,
        });
        console.log(JSON.stringify({ hasSpark: html.includes('ws-ep-spark') }));
        """
    )
    assert out["hasSpark"] is False


# ── episodeSparklineSvg — the pure curve-preview renderer ───────────────


def test_sparkline_renders_a_path_for_many_samples():
    out = _js(
        """
        const { episodeSparklineSvg } = await import(JS + '/weather/_episode-sparkline.js');
        const svg = episodeSparklineSvg({ field: 'precipitation', values: [1, 5, 12, 4, 0, 2] });
        console.log(JSON.stringify({ hasSvg: svg.includes('<svg'), hasPath: svg.includes('<path') }));
        """
    )
    assert out["hasSvg"] is True
    assert out["hasPath"] is True


def test_sparkline_is_empty_for_a_single_sample():
    """buildLinePath needs at least two real points to draw anything —
    a one-sample episode must render nothing, not throw."""
    out = _js(
        """
        const { episodeSparklineSvg } = await import(JS + '/weather/_episode-sparkline.js');
        const svg = episodeSparklineSvg({ field: 'precipitation', values: [4] });
        console.log(JSON.stringify({ svg }));
        """
    )
    assert out["svg"] == ""


def test_sparkline_is_empty_for_an_empty_or_missing_preview():
    out = _js(
        """
        const { episodeSparklineSvg } = await import(JS + '/weather/_episode-sparkline.js');
        console.log(JSON.stringify({
          empty: episodeSparklineSvg({ field: 'precipitation', values: [] }),
          missing: episodeSparklineSvg(null),
          noField: episodeSparklineSvg({ field: null, values: [1, 2, 3] }),
        }));
        """
    )
    assert out["empty"] == ""
    assert out["missing"] == ""
    assert out["noField"] == ""


def test_open_storm_episode_navigates_the_archive_hash_route():
    """Must match storms/index.js's own #/gewitter/<id> route exactly —
    a mismatch here is a silent dead click, not an error."""
    out = _js(
        """
        globalThis.location = { hash: '' };
        const feed = await import(JS + '/weather/_feed.js');
        feed.openStormEpisode('ep-42');
        console.log(JSON.stringify({ hash: globalThis.location.hash }));
        """
    )
    assert out["hash"] == "#/gewitter/ep-42"


def test_open_storm_episode_is_a_noop_without_an_id():
    out = _js(
        """
        globalThis.location = { hash: '#weather' };
        const feed = await import(JS + '/weather/_feed.js');
        feed.openStormEpisode(null);
        console.log(JSON.stringify({ hash: globalThis.location.hash }));
        """
    )
    assert out["hash"] == "#weather"


# ── manual events (drag-zoom "als Ereignis speichern") ──────────────────


def test_manual_event_card_carries_its_id_not_a_recap_or_sighting_attribute():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.manualEventCardHTML({
          id: 'manual_1', name: 'Gewitter mit Blitzen', category: 'thunder',
          range_start: '2026-08-29T14:00:00', range_end: '2026-08-29T18:00:00',
          curves: ['precipitation', 'lightning_potential'],
        });
        console.log(JSON.stringify({
          hasManualId: html.includes('data-manual-id="manual_1"'),
          hasRecapIdx: html.includes('data-recap-idx'),
          hasSightingIdx: html.includes(' data-idx='),
          hasName: html.includes('Gewitter mit Blitzen'),
          hasCurveCount: html.includes('2 Kurven'),
        }));
        """
    )
    assert out["hasManualId"] is True
    assert out["hasRecapIdx"] is False
    assert out["hasSightingIdx"] is False
    assert out["hasName"] is True
    assert out["hasCurveCount"] is True


def test_manual_event_card_falls_back_to_the_category_label_without_a_name():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.manualEventCardHTML({
          id: 'manual_2', category: 'snow',
          range_start: '2026-08-29T14:00:00', range_end: '2026-08-29T18:00:00',
          curves: ['snowfall'],
        });
        console.log(JSON.stringify({ hasSchnee: html.includes('Schnee') }));
        """
    )
    assert out["hasSchnee"] is True


def test_manual_event_card_shows_one_badge_per_category():
    """An event is genuinely more than one thing (a thunderstorm that
    also brings heavy rain) — the card must show every category, not
    just the first, and label the slot for screen readers."""
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.manualEventCardHTML({
          id: 'manual_3', name: 'Gewitter mit Starkregen',
          categories: ['thunder', 'heavy_rain'],
          range_start: '2026-08-29T14:00:00', range_end: '2026-08-29T18:00:00',
          curves: ['precipitation', 'lightning_potential'],
        });
        console.log(JSON.stringify({
          badges: (html.match(/class="ws-manual-cat"/g) || []).length,
          n: html.includes('data-n="2"'),
          label: html.includes('aria-label="Gewitter · Starkregen"'),
          thunderColour: html.includes('--cb:#7faec9'),
          rainColour: html.includes('--cb:#5a8aa8'),
        }));
        """
    )
    assert out["badges"] == 2
    assert out["n"] is True
    assert out["label"] is True
    assert out["thunderColour"] is True
    assert out["rainColour"] is True


def test_manual_event_card_still_renders_an_old_single_category_record():
    """Records saved before multi-select carry only `category`. They must
    keep rendering — one badge, its own colour — with no migration."""
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.manualEventCardHTML({
          id: 'manual_old', name: 'Altes Gewitter', category: 'thunder',
          range_start: '2026-08-29T14:00:00', range_end: '2026-08-29T18:00:00',
          curves: ['lightning_potential'],
        });
        console.log(JSON.stringify({
          badges: (html.match(/class="ws-manual-cat"/g) || []).length,
          n: html.includes('data-n="1"'),
          label: html.includes('aria-label="Gewitter"'),
          hasName: html.includes('Altes Gewitter'),
          hasManualId: html.includes('data-manual-id="manual_old"'),
        }));
        """
    )
    assert out["badges"] == 1
    assert out["n"] is True
    assert out["label"] is True
    assert out["hasName"] is True
    assert out["hasManualId"] is True


def test_manual_event_categories_normalises_both_record_shapes():
    """The JS twin of weather_service/_manual_events.py::
    manual_event_categories — one helper, both shapes, no branching on a
    record's age scattered across the card builder and the modal."""
    out = _js(
        """
        const cats = await import(JS + '/weather/_manual-event-cats.js');
        console.log(JSON.stringify({
          old: cats.manualEventCategories({ category: 'fog' }),
          neu: cats.manualEventCategories({ categories: ['fog', 'snow'] }),
          both: cats.manualEventCategories({ categories: ['snow', 'fog'], category: 'snow' }),
          dedup: cats.manualEventCategories({ categories: ['fog', 'fog', 7, ''] }),
          none: cats.manualEventCategories({}),
          max: cats.MANUAL_CATEGORIES_MAX,
        }));
        """
    )
    assert out["old"] == ["fog"]
    assert out["neu"] == ["fog", "snow"]
    assert out["both"] == ["snow", "fog"]
    assert out["dedup"] == ["fog"]
    assert out["none"] == []
    assert out["max"] == 3


def test_sighting_card_html_moved_here_still_builds_a_card():
    """sightingCardHTML moved from sightings.js into this module when
    sightings.js crossed the JS line ceiling — pin that the export
    survived the move with its original behaviour."""
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.sightingCardHTML(
          { id: 's9', event_type: 'fog', started_at: '2026-08-29T08:00:00', score: 0.8 },
          3,
          true,
        );
        console.log(JSON.stringify({ hasIdx: html.includes('data-idx="3"') }));
        """
    )
    assert out["hasIdx"] is True
