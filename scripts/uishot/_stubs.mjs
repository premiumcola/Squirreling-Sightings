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
  DOSSIERS,
  DOSSIER_CLIPS,
  SIM_TICK,
  TPU_STATUS,
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
  if (pathname.startsWith('/api/bird-dossiers')) return { dossiers: DOSSIERS };
  if (pathname.startsWith('/api/library')) return DOSSIER_CLIPS;
  // The simulation's per-tick endpoint. Checked BEFORE the /api/cameras
  // prefix, which would otherwise swallow it and answer the poll loop
  // with a camera list — a body it reads as a tick with no detections,
  // which looks exactly like a loop that is running and finding nothing.
  if (pathname.includes('/test-detection')) return SIM_TICK;
  if (pathname.startsWith('/api/cameras')) return { cameras: [CAMERA] };
  if (pathname.startsWith('/api/bootstrap')) {
    return { wizard_done: true, cameras: [CAMERA], settings: {}, app: {} };
  }
  if (pathname.startsWith('/api/event/')) return {};
  if (pathname.startsWith('/api/status') || pathname.startsWith('/api/system')) {
    // `tpu` carried here and not on the frame, because that is where the
    // real endpoint puts it and where the panel's TPU chip looks.
    return { ok: true, cameras: {}, tpu: TPU_STATUS };
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

// ── Overrides that are not a 200 ───────────────────────────────────────────
// A surface used to be able to say only "answer this path with this body",
// which is enough to pose a different SUCCESS and nothing else. The whole
// failure half of the simulation — every 429, every 503, and a fetch that
// never lands at all — was therefore unphotographable, and "the panel
// explains the outage" could not be told apart from "the panel says
// nothing", which is exactly the defect that shipped.
//
// Tagged with `__uishot` rather than sniffed, because a real API body may
// legitimately have a `status` key of its own and guessing would silently
// answer the wrong thing.

const TAG = '__uishot';

/**
 * Answer one path with a non-200 status.
 *
 * @param {number} status
 * @param {object} body  the JSON the real endpoint would send
 */
export function reply(status, body) {
  return { [TAG]: 'reply', status, body };
}

/**
 * Fail one path at the transport, the way an unplugged box does: the
 * request is aborted, so `fetch` REJECTS rather than resolving with an
 * error status. That is a different branch in the poll loop
 * (`_handleTickError`, not `_consumeResponse`) and a different verdict on
 * screen, so it needs its own stub.
 */
export function netFail() {
  return { [TAG]: 'abort' };
}

/**
 * Does this override key select this path?
 *
 * A key starting with `/` is a path PREFIX, as it always was. Anything
 * else is a substring, mirroring apiBody's own `includes('/test-detection')`
 * — the simulation's endpoint sits under `/api/cameras/<id>/`, so a prefix
 * wide enough to reach it would also swallow the camera list the whole
 * page boots from.
 */
function overrideMatches(key, pathname) {
  return key.startsWith('/') ? pathname.startsWith(key) : pathname.includes(key);
}

/** Apply one matched override. Returns true when it answered the route. */
async function applyOverride(route, value) {
  if (value && value[TAG] === 'abort') {
    await route.abort('connectionrefused');
    return true;
  }
  const isReply = value && value[TAG] === 'reply';
  await route.fulfill({
    status: isReply ? value.status : 200,
    contentType: 'application/json',
    body: JSON.stringify(isReply ? value.body : value),
  });
  return true;
}

/** The two CDN libraries index.html loads, as inert stand-ins. */
const CDN_SHIM =
  'window.Hls={isSupported:function(){return false}};' +
  'window.L={map:function(){return{setView:function(){return this},' +
  'addLayer:function(){return this},on:function(){return this}}},' +
  'tileLayer:function(){return{addTo:function(){return this}}}};';

/**
 * Install request interception on one page.
 * Anything not matched falls through to the harness's static server.
 *
 * `overrides` is an optional { pathPrefix: answer } from the surface, for
 * the cases where the SAME endpoint has to answer differently than the
 * default fixture — a sparse weather archive, say, which is a state the
 * default payload cannot also be. Checked before apiBody, so a surface
 * can shadow any answer without editing the shared table.
 *
 * `answer` is a plain JSON body for a 200, or `reply(status, body)` /
 * `netFail()` for the failure states.
 */
export async function installStubs(page, overrides = null) {
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
    // `.mjpg` belongs here too: the live and simulation surfaces point
    // their <img> at a stream URL, and without it that request fell
    // through to the static server, 404'd, and photographed a broken-
    // image icon over a black stage — which reads as "the player cannot
    // show a picture" when the player is fine.
    const isImg =
      !CODE_RE.test(p) && (/\.(jpe?g|png|webp|gif|mjpg)$/i.test(p) || p.includes('snapshot'));
    if (isImg) return route.fulfill({ contentType: 'image/svg+xml', body: SNAPSHOT_SVG });

    if (p.startsWith('/api/') || (p.startsWith('/media/') && !p.endsWith('.mp4'))) {
      const over = Object.entries(overrides || {}).find(([key]) => overrideMatches(key, p));
      if (over) return applyOverride(route, over[1]);
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(apiBody(url)),
      });
    }
    return route.continue();
  });
}
