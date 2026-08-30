"""Behavioural tests for the Gewitter-Browser's frontend LOGIC.

`test_storms_archive.py` next door pins structure by reading source
text. That catches a module being deleted; it cannot catch a function
that computes the wrong number, and every defect this file covers was
of exactly that kind — a dot planted at the wrong sample, a `null`
threshold silently becoming 0, a float `===` that never matches.

So these run the real modules. There is no jsdom in this repo (and
adding a browser test stack for six pure functions would be the larger
sin), but node ships with the ES-module loader the app already targets,
and the modules under test are pure. A small DOM stub satisfies the
handful of top-level `window.x = …` bridges their import graph carries;
nothing here renders into a real document.

Skipped, not failed, when node is unavailable — this must never be the
reason a Python-only checkout cannot run its tests.
"""

from __future__ import annotations

import pytest

from ._node_js import JS_URI as _JS
from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


# ── A1 · the peak dot marks the metric's own WORST reading ─────────────


def test_series_peak_is_the_extreme_not_the_sample_at_t_zero():
    """The x axis is anchored on the record's `peak_at`, which the
    backend derives from thresholded fields only — wind gusts have no
    threshold and can never set it. Labelling the t=0 sample "the peak"
    of a gust curve is a straight lie on the chart."""
    out = _js(
        """
        const { seriesPeak } = await import(JS + '/weather/stats-chart/_multi.js');
        // A gust curve peaking 20 min AFTER the lightning peak at t=0.
        const points = [[-10, 30], [-5, 45], [0, 52], [10, 88], [20, 61]];
        console.log(JSON.stringify({
          top: seriesPeak(points, 'wind_gusts_10m'),
          empty: seriesPeak([], 'wind_gusts_10m'),
          allNull: seriesPeak([[0, null], [5, NaN]], 'wind_gusts_10m'),
        }));
        """
    )
    assert out["top"] == {"m": 10, "v": 88}
    assert out["empty"] is None
    assert out["allNull"] is None


def test_the_peak_dot_marks_the_thickest_fog_not_the_clearest_moment():
    """`visibility` is inverted — the backend stores its MINIMUM as the
    peak and the severity ratio is threshold ÷ value. The chart's dot
    was an unconditional argmax, so on a fog episode it landed on the
    24 km sample and skipped the 800 m one: it pointed at the clearest
    moment of the fog and called it the peak."""
    out = _js(
        """
        const { seriesPeak } = await import(JS + '/weather/stats-chart/_multi.js');
        const fog = [[-20, 24000], [-5, 6000], [0, 800], [15, 12000]];
        console.log(JSON.stringify({
          fog: seriesPeak(fog, 'visibility'),
          // The same samples read as a normal metric still argmax.
          asNormal: seriesPeak(fog, 'precipitation'),
        }));
        """
    )
    assert out["fog"] == {"m": 0, "v": 800}
    assert out["asNormal"] == {"m": -20, "v": 24000}


# ── A4 · the compare tooltip finds every episode ───────────────────────


def test_hover_lookup_tolerates_unaligned_polls():
    """Two storms weeks apart are not phase-locked, so their relative
    minute sets barely intersect. An `===` lookup showed one episode per
    tooltip — the one thing a compare view must not do."""
    out = _js(
        """
        const { nearestPoint } = await import(JS + '/weather/stats-chart/_multi.js');
        // Episode B's samples sit 2 minutes off episode A's grid.
        const b = [[-7, 3], [-2, 9], [3, 4]];
        console.log(JSON.stringify({
          near: nearestPoint(b, 0, 2.5),
          exact: nearestPoint(b, 3, 2.5),
          tooFar: nearestPoint(b, 30, 2.5),
          strictWouldMiss: b.some(([m]) => m === 0),
        }));
        """
    )
    assert out["strictWouldMiss"] is False, "the fixture must not be phase-aligned"
    assert out["near"] == [-2, 9]
    assert out["exact"] == [3, 4]
    assert out["tooFar"] is None


def test_hover_tolerance_is_measured_not_assumed():
    """The constant 2.5 was "half a poll" against a poll_interval the
    operator can change (settings/_consts.py, default 300 s). At 600 s
    every tooltip regressed to one episode. The tolerance is now half
    the widest MEASURED cadence, and the median is what keeps an outage
    hole from inflating it."""
    out = _js(
        """
        const { hoverTolerance, medianStep } =
          await import(JS + '/weather/stats-chart/_multi.js');
        const five = [[0, 1], [5, 1], [10, 1], [15, 1]];
        const ten = [[0, 1], [10, 1], [20, 1], [30, 1]];
        // 5-min cadence with one 40-min outage in the middle.
        const gappy = [[0, 1], [5, 1], [45, 1], [50, 1], [55, 1]];
        console.log(JSON.stringify({
          five: hoverTolerance([{ points: five }]),
          ten: hoverTolerance([{ points: ten }]),
          mixed: hoverTolerance([{ points: five }, { points: ten }]),
          gappyStep: medianStep(gappy),
          single: hoverTolerance([{ points: [[0, 1]] }]),
        }));
        """
    )
    assert out["five"] == 2.5
    assert out["ten"] == 5, "a 600 s poll must widen the tolerance, not break the tooltip"
    assert out["mixed"] == 5, "the widest cadence in the selection wins"
    assert out["gappyStep"] == 5, "the median ignores the outage; a mean would read 13.75"
    assert out["single"] == 2.5


def test_a_poll_gap_shows_a_dash_instead_of_dropping_the_episode():
    """`_record_sample` only runs after a SUCCESSFUL poll, so a failed
    API call, a coalesced job or a restart appends no row. Hovering into
    such a hole used to drop the episode's whole tooltip row, which
    reads as "this storm is not in the comparison"."""
    out = _js(
        """
        const { seriesReading } = await import(JS + '/weather/stats-chart/_multi.js');
        // 5-min cadence with a 40-min hole between -55 and -15.
        const pts = [[-60, 4], [-55, 5], [-15, 9], [-10, 7]];
        console.log(JSON.stringify({
          hit: seriesReading(pts, -14, 2.5),
          inGap: seriesReading(pts, -35, 2.5),
          beforeStart: seriesReading(pts, -200, 2.5) === undefined,
          afterEnd: seriesReading(pts, 200, 2.5) === undefined,
          noPoints: seriesReading([], 0, 2.5) === undefined,
        }));
        """
    )
    assert out["hit"] == 9
    assert out["inGap"] is None, "inside the episode's span a gap is a dash, not an absence"
    assert out["beforeStart"] is True
    assert out["afterEnd"] is True
    assert out["noPoints"] is True


# ── A2 / A3 · a missing threshold stays missing ────────────────────────


def test_a_null_threshold_never_becomes_zero():
    """`Number(null)` is 0 and `Number.isFinite(0)` is true, so the
    payload's `null` for wind gusts (no event) and visibility (fog is
    configured as vis_max_m) used to draw a "Schwelle" line along the
    axis floor and make every severity ratio infinite."""
    out = _js(
        """
        const { thresholdFor, severityRatio } = await import(JS + '/storms/_helpers.js');
        const thr = { lightning_potential: 1000, wind_gusts_10m: null, visibility: null };
        console.log(JSON.stringify({
          gusts: Number.isFinite(thresholdFor(thr, 'wind_gusts_10m')),
          visibility: Number.isFinite(thresholdFor(thr, 'visibility')),
          missing: Number.isFinite(thresholdFor(thr, 'snowfall')),
          real: thresholdFor(thr, 'lightning_potential'),
          ratioOnNull: severityRatio('wind_gusts_10m', 95, thresholdFor(thr, 'wind_gusts_10m')),
        }));
        """
    )
    assert out["gusts"] is False
    assert out["visibility"] is False
    assert out["missing"] is False
    assert out["real"] == 1000
    assert out["ratioOnNull"] == 0


def test_compare_draws_no_threshold_line_for_an_unthresholded_metric():
    out = _js(
        """
        const { metricThresholds } = await import(JS + '/storms/_compare.js');
        const eps = [{ id: 'a', thresholds: { precipitation: 5, wind_gusts_10m: null } }];
        console.log(JSON.stringify({
          gusts: metricThresholds(eps, 'wind_gusts_10m'),
          rain: metricThresholds(eps, 'precipitation'),
        }));
        """
    )
    assert out["gusts"] == []
    assert out["rain"] == [{"value": 5, "label": "Schwelle"}]


def test_episodes_with_different_thresholds_get_a_line_each():
    """Every record stamps the thresholds it was measured against, and
    the archive outlives the settings that produced it. Taking the FIRST
    episode's value and drawing it across four curves labels three of
    them with a threshold that was never theirs."""
    out = _js(
        """
        const { metricThresholds } = await import(JS + '/storms/_compare.js');
        const { slotsClear, slotAssign } = await import(JS + '/storms/_state.js');
        slotsClear();
        ['a', 'b', 'c'].forEach(slotAssign);
        const raised = [
          { id: 'a', thresholds: { lightning_potential: 1000 } },
          { id: 'b', thresholds: { lightning_potential: 2500 } },
          { id: 'c', thresholds: { lightning_potential: 1000 } },
        ];
        const agreed = raised.map((ep) => ({
          id: ep.id, thresholds: { lightning_potential: 1000 },
        }));
        console.log(JSON.stringify({
          differing: metricThresholds(raised, 'lightning_potential'),
          agreed: metricThresholds(agreed, 'lightning_potential'),
        }));
        """
    )
    # Two levels, each naming the slots it actually applies to.
    assert out["differing"] == [
        {"value": 1000, "label": "Schwelle 1·3"},
        {"value": 2500, "label": "Schwelle 2"},
    ]
    # One agreed level needs no slot list — the unqualified label is
    # true for every curve.
    assert out["agreed"] == [{"value": 1000, "label": "Schwelle"}]


def test_an_empty_archive_renders_nothing_and_hides_its_section():
    """The day-one empty state is gone.

    It existed to prove the detector was armed by naming its thresholds.
    That reasoning still holds, but the surface changed: storm episodes
    now render as ordinary cards inside the Wetter-Ereignisse feed, so
    #storms is a detail view rather than the archive's only entrance,
    and an empty panel at the foot of the weather section said only
    "there is nothing here". The operator struck it out and asked for it
    gone; the section now hides itself instead.
    """
    out = _js(
        """
        const { renderList } = await import(JS + '/storms/_list.js');
        const { stormsState } = await import(JS + '/storms/_state.js');
        stormsState.episodes = [];
        const attrs = [];
        globalThis.document.getElementById = () => ({
          setAttribute: (k, v) => attrs.push(['set', k, v]),
          removeAttribute: (k) => attrs.push(['remove', k]),
        });
        const host = { innerHTML: 'stale', classList: { toggle() {} } };
        renderList(host, () => {});
        console.log(JSON.stringify({ html: host.innerHTML, attrs }));
        """
    )
    assert out["html"] == "", "an empty archive still paints something"
    assert ["set", "hidden", ""] in [list(a) for a in out["attrs"]], "#storms was not hidden"


# ── B1 · the inverted metric ───────────────────────────────────────────


def test_visibility_severity_is_inverted():
    """Low visibility is the alarm, so its ratio is threshold ÷ value —
    mirroring the backend's sample_strength. Uninverted, 800 m of fog
    against a 1000 m ceiling scores 0.8 and never leads."""
    out = _js(
        """
        const { severityRatio, leadPeak } = await import(JS + '/storms/_helpers.js');
        const ep = { peaks: { visibility: 200, precipitation: 6 },
                     thresholds: { visibility: 1000, precipitation: 5 } };
        console.log(JSON.stringify({
          fog: severityRatio('visibility', 200, 1000),
          rain: severityRatio('precipitation', 6, 5),
          lead: leadPeak(ep).key,
        }));
        """
    )
    assert out["fog"] == 5
    assert out["rain"] == pytest.approx(1.2)
    assert out["lead"] == "visibility"


def test_the_table_bolds_the_worst_reading_not_the_largest_number():
    """`_row` did `let max = -Infinity; if (v > max)` and bolded the
    winner. On the "Sicht" row that marks the episode with the BEST
    visibility as the worst fog — the table stating the opposite of the
    truth, in bold."""
    out = _js(
        """
        const { compareTableHtml } = await import(JS + '/storms/_compare_table.js');
        const eps = [
          { id: 'thick', peaks: { visibility: 800, precipitation: 3 },
            duration_min: 40, intensity: 0.9 },
          { id: 'thin', peaks: { visibility: 24000, precipitation: 9 },
            duration_min: 20, intensity: 0.3 },
        ];
        const slots = { thick: 1, thin: 2 };
        const html = compareTableHtml(eps, (id) => slots[id]);
        // One <tr> per row; find the cells carrying is-max per row.
        const rows = html.split('<tr>').slice(2);
        const marked = (needle) => {
          const row = rows.find((r) => r.includes(needle)) || '';
          return row.split('<td').map((c) => c.startsWith(' class="is-max"'));
        };
        console.log(JSON.stringify({
          sicht: marked('>Sicht<').slice(1),
          regen: marked('Niederschlag').slice(1),
          dauer: marked('Dauer').slice(1),
        }));
        """
    )
    assert out["sicht"] == [True, False], "800 m of fog is the worse reading, not 24 000 m"
    assert out["regen"] == [False, True], "an ordinary metric still bolds the maximum"
    assert out["dauer"] == [True, False], "a non-metric row keeps higher-is-worse"


# ── B3 · the PATCH response is actually read ───────────────────────────


def test_patch_reconcile_reads_the_route_envelope():
    """The route answers {"ok": true, "episode": rec}. Testing `.id` on
    the envelope finds nothing, so every server-side normalisation was
    silently discarded."""
    out = _js(
        """
        const { patchedRecord } = await import(JS + '/storms/_detail_edit.js');
        console.log(JSON.stringify({
          envelope: patchedRecord({ ok: true, episode: { id: 'a', user_name: 'Hagelfront' } }),
          bare: patchedRecord({ id: 'a', user_name: 'Hagelfront' }),
          ackOnly: patchedRecord({ ok: true }),
          nothing: patchedRecord(null),
        }));
        """
    )
    assert out["envelope"]["user_name"] == "Hagelfront"
    assert out["bare"]["user_name"] == "Hagelfront"
    assert out["ackOnly"] is None
    assert out["nothing"] is None


# ── D1 · the sticky metric cannot strand the operator ──────────────────


def test_detail_drops_a_sticky_metric_this_episode_has_no_data_for():
    """Pick Schnee on a snow episode, open a thunderstorm: the chart was
    blank and the Schnee pill rendered both selected and disabled, so
    there was nothing to click out of."""
    out = _js(
        """
        const { detailMetric } = await import(JS + '/storms/_detail.js');
        const { stormsState } = await import(JS + '/storms/_state.js');
        const thunder = { peaks: { lightning_potential: 2400 },
                          thresholds: { lightning_potential: 1000 } };
        const snowy = { peaks: { snowfall: 2 }, thresholds: { snowfall: 0.5 } };
        stormsState.metric = 'snowfall';
        const onThunder = detailMetric(thunder);
        const onSnow = detailMetric(snowy);
        stormsState.metric = null;
        console.log(JSON.stringify({ onThunder, onSnow, blank: detailMetric({ peaks: {} }) }));
        """
    )
    assert out["onThunder"] == "lightning_potential"
    assert out["onSnow"] == "snowfall", "a metric the episode HAS must stay sticky"
    assert out["blank"] is None, "no data anywhere selects NOTHING, not a disabled pill"


def test_no_metric_can_be_selected_and_disabled_at_the_same_time():
    """The fallback's own docstring promised it never leaves a caller
    pointing at a metric whose pill is disabled while it renders as
    selected — and then returned STORM_METRICS[0], which does exactly
    that. Every metric that can be returned must have data."""
    out = _js(
        """
        const { firstMetricWithData, dominantMetric, metricHasData } =
          await import(JS + '/storms/_helpers.js');
        const blank = [{ peaks: {} }, { peaks: {} }];
        const some = [{ peaks: {} }, { peaks: { snowfall: 2 } }];
        const picked = firstMetricWithData(some);
        console.log(JSON.stringify({
          blank: firstMetricWithData(blank),
          blankDominant: dominantMetric(blank),
          picked,
          pickedHasData: metricHasData(some, picked),
        }));
        """
    )
    assert out["blank"] is None
    assert out["blankDominant"] is None
    assert out["picked"] == "snowfall"
    assert out["pickedHasData"] is True


# ── C2 · the slot palette is imported, not re-declared ─────────────────


def test_slot_colours_come_from_the_shared_palette():
    out = _js(
        """
        const { STORM_SLOT_COLORS, STORM_MAX_COMPARE } = await import(JS + '/storms/_state.js');
        const { LIVE_PALETTE } = await import(JS + '/core/track-color.js');
        console.log(JSON.stringify({
          slots: STORM_SLOT_COLORS,
          max: STORM_MAX_COMPARE,
          fromPalette: STORM_SLOT_COLORS.every((c) => LIVE_PALETTE.includes(c)),
          distinct: new Set(STORM_SLOT_COLORS).size,
        }));
        """
    )
    assert out["max"] == 4
    assert len(out["slots"]) == 4
    assert out["distinct"] == 4
    assert out["fromPalette"] is True


# ── C3 · one decimal banding, not two ──────────────────────────────────


def test_the_archive_and_the_weather_panel_agree_on_decimals():
    out = _js(
        """
        const { wsFieldDigits, _wsFmtVal, _wsStatsState } = await import(JS + '/weather/stats.js');
        const { fmtMetric } = await import(JS + '/storms/_helpers.js');
        _wsStatsState.data = { units: { precipitation: 'mm/h' } };
        console.log(JSON.stringify({
          panel: _wsFmtVal('precipitation', 12.4),
          archive: fmtMetric('precipitation', 12.4),
          gustDigits: wsFieldDigits('wind_gusts_10m'),
        }));
        """
    )
    # Same number of decimals on both sides — German comma in the
    # archive, decimal point in the panel, but never 12,4 vs 12.40.
    assert out["panel"] == "12.40 mm/h"
    assert out["archive"] == "12,40 mm/h"
    assert out["gustDigits"] == 0
