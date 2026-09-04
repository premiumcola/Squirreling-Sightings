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
let _dismissed = false;
let _onVisible = null;

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
    '<button type="button" class="version-bar-btn">Neu laden</button>' +
    '<button type="button" class="version-bar-close" aria-label="Hinweis ausblenden">×</button>';
  bar.querySelector('.version-bar-btn').addEventListener('click', hardReload);
  // Dismissable on purpose. Being one deploy behind breaks nothing, and
  // the bar is fixed over the content — on a phone it sits where the
  // navigation dock is. A notice the operator cannot get out of the way
  // is worse than the staleness it reports, and it would be dismissed by
  // closing the tab, which is the one action that loses their place.
  bar.querySelector('.version-bar-close').addEventListener('click', () => {
    bar.remove();
    // Stays gone for this tab. It will come back on the next full load,
    // which is exactly when acting on it is free.
    _dismissed = true;
  });
  document.body.appendChild(bar);
}

async function check() {
  if (_dismissed) return;
  const server = await fetchServerHash();
  if (!server) return;
  _serverHash = server;
  // No stamp in the document at all means this tab booted from a build
  // that predates this module. That IS stale, by definition.
  if (!_bootHash || _bootHash !== _serverHash) showBanner();
}

/** Start watching. Idempotent — a second call is a no-op.
 *
 * The guard for that is real, not defensive boilerplate: without it a
 * second call stacks a second interval and a second listener, and every
 * later stop leaks both.
 */
export function startVersionGuard() {
  if (_timer) return;
  _bootHash = bootHash();
  check();
  // A dashboard tab stays open for days on a wall display. Poll slowly,
  // and check again whenever it comes back to the foreground — that is
  // when someone is actually looking, and it costs nothing while hidden.
  _timer = setInterval(check, POLL_MS);
  // Named, so stopVersionGuard can actually take it off again.
  _onVisible = () => {
    if (!document.hidden) check();
  };
  document.addEventListener('visibilitychange', _onVisible);
}

export function stopVersionGuard() {
  if (_timer) clearInterval(_timer);
  _timer = null;
  if (_onVisible) document.removeEventListener('visibilitychange', _onVisible);
  _onVisible = null;
}

// Exposed for the diagnostics panel and for anyone debugging this from
// the console — `__version()` answers "what am I running vs. what is
// there" in one line, which is the question that took weeks to ask.
window.__version = () => ({ tab: _bootHash, server: _serverHash });
