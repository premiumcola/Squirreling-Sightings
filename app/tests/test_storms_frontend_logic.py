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

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = (Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js").as_uri()

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

# Enough of a DOM for the import graph: several modules publish a
# `window.*` bridge at module scope and a couple touch `document` on
# import. The element proxy answers any method with another proxy, and
# remembers assigned properties so `host.innerHTML` can be read back.
_STUB = """
const el = () =>
  new Proxy(
    { style: {}, dataset: {},
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false } },
    { get(t, k) { if (k in t) return t[k];
                  if (k === 'children' || k === 'childNodes') return [];
                  return typeof k === 'string' ? () => el() : undefined; },
      set(t, k, v) { t[k] = v; return true; } },
  );
globalThis.window = { addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }) };
globalThis.document = { addEventListener() {}, querySelector: () => el(),
  querySelectorAll: () => [], getElementById: () => el(), createElement: () => el(),
  createElementNS: () => el(), body: el(), documentElement: el() };
globalThis.IntersectionObserver = class { observe() {} disconnect() {} };
globalThis.history = { replaceState() {} };
globalThis.fetch = () => Promise.reject(new Error('no network in tests'));
"""


def _js(body: str):
    """Run `body` with the storms modules importable. Returns its JSON."""
    script = "{}\nconst JS = '{}';\n{}\n".format(_STUB, _JS, body)
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, "node failed:\n{}".format(proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── A1 · the peak dot marks the metric's own maximum ───────────────────


def test_series_max_is_the_argmax_not_the_sample_at_t_zero():
    """The x axis is anchored on the record's `peak_at`, which the
    backend derives from thresholded fields only — wind gusts have no
    threshold and can never set it. Labelling the t=0 sample "the peak"
    of a gust curve is a straight lie on the chart."""
    out = _js(
        """
        const { seriesMax } = await import(JS + '/weather/stats-chart/_multi.js');
        // A gust curve peaking 20 min AFTER the lightning peak at t=0.
        const points = [[-10, 30], [-5, 45], [0, 52], [10, 88], [20, 61]];
        console.log(JSON.stringify({
          top: seriesMax(points),
          empty: seriesMax([]),
          allNull: seriesMax([[0, null], [5, NaN]]),
        }));
        """
    )
    assert out["top"] == {"m": 10, "v": 88}
    assert out["empty"] is None
    assert out["allNull"] is None


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
        const { metricThreshold } = await import(JS + '/storms/_compare.js');
        const eps = [{ thresholds: { precipitation: 5, wind_gusts_10m: null } }];
        console.log(JSON.stringify({
          gusts: Number.isFinite(metricThreshold(eps, 'wind_gusts_10m')),
          rain: metricThreshold(eps, 'precipitation'),
        }));
        """
    )
    assert out["gusts"] is False
    assert out["rain"] == 5


def test_day_one_empty_state_names_only_real_thresholds():
    """The threshold line is the whole point of that empty state: it
    proves the detector is armed. "Schnee 0,00 cm/h" disproves it."""
    out = _js(
        """
        const { renderList } = await import(JS + '/storms/_list.js');
        const { stormsState } = await import(JS + '/storms/_state.js');
        const { _wsStatsState } = await import(JS + '/weather/stats.js');
        stormsState.episodes = [];
        _wsStatsState.data = { thresholds: { precipitation: 5, snowfall: null } };
        const host = { innerHTML: '', classList: { toggle() {} } };
        renderList(host, () => {});
        console.log(JSON.stringify({ html: host.innerHTML }));
        """
    )
    html = out["html"]
    assert "Aktuelle Schwellen" in html
    assert "Regen" in html
    assert "Schnee" not in html, "a null threshold must not be printed as 0"


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
    assert out["blank"] == "lightning_potential"


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
