"""Wetter-Ereignisse: the unified feed (sightings + recaps + Gewitter-
episodes) rendered inline in one grid.

Recap and episode cards used to live in weather/sightings.js directly;
they moved into weather/_feed.js as pure, DOM-free functions (they build
HTML strings the same way the sighting card builder already does) both
to keep _renderWeatherGrid under the JS function-line ceiling and
because that made them independently testable without a jsdom harness.
See test_storms_archive.py::test_mobile_dock_is_untouched for why the
in-feed episode card is now the archive's mobile discovery path — it
replaced the standalone "Gewitter-Archiv →" jump-chip.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


def test_the_unified_feed_sorts_newest_first_across_all_three_kinds():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const sightings = [{ id: 's1', started_at: '2026-08-01T10:00:00Z' }];
        const recaps = [{ id: 'r1', built_at: '2026-08-15T00:00:00Z' }];
        const episodes = [{ id: 'e1', started_at: '2026-08-30T12:00:00Z' }];
        const merged = feed.unifiedFeedItems(sightings, recaps, episodes);
        console.log(JSON.stringify({ order: merged.map((m) => m.kind) }));
        """
    )
    assert out["order"] == ["episode", "recap", "sighting"]


def test_a_sighting_keeps_its_absolute_index_regardless_of_feed_position():
    """The lightbox's prev/next walks state.weather.itemsFiltered by this
    same absolute index — the unified sort must never renumber it."""
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const sightings = [
          { id: 's1', started_at: '2026-08-01T10:00:00Z' },
          { id: 's2', started_at: '2026-08-20T10:00:00Z' },
        ];
        const merged = feed.unifiedFeedItems(sightings, [], []);
        console.log(JSON.stringify(merged.map((m) => ({ id: m.data.id, idx: m.idx }))));
        """
    )
    by_id = {row["id"]: row["idx"] for row in out}
    assert by_id == {"s1": 0, "s2": 1}


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
