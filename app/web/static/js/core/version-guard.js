// ─── core/version-guard.js ───────────────────────────────────────────────
// Tells the operator when the code in THIS TAB is older than the code on
// the server, and gives them one button that actually fixes it.
//
// The reason this exists: weeks of front-end work sat on the server
// without ever reaching the browser, and nobody — including the person
// who wrote it — could tell. The dashboard's own "App & Server" panel
// was no help: its Build row comes from an API, so it reports the
// SERVER's commit and looked perfectly current while the tab rendered
// months-old modules. Every diagnostic surface pointed at the half that
// was fine.
//
// Worse, the staleness was PER FILE. The old service worker cached each
// URL independently and served it stale-while-revalidate, so a tab could
// hold new JavaScript against old CSS — a build that never existed in
// the repository and that no amount of reading the code explains.
//
// So: the server stamps its shell hash into the HTML at render time.
// That value travels with the DOCUMENT, which means it describes the
// bundle this tab actually booted. Comparing it against a live
// /version.json is the one honest way to answer "am I looking at the
// current app?".

const POLL_MS = 5 * 60 * 1000;

let _serverHash = null;
let _bootHash = null;
let _timer = null;
let _shown = false;

/** The hash the server stamped into this document at render time. */
function bootHash() {
  const meta = document.querySelector('meta[name="shell-version"]');
  return (meta?.content || '').trim() || null;
}

async function fetchServerHash() {
  try {
    // no-store, or the very cache this module exists to detect would
    // answer the question with its own stale copy.
    const r = await fetch('/version.json', { cache: 'no-store' });
    if (!r.ok) return null;
    const data = await r.json();
    return (data?.shell_hash || '').trim() || null;
  } catch {
    return null; // offline — say nothing rather than cry wolf
  }
}

/** Throw away every cached copy of the app, then reload.
 *
 * A plain reload is NOT enough and that is the whole point: if a service
 * worker is serving the stale bundle, it will serve it again to the
 * reloaded page. Unregistering it and emptying the caches first is what
 * makes the button honest.
 */
async function hardReload() {
  try {
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
  } catch (e) {
    console.warn('[version] service worker unregister failed:', e);
  }
  try {
    // globalThis, not window: `caches` lives on the global scope
    // (WindowOrWorkerGlobalScope). Identical in a browser tab, and the
    // right reference anywhere else.
    if (globalThis.caches) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
  } catch (e) {
    console.warn('[version] cache clear failed:', e);
  }
  location.reload();
}

function showBanner() {
  if (_shown) return;
  _shown = true;
  const bar = document.createElement('div');
  bar.className = 'version-bar';
  bar.setAttribute('role', 'status');
  bar.innerHTML =
    '<span class="version-bar-text">Diese Seite läuft auf einer älteren Fassung als der Server.</span>' +
    '<button type="button" class="version-bar-btn">Neu laden</button>';
  bar.querySelector('.version-bar-btn').addEventListener('click', hardReload);
  document.body.appendChild(bar);
}

async function check() {
  const server = await fetchServerHash();
  if (!server) return;
  _serverHash = server;
  // No stamp in the document at all means this tab booted from a build
  // that predates this module. That IS stale, by definition.
  if (!_bootHash || _bootHash !== _serverHash) showBanner();
}

/** Start watching. Idempotent. */
export function startVersionGuard() {
  _bootHash = bootHash();
  check();
  // A dashboard tab stays open for days on a wall display. Poll slowly,
  // and check again whenever it comes back to the foreground — that is
  // when someone is actually looking, and it costs nothing while hidden.
  _timer = setInterval(check, POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) check();
  });
}

export function stopVersionGuard() {
  if (_timer) clearInterval(_timer);
  _timer = null;
}

// Exposed for the diagnostics panel and for anyone debugging this from
// the console — `__version()` answers "what am I running vs. what is
// there" in one line, which is the question that took weeks to ask.
window.__version = () => ({ tab: _bootHash, server: _serverHash });
