// ─── storms/index.js ───────────────────────────────────────────────────────
// Gewitter-Browser — public API, boot, view router.
//
// The app is a single scrolling page, so this "page" is a section
// (#storms) with three STATES rather than three modals. Only one state
// is in the DOM at a time: that avoids a modal-inside-a-modal on iOS,
// keeps safe-area handling in one place, and makes the browser back
// button work for free.
//
//   #storms                          → Liste
//   #/gewitter/<id>                  → Detail
//   #/gewitter/vergleich/<id>,<id>…  → Vergleich (2–4 ids)
//
// Back from detail to the list is a history-driven state change, not a
// re-fetch: the list stays in module state.

import { byId } from '../core/dom.js';
import { stormsState, STORM_MAX_COMPARE, slotAssign, slotsClear } from './_state.js';
import { fetchEpisodes, fetchEpisode } from './_api.js';
import { renderList } from './_list.js';
import { renderDetail, remountDetailChart } from './_detail.js';
import { renderCompare } from './_compare.js';
import { renderDeadEnd } from './_helpers.js';

const BODY_ID = 'stormsBody';

function _host() {
  return byId(BODY_ID);
}

function _navigate(hash) {
  if (location.hash === hash) _route();
  else location.hash = hash;
}

// Loaded once per session. A load that FAILED is retried on the next
// visit rather than latching the archive empty for the rest of the
// session — the endpoint may simply not have existed yet at boot.
async function _ensureLoaded() {
  if (stormsState.loaded && !stormsState.unavailable) return;
  const { items, ok } = await fetchEpisodes();
  stormsState.episodes = items;
  stormsState.unavailable = !ok;
  stormsState.loaded = true;
}

// Full record (with samples) for one id, cached so compare fetches each
// episode exactly once per session.
async function _full(id) {
  if (stormsState.samples[id]) return stormsState.samples[id];
  const rec = await fetchEpisode(id);
  if (rec) stormsState.samples[id] = rec;
  return rec;
}

function _listRecord(id) {
  return stormsState.episodes.find((ep) => ep.id === id) || null;
}

async function _showList(host) {
  stormsState.view = 'list';
  await _ensureLoaded();
  renderList(host, _navigate);
}

async function _showDetail(host, id) {
  stormsState.view = 'detail';
  stormsState.detailId = id;
  host.classList.remove('is-selecting');
  await _ensureLoaded();
  host.innerHTML = '<div class="ws-empty">Gewitter wird geladen …</div>';
  const rec = (await _full(id)) || _listRecord(id);
  if (stormsState.detailId !== id) return; // a newer navigation won
  if (!rec) {
    renderDeadEnd(host, 'Dieses Gewitter ist nicht mehr im Archiv.', _navigate);
    return;
  }
  stormsState.detail = rec;
  renderDetail(host, rec, _navigate);
}

async function _showCompare(host, ids) {
  stormsState.view = 'compare';
  host.classList.remove('is-selecting');
  await _ensureLoaded();
  host.innerHTML = '<div class="ws-empty">Vergleich wird geladen …</div>';
  const wanted = ids.slice(0, STORM_MAX_COMPARE);
  // Re-seed the slot allocator from the URL so a deep link paints the
  // same colours the picker would have assigned.
  if (wanted.some((id) => !stormsState.slots.includes(id))) {
    slotsClear();
    for (const id of wanted) slotAssign(id);
  }
  const recs = [];
  for (const id of wanted) {
    const rec = (await _full(id)) || _listRecord(id);
    if (rec) recs.push(rec);
  }
  if (stormsState.view !== 'compare') return;
  renderCompare(host, recs, _navigate);
}

function _route() {
  const host = _host();
  if (!host) return;
  const h = location.hash || '';
  let m;
  if ((m = h.match(/^#\/gewitter\/vergleich\/(.+)$/))) {
    const ids = decodeURIComponent(m[1])
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (ids.length >= 2) {
      _showCompare(host, ids);
      return;
    }
  }
  if ((m = h.match(/^#\/gewitter\/([^/]+)$/))) {
    _showDetail(host, decodeURIComponent(m[1]));
    return;
  }
  _showList(host);
}

// Re-draw on resize so the SVG charts keep their 1:1 viewBox mapping
// through a rotation or a window drag. Debounced.
//
// Detail re-mounts ONLY its chart. It used to run the whole router,
// which overwrites the host with a loading placeholder — and the detail
// header holds two text editors that autosave on blur, so a window drag
// with a half-typed name open removed the input without firing blur and
// the text was gone. Compare carries no editors and re-renders whole.
function _onResize() {
  if (stormsState.view === 'detail') {
    if (stormsState.detail) {
      remountDetailChart(stormsState.detail);
      return;
    }
  }
  _route();
}

let _resizeTimer = null;
window.addEventListener(
  'resize',
  () => {
    if (!_host() || stormsState.view === 'list') return;
    if (_resizeTimer) clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(_onResize, 180);
  },
  { passive: true },
);

let _observer = null;

// Hydrate on first visibility rather than at boot — the archive is a
// section the operator scrolls into, not a background task.
export function initStorms() {
  const sec = byId('storms');
  const host = _host();
  if (!sec || !host) return;
  if (_observer) return;
  _observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      _route();
    },
    { threshold: 0.02 },
  );
  _observer.observe(sec);
  // A deep link that lands on a storm route must render even if the
  // section never crosses the observer threshold on its own.
  if ((location.hash || '').startsWith('#/gewitter/')) _route();
}

window.addEventListener('hashchange', () => {
  const h = location.hash || '';
  if (h === '#storms' || h.startsWith('#/gewitter/')) _route();
});

document.addEventListener('DOMContentLoaded', initStorms);

// window.* bridge — live-update.js's loadAll() reaches domain
// bootstrappers by global name, matching initWeatherStats next door.
window.initStorms = initStorms;
