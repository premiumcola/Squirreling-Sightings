// ─── Squirreling · Sightings service worker ────────────────────────────────────────────
// App-shell strategy. Caches the HTML/CSS/JS/icons that paint the chrome
// so a brief WLAN drop doesn't blank the screen, but never caches API,
// /media, or MJPEG streams — those are live data and a stale response
// would be worse than no response.
//
// ── VERSIONS-GETAKTET, NICHT PRO DATEI ────────────────────────────────
//
// Diese Datei hatte zwei Fassungen, und beide waren an derselben Frage
// falsch: „woher weiß der Browser, dass sein Vorrat noch stimmt?"
//
//   1. stale-while-revalidate für alles. `cached || fetchPromise` gibt
//      die ALTE Datei heraus und schreibt die neue für das nächste Mal —
//      ein Nutzer online, mit funktionierender Verbindung, hing dauerhaft
//      einen Deploy hinterher: „wieso kommt der neue player nicht bei
//      mir an??"
//   2. network-first mit `cache: 'no-cache'` für JEDE Code-Datei. Damit
//      war die Frische zurück, aber der Preis stand in dieser Datei als
//      Nebensatz: „one conditional request per file". Gemessen am
//      2026-09-12 sind das **365 bedingte Anfragen bei jedem
//      Seitenaufruf**, jede mit ihrer eigenen Wartezeit, und es werden
//      mit jedem neuen Modul mehr. Genau das ist der Eindruck „die Seite
//      wird mobil immer langsamer".
//
// Die Frage muss nicht 365-mal gestellt werden, sondern EINMAL. Der
// Cache-Name trägt den Shell-Hash aus /version.json, und der deckt seit
// jeher CSS **und** den JS-Baum ab. Also:
//
//   * bei jedem Seitenaufruf (navigate) genau eine Abfrage von
//     /version.json → der gültige Cache-Name;
//   * gleicher Hash  → alles aus dem Cache, NULL Netzanfragen für Code;
//   * anderer Hash   → anderer Cache-Name, der ist leer, alles wird
//     einmal frisch geholt. Ein altes Bündel kann gar nicht ausgeliefert
//     werden, weil es unter einem Namen liegt, den niemand mehr fragt.
//
// Das ist dieselbe Zusage wie bei network-first, für einen Rundlauf
// statt für 365. Als zweites Netz prüft core/version-guard.js im Tab den
// im Dokument eingestempelten Hash gegen den Server und bietet einen
// Knopf an, der Cache und Worker vollständig wegwirft.

const CACHE_PREFIX = 'squirreling-shell-';
const SHELL_ASSETS = [
  '/',
  '/static/app.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/manifest.json',
];

// Der Browser beendet und startet einen Service Worker ständig neu, und
// `install`/`activate` laufen dabei NICHT erneut — nur wenn sich die
// SW-Datei selbst ändert. Ein schlichtes `let _name = …` wäre also
// mehrmals pro Stunde wieder auf seinem Anfangswert. Deshalb wird der
// Name aus /version.json abgeleitet, gemerkt, und bei jedem
// Seitenaufruf einmal nachgezogen.
let _cacheName = null;
let _namePromise = null;

async function _purgeOthers(keep) {
  const keys = await caches.keys();
  await Promise.all(
    keys.filter((k) => k.startsWith(CACHE_PREFIX) && k !== keep).map((k) => caches.delete(k)),
  );
}

async function _resolveName() {
  try {
    const r = await fetch('/version.json', { cache: 'no-store' });
    if (r.ok) {
      const data = await r.json();
      if (data && data.shell_hash) {
        const name = CACHE_PREFIX + data.shell_hash;
        if (name !== _cacheName) {
          _cacheName = name;
          // Ein neuer Deploy: die alten Vorräte sind ab jetzt
          // unerreichbar, also weg damit, bevor sie Platz kosten.
          await _purgeOthers(name);
        }
        return _cacheName;
      }
    }
  } catch {
    /* offline → unten weiter */
  }
  if (_cacheName) return _cacheName;
  // Offline und noch kein Name: den vorhandenen versionierten Cache
  // weiterbenutzen statt einen frischen leeren zu erfinden — sonst hat
  // der Notnagel nichts, worauf er zurückfallen könnte.
  const keys = await caches.keys();
  _cacheName = keys.filter((k) => k.startsWith(CACHE_PREFIX))[0] || CACHE_PREFIX + 'init';
  return _cacheName;
}

function activeCacheName() {
  if (!_namePromise) _namePromise = _resolveName();
  return _namePromise;
}

/** Einmal pro Seitenaufruf: den Cache-Namen neu bestimmen. Alle
 *  Asset-Anfragen dieses Aufrufs warten auf dieselbe Zusage, bekommen
 *  also garantiert den Vorrat des Bündels, das gerade geladen wird. */
function refreshCacheName() {
  _namePromise = _resolveName();
  return _namePromise;
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
      await _purgeOthers(await activeCacheName());
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
 *  resort. Only the offline path gets to the second half. */
async function _fallback(request) {
  const c = await caches.open(await activeCacheName());
  return (await c.match(request)) || (await caches.match(request));
}

/** Cache-first gegen den VERSIONIERTEN Cache.
 *
 *  Dass das nichts Altes ausliefern kann, hängt an einer einzigen
 *  Eigenschaft: der Cache-Name trägt den Shell-Hash. Ein anderer Build
 *  ist ein anderer Name ist ein leerer Vorrat. Deshalb steht diese
 *  Funktion und nicht mehr `_networkFirst` in der Auslieferung. */
async function _cacheFirst(request) {
  const c = await caches.open(await activeCacheName());
  const cached = await c.match(request);
  if (cached) return cached;
  try {
    const net = await fetch(request);
    if (net && net.ok) _put(request, net.clone());
    return net;
  } catch (err) {
    const old = await caches.match(request);
    if (old) return old;
    throw err;
  }
}

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

  // Das Dokument selbst geht immer ans Netz (es ist ohnehin `no-store`)
  // und ist zugleich der Auslöser für die EINE Versionsabfrage, von der
  // alle Code-Anfragen dieses Aufrufs abhängen.
  if (evt.request.mode === 'navigate') {
    refreshCacheName();
    evt.respondWith(
      (async () => {
        try {
          return await fetch(evt.request);
        } catch (err) {
          const cached = await _fallback(evt.request);
          if (cached) return cached;
          throw err;
        }
      })(),
    );
    return;
  }

  evt.respondWith(_cacheFirst(evt.request));
});
