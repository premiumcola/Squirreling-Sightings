// ─── Squirreling · Sightings service worker ────────────────────────────────────────────
// App-shell strategy. Caches the HTML/CSS/JS/icons that paint the chrome
// so a brief WLAN drop doesn't blank the screen, but never caches API,
// /media, or MJPEG streams — those are live data and a stale response
// would be worse than no response.
//
// NETWORK-FIRST FOR CODE. This file used to be stale-while-revalidate
// for everything, and `return cached || fetchPromise` means the browser
// gets the OLD file and only writes the new one for NEXT time — so an
// online user with a working connection was permanently one deploy
// behind. For a dashboard that ships several times a day that is not a
// caching strategy, it is a bug with a comment: „wieso kommt der neue
// player nicht bei mir an??" Code now goes to the network first and
// falls back to the cache only when the network actually fails, which
// is the offline case the cache exists for in the first place.
//
// Cache versioning: the cache name carries the shell hash from
// /version.json — which since this commit hashes the JS tree as well as
// app.css, so a JavaScript-only deploy also flips it.

const CACHE_PREFIX = 'squirreling-shell-';
const SHELL_ASSETS = [
  '/',
  '/static/app.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/manifest.json',
];

// The browser kills and restarts a service worker constantly, and
// `install`/`activate` do NOT re-run on a restart — they only fire when
// the SW file itself changes. So a plain `let _activeCache = ...` is
// reset to its initial value several times an hour, and the old code
// then wrote fresh responses into a cache named `…-init` while
// `caches.match(req)` — unscoped, therefore searching EVERY cache —
// kept answering from the real one. New files were downloaded, stored,
// and never served. Re-deriving the name per request fixes that; the
// promise is memoised so it costs one fetch per SW lifetime, not one
// per request.
let _cacheNamePromise = null;

function activeCacheName() {
  if (!_cacheNamePromise) {
    _cacheNamePromise = (async () => {
      try {
        const r = await fetch('/version.json', { cache: 'no-store' });
        if (r.ok) {
          const data = await r.json();
          if (data && data.shell_hash) return CACHE_PREFIX + data.shell_hash;
        }
      } catch {
        /* offline → fall through */
      }
      // Offline and no name yet: reuse whatever versioned cache exists
      // rather than inventing a fresh empty one, or the fallback has
      // nothing to fall back to.
      const keys = await caches.keys();
      const known = keys.filter((k) => k.startsWith(CACHE_PREFIX));
      return known[0] || CACHE_PREFIX + 'init';
    })();
  }
  return _cacheNamePromise;
}

self.addEventListener('install', (evt) => {
  evt.waitUntil(
    (async () => {
      const c = await caches.open(await activeCacheName());
      await c.addAll(SHELL_ASSETS);
    })(),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (evt) => {
  evt.waitUntil(
    (async () => {
      const name = await activeCacheName();
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k.startsWith(CACHE_PREFIX) && k !== name).map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

/** Store a response copy in the ACTIVE cache — never in whatever name a
 *  restarted worker happened to start with. */
async function _put(request, response) {
  try {
    const c = await caches.open(await activeCacheName());
    await c.put(request, response);
  } catch {
    /* quota or opaque response — caching is best-effort */
  }
}

/** Read from the active cache, then from any older one as a last
 *  resort. Offline is the only path that gets here. */
async function _fallback(request) {
  const c = await caches.open(await activeCacheName());
  return (await c.match(request)) || (await caches.match(request));
}

/** Network-first: the answer is whatever the server says, and the cache
 *  is only consulted when the network fails.
 *
 *  `cache: 'no-cache'` is load-bearing, not decoration. A plain
 *  `fetch(request)` is served by the BROWSER's HTTP cache, so this
 *  function could hand back a stale file while believing it had gone to
 *  the network — the same bug one layer down, and it would have made
 *  this whole rewrite look like it did nothing.
 *
 *  Note it is 'no-cache', not 'no-store': the request still carries its
 *  validators, so an unchanged file comes back as a 304 with no body.
 *  Correctness on every load, at the cost of one conditional request per
 *  file — and, critically, this no longer depends on the server sending
 *  the right Cache-Control. index.html stamps ?v= on exactly two URLs;
 *  the several hundred ES modules behind them are fetched at addresses
 *  that never change, so their freshness rests entirely here.
 */
async function _networkFirst(request) {
  try {
    const net = await fetch(request, { cache: 'no-cache' });
    if (net && net.ok) _put(request, net.clone());
    return net;
  } catch (err) {
    const cached = await _fallback(request);
    if (cached) return cached;
    throw err;
  }
}

/** Cache-first for things that do not change between deploys — icons,
 *  the manifest, fonts. Saves a round trip where staleness costs
 *  nothing, because the cache name itself flips on every deploy. */
async function _cacheFirst(request) {
  const cached = await _fallback(request);
  if (cached) return cached;
  const net = await fetch(request);
  if (net && net.ok) _put(request, net.clone());
  return net;
}

const _IMMUTABLE = /\.(png|jpg|jpeg|svg|ico|webp|woff2?|ttf)$|\/manifest\.json$/i;

self.addEventListener('fetch', (evt) => {
  const url = new URL(evt.request.url);

  // Live data — never cache. The browser handles offline failure on the
  // app side (toast + per-widget error states); a stale cached response
  // would lie about the camera state.
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/media/')) return;
  if (url.pathname.includes('.mjpg')) return;
  if (url.pathname.includes('snapshot.jpg')) return;
  if (url.pathname === '/sw.js') return;
  // The SW asks for this itself to learn the cache name; going through
  // the cache here would be circular.
  if (url.pathname === '/version.json') return;
  // Cross-origin (CDN, tiles) — leave to the browser's own cache.
  if (url.origin !== self.location.origin) return;

  evt.respondWith(
    _IMMUTABLE.test(url.pathname) ? _cacheFirst(evt.request) : _networkFirst(evt.request),
  );
});
