// ─── scripts/uishot/_stubs.mjs ─────────────────────────────────────────────
// Everything the page asks the network for, answered locally.
//
// The harness does not boot Flask, so /api/* has to come from somewhere.
// Answering at the browser rather than in a server keeps the fixtures in
// one file with the surfaces that use them, and makes "what did this
// surface actually request" observable.
//
// The two CDN <script> tags in index.html are stubbed rather than
// fetched: the harness must not depend on the internet, and neither
// library draws any of the four surfaces.

import {
  TRACKS,
  CLIP_ONLY_TRACKS,
  CAMERA,
  TIMELINE_MONTH,
  TIMELINE_DAY,
  DETECTION_CLOUD,
  WEATHER_HISTORY,
} from './_fixtures.mjs';

/** A neutral picture stand-in, so tiles show a frame and not a placeholder. */
const SNAPSHOT_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">` +
  `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">` +
  `<stop offset="0" stop-color="#2b3a4a"/><stop offset="1" stop-color="#16202b"/>` +
  `</linearGradient></defs><rect width="640" height="360" fill="url(#g)"/>` +
  `<circle cx="480" cy="90" r="38" fill="#3d5064"/>` +
  `<rect y="250" width="640" height="110" fill="#1b2a1f"/>` +
  `<text x="24" y="332" font-family="sans-serif" font-size="20" fill="#7d93a8">uishot fixture frame</text>` +
  `</svg>`;

/** Static JSON answers, longest prefix wins. */
function apiBody(url) {
  const pathname = url.pathname;
  // The clip-basis surface's event, whose indexer confirmed nothing —
  // keyed on its own file so the sidecar-basis surface keeps its tracks.
  if (pathname.endsWith('e7.tracks.json')) return CLIP_ONLY_TRACKS;
  if (pathname.endsWith('.tracks.json')) return TRACKS;
  if (pathname.startsWith('/api/cameras')) return { cameras: [CAMERA] };
  if (pathname.startsWith('/api/bootstrap')) {
    return { wizard_done: true, cameras: [CAMERA], settings: {}, app: {} };
  }
  if (pathname.startsWith('/api/event/')) return {};
  if (pathname.startsWith('/api/status') || pathname.startsWith('/api/system')) {
    return { ok: true, cameras: {} };
  }
  // camedit/index.js::renderProfiles does an unguarded
  // `cats.profiles.map(...)`, and it is awaited from live-update.js's
  // loadAll — so a shape it does not expect throws and silently kills
  // every boot step queued after it. Shaped correctly here so the
  // harness sees the app's real console, not one error of its own making.
  if (pathname.startsWith('/api/cats') || pathname.startsWith('/api/persons')) {
    return { profiles: [] };
  }
  if (pathname.startsWith('/api/telegram/actions')) return { items: [] };
  // library/_filter-chips.js guards `cameras` but never `counts`, in all
  // three chip builders — an absent sub-dict throws inside the map and
  // takes the filter bar down with it. Every key it reads is present here.
  if (pathname.startsWith('/api/library/facets')) {
    return { cameras: {}, labels: {}, categories: {}, kinds: {}, total: 0 };
  }
  // The Statistik panel asks twice with different windows and draws a
  // different chart from each — the month feeds the donut and the period
  // pills, the rolling 24 h feeds the heatmap. Answering both with one
  // body would photograph the heatmap's empty state.
  if (pathname.startsWith('/api/timeline')) {
    return Number(url.searchParams.get('hours')) > 24 ? TIMELINE_MONTH : TIMELINE_DAY;
  }
  if (pathname.startsWith('/api/detection_cloud')) return DETECTION_CLOUD;
  // The Wetterdaten panel re-fetches this on a 60 s timer AND on its
  // IntersectionObserver, so seeding _wsStatsState by hand is not enough
  // — the first refresh would overwrite the fixture with `{}` and the
  // shot would catch an empty chart. Answering here also means the
  // surface exercises the real loadWeatherStats path.
  if (pathname.startsWith('/api/weather/history')) return WEATHER_HISTORY;
  return {};
}

/** Code assets must never be answered with a picture or a JSON blob. */
const CODE_RE = /\.(m?js|json|css|map)$/i;

/** The two CDN libraries index.html loads, as inert stand-ins. */
const CDN_SHIM =
  'window.Hls={isSupported:function(){return false}};' +
  'window.L={map:function(){return{setView:function(){return this},' +
  'addLayer:function(){return this},on:function(){return this}}},' +
  'tileLayer:function(){return{addTo:function(){return this}}}};';

/**
 * Install request interception on one page.
 * Anything not matched falls through to the harness's static server.
 */
export async function installStubs(page) {
  // The CDN <script> tags carry SRI hashes, so a stubbed BODY is rejected
  // by the integrity check and the globals never appear. Defining them
  // before any document script runs sidesteps that entirely, and the
  // requests themselves are aborted — the harness must not need network.
  await page.addInitScript(CDN_SHIM);

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;

    if (url.hostname !== '127.0.0.1') return route.abort();

    // Pictures: snapshots and thumbnails. Extension decides — matching on
    // the word "snapshot" alone also catches real modules such as
    // mediaview/player/_snapshot.js, which then arrive as image/svg+xml
    // and take the whole module graph down with them.
    const isImg =
      !CODE_RE.test(p) && (/\.(jpe?g|png|webp|gif)$/i.test(p) || p.includes('snapshot'));
    if (isImg) return route.fulfill({ contentType: 'image/svg+xml', body: SNAPSHOT_SVG });

    if (p.startsWith('/api/') || (p.startsWith('/media/') && !p.endsWith('.mp4'))) {
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(apiBody(url)),
      });
    }
    return route.continue();
  });
}
