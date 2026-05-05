// ─── birds.js ──────────────────────────────────────────────────────────────
// Bird dossier gallery (F08). Sub-section of the Sichtungen panel,
// rendered below the species achievement grid. The data comes from
// `/api/bird-dossiers` (auto-built service) — server-side
// BirdDossierService caches Wikipedia summaries + Xeno-canto audio
// per latin name.
//
// Two-pane UX:
//   • Gallery — tile per species, newest sighting first
//   • Detail modal — first-seen snapshot, Wikipedia extract, audio
//     player with attribution + license (CC-BY compliance!), recent
//     sightings list (clickable into the lightbox).
import { byId, esc } from './core/dom.js';
import { j } from './core/api.js';

let _dossiers = [];

function _relDays(iso){
  if (!iso) return '';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const days = Math.floor((Date.now() - t) / (24 * 3600 * 1000));
  if (days <= 0) return 'heute';
  if (days === 1) return 'gestern';
  if (days < 14) return `vor ${days} Tagen`;
  if (days < 60) return `vor ${Math.round(days / 7)} Wochen`;
  return `vor ${Math.round(days / 30)} Monaten`;
}

export async function loadBirdDossiers(){
  try {
    const r = await j('/api/bird-dossiers');
    _dossiers = (r && r.dossiers) || [];
  } catch {
    _dossiers = [];
  }
  renderBirdDossiers();
}
window.loadBirdDossiers = loadBirdDossiers;

export function renderBirdDossiers(){
  const wrap = byId('birdsGallery');
  if (!wrap) return;
  if (!_dossiers.length){
    wrap.innerHTML = `<div class="birds-empty">
      Noch keine Vogel-Dossiers — sobald der Bird-Classifier eine neue
      Art identifiziert, wird sie hier angelegt.</div>`;
    return;
  }
  const tiles = _dossiers.map(_tileHtml).join('');
  wrap.innerHTML = `<div class="birds-grid">${tiles}</div>`;
  wrap.querySelectorAll('.bird-tile').forEach(el => {
    el.addEventListener('click', () => {
      openBirdDossier(el.dataset.latin);
    });
  });
}
window.renderBirdDossiers = renderBirdDossiers;

function _tileHtml(d){
  const thumb = d.wikipedia_thumb_url
    ? `<img class="bird-thumb-img" src="${esc(d.wikipedia_thumb_url)}" alt="" loading="lazy"/>`
    : `<div class="bird-thumb-placeholder">🐦</div>`;
  const nameDe = esc(d.common_name_de || d.latin);
  const latin = esc(d.latin);
  const seen = esc(_relDays(d.first_seen_at) ? `Erstmals gesichtet ${_relDays(d.first_seen_at)}` : 'Frisch entdeckt');
  const cnt = d.sighting_count || 1;
  return `<article class="bird-tile" data-latin="${latin}" tabindex="0" role="button">
    <div class="bird-thumb">${thumb}</div>
    <div class="bird-info">
      <div class="bird-name-de">${nameDe}</div>
      <div class="bird-name-latin">${latin}</div>
      <div class="bird-meta">${seen}</div>
    </div>
    <span class="bird-count-badge" title="${cnt} Sichtungen">${cnt}×</span>
  </article>`;
}

// ── Detail modal ───────────────────────────────────────────────────────────
async function openBirdDossier(latin){
  if (!latin) return;
  let payload = null;
  try {
    payload = await j(`/api/bird-dossiers/${encodeURIComponent(latin)}`);
  } catch {
    payload = null;
  }
  if (!payload || !payload.dossier){
    return;
  }
  const d = payload.dossier;
  const evs = payload.events || [];
  // Prefer the snapshot of the first-seen event; if we can't recover
  // it from the events list, fall back to the Wikipedia thumbnail.
  let firstSnap = null;
  const firstEvent = evs.find(e => e.event_id === d.first_seen_event_id) || evs[0];
  if (firstEvent && firstEvent.snapshot_url){
    firstSnap = firstEvent.snapshot_url;
  }
  const heroImg = firstSnap || d.wikipedia_thumb_url || '';
  const audioBlock = d.audio_url ? `
    <div class="bird-modal-audio">
      <audio controls preload="none" src="${esc(d.audio_url)}"></audio>
      <div class="bird-modal-attribution">
        ♪ Audio: ${esc(d.audio_attribution || 'unbekannt')}${d.audio_license
          ? ` · <a href="${esc(d.audio_license)}" target="_blank" rel="noopener noreferrer">Lizenz</a>`
          : ''}
        · Quelle: <a href="https://xeno-canto.org/" target="_blank" rel="noopener noreferrer">xeno-canto.org</a>
      </div>
    </div>` : '';
  const wikiBlock = d.wikipedia_summary ? `
    <p class="bird-modal-summary">${esc(d.wikipedia_summary)}</p>` : `
    <p class="bird-modal-summary bird-modal-summary--missing">
      Keine Wikipedia-Daten verfügbar — der nächste Re-Fetch versucht es erneut.
    </p>`;
  const eventsBlock = evs.length ? `
    <div class="bird-modal-events">
      <div class="bird-modal-events-title">Letzte Sichtungen</div>
      <div class="bird-modal-events-grid">
        ${evs.slice(0, 10).map(_eventThumbHtml).join('')}
      </div>
    </div>` : '';
  const wikiLink = d.wikipedia_url ? `
    <a class="bird-modal-wiki-link" href="${esc(d.wikipedia_url)}" target="_blank" rel="noopener noreferrer">
      Auf Wikipedia ansehen ↗
    </a>` : '';
  const refetchBtn = `<button type="button" class="btn-action bird-refetch"
    onclick="window.refetchBirdDossier('${esc(d.latin)}')">Re-Fetch</button>`;

  const html = `
    <div class="bird-modal-backdrop" onclick="this.remove()">
      <div class="bird-modal" onclick="event.stopPropagation()">
        <button type="button" class="bird-modal-close" onclick="this.closest('.bird-modal-backdrop').remove()" aria-label="Schließen">✕</button>
        <header class="bird-modal-head">
          <div class="bird-modal-titles">
            <h3>${esc(d.common_name_de || d.latin)}</h3>
            <div class="bird-modal-latin">${esc(d.latin)}</div>
          </div>
          ${refetchBtn}
        </header>
        ${heroImg ? `<div class="bird-modal-hero"><img src="${esc(heroImg)}" alt=""/></div>` : ''}
        ${wikiBlock}
        ${audioBlock}
        ${wikiLink}
        <div class="bird-modal-footline">
          Erstmals gesichtet ${esc(_relDays(d.first_seen_at))}
          · ${d.sighting_count || 1} Sichtungen insgesamt
        </div>
        ${eventsBlock}
      </div>
    </div>`;
  // Mount as a sibling to body so the backdrop can use position:fixed
  // without inheriting any panel's overflow:hidden.
  const div = document.createElement('div');
  div.innerHTML = html;
  document.body.appendChild(div.firstElementChild);
}
window.openBirdDossier = openBirdDossier;

function _eventThumbHtml(ev){
  const url = ev.snapshot_url || ev.thumb_url || '';
  const time = ev.time ? esc(ev.time.replace('T', ' ').slice(0, 16)) : '';
  if (!url){
    return `<div class="bird-event-thumb bird-event-thumb--missing"><span>${time}</span></div>`;
  }
  return `<a class="bird-event-thumb" href="#"
    onclick="event.preventDefault(); window.openLightbox && window.openLightbox(${esc(JSON.stringify(ev))})">
    <img src="${esc(url)}" alt="" loading="lazy"/>
    <span>${time}</span>
  </a>`;
}

export async function refetchBirdDossier(latin){
  if (!latin) return;
  try {
    await j(`/api/bird-dossiers/${encodeURIComponent(latin)}/refetch`, { method: 'POST' });
  } catch {
    // Refetch is best-effort — failures are silent on the server, so
    // we don't need to surface them here either.
  }
  // The bg fetch needs a couple seconds; reload the modal data after a
  // short delay so the user sees the refresh land without polling.
  setTimeout(() => {
    document.querySelector('.bird-modal-backdrop')?.remove();
    loadBirdDossiers().then(() => openBirdDossier(latin));
  }, 4000);
}
window.refetchBirdDossier = refetchBirdDossier;
