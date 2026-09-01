// ─── mediathek/_overview.js ────────────────────────────────────────────────
// R23 split of orchestration.js — Level 1 of the Mediathek: the camera tile
// grid the section opens on ("Alle Medien" + one card per active camera +
// the archived-cameras strip), plus the single source of truth for which
// tile reads as active.
//
// Level 2 (the drilldown the tiles open) lives in _drilldown.js; this
// module only paints tiles and never loads media itself — the onclick
// bridges go through window.openMediaDrilldown / openAllMediaDrilldown.
import { byId, esc, safeHexColor } from '../core/dom.js';
import { state } from '../core/state.js';
import { getCameraIcon, getCameraColor, objIconSvg } from '../core/icons.js';
import { _buildMocChips } from './_chips.js';
import { renderMediaFilterPills } from './filters.js';

// Quick-jump tiles into the MERGED grid (library/page.js), not the
// per-camera drilldown the tiles above open — "Tiere" and "Menschen"
// are cross-camera, cross-kind questions ("show me every animal, on
// any camera"), which is exactly what the merged feed already answers
// and the drilldown (motion clips, one camera at a time) cannot: it has
// no concept of grouping several object labels into one tap.
// `objIconSvg('wildlife', …)` is the same generic-paw fallback the
// per-label pill row already falls back to for fox/hedgehog/marten/deer
// (core/icons.js), so "Tiere" reads as one obvious step up from those
// species-specific icons rather than a new visual language.
const _QUICK_LABEL_TILES = [
  {
    id: '__animals__',
    name: 'Tiere',
    icon: () => objIconSvg('wildlife', 48),
    labels: ['cat', 'bird', 'dog', 'squirrel', 'fox', 'hedgehog', 'marten', 'deer'],
  },
  {
    id: '__people__',
    name: 'Menschen',
    icon: () => objIconSvg('person', 48),
    labels: ['person'],
  },
];

function _quickLabelTileHTML(tile) {
  return `<div class="moc-card moc-quick" data-quick-id="${tile.id}" data-quick-labels="${tile.labels.join(',')}">
    <div class="moc-all-thumb moc-quick-thumb">${tile.icon()}</div>
    <div class="moc-body">
      <div class="moc-name">${esc(tile.name)}</div>
      <div class="moc-desc">Alle Kameras &middot; Kurzeinstieg</div>
    </div>
  </div>`;
}

/** Wired separately from the inline onclicks the camera/"Alle Medien"
 *  tiles use — an array of labels doesn't serialise cleanly into an
 *  inline attribute the way a single camera id string does. */
function _bindQuickLabelTiles() {
  document.querySelectorAll('.moc-quick[data-quick-labels]').forEach((card) => {
    card.addEventListener('click', () => {
      window.setLibraryLabelFilter?.(card.dataset.quickLabels.split(','));
    });
  });
}

function _fmtMb(mb) {
  if (!mb || mb <= 0) return '0 MB';
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB';
  return Math.round(mb) + ' MB';
}
// Archive icon — box with lid and latch
const _ARCHIVE_ICON = `<svg width="13" height="12" viewBox="0 0 13 12" fill="none" aria-hidden="true" style="flex-shrink:0"><rect x="1" y="4.5" width="11" height="7" rx="1.5" stroke="currentColor" stroke-width="1.3"/><rect x="0.5" y="2" width="12" height="2.5" rx="1" stroke="currentColor" stroke-width="1.1"/><rect x="4.5" y="6.25" width="4" height="2" rx="0.75" stroke="currentColor" stroke-width="1"/></svg>`;

// All-media multi-camera grid icon — 4 quads: TL=timelapse(violet), TR=motion(blue), BL=person(blue), BR=object(amber)
// Single coherent stacked-media glyph for the "Alle Medien" tile.
// Replaces a previous 2×2 collage of small thumbnails (timelapse,
// walker, face, archive bag) which read as cluttered. Three overlapping
// rounded "media cards" stacked top-down with a play triangle on the
// front card communicate "all archived clips" cleanly. Single muted-
// blue family, flat fill, ≥ 8 px corner radius per CLAUDE.md design
// rules. Container CSS centers + pads it so the mark sits with
// comfortable breathing room on all four sides of the tile.
// Composite bounding box of the three rects spans x=14-70, y=10-54
// (centre 42,32). The 80×80 viewBox centre is 40,40 — so the
// composite is 2 px right and 8 px above where it should sit. The
// translate(-2,8) on the wrapping <g> pulls the whole stack back
// onto the geometric centre with equal padding on all four sides.
export const _MOC_ALL_SVG = `<svg width="96" height="96" viewBox="0 0 80 80" fill="none" aria-hidden="true">
  <g transform="translate(-2, 8)">
    <rect x="14" y="22" width="44" height="32" rx="6" fill="#3a5878" opacity=".55"/>
    <rect x="20" y="16" width="44" height="32" rx="6" fill="#4a7090" opacity=".8"/>
    <rect x="26" y="10" width="44" height="32" rx="6" fill="#7faec9"/>
    <polygon points="44,18 44,34 58,26" fill="#1a2535"/>
  </g>
</svg>`;

const _THUMB_BADGE_STYLE =
  'position:absolute;bottom:6px;right:6px;font-size:10px;font-weight:700;color:#e2e8f0;background:rgba(0,0,0,.68);backdrop-filter:blur(3px);padding:2px 6px;border-radius:4px;z-index:2';

// Sum every per-camera stats row into one "Alle Medien" row, merging the
// per-label counters key by key.
function _totalStats() {
  return (state.mediaStats || []).reduce(
    (acc, s) => {
      const lc = { ...acc.label_counts };
      if (s.label_counts)
        Object.entries(s.label_counts).forEach(([k, v]) => {
          lc[k] = (lc[k] || 0) + v;
        });
      return {
        size_mb: (acc.size_mb || 0) + (s.size_mb || 0),
        event_count: (acc.event_count || 0) + (s.event_count || 0),
        jpg_count: (acc.jpg_count || 0) + (s.jpg_count || 0),
        timelapse_count: (acc.timelapse_count || 0) + (s.timelapse_count || 0),
        label_counts: lc,
      };
    },
    { size_mb: 0, event_count: 0, jpg_count: 0, timelapse_count: 0, label_counts: {} },
  );
}

function _camCardHTML(c, s, ts) {
  const icon = getCameraIcon(c.name || c.id);
  const camColor = getCameraColor(c);
  // Prefer newest object-labelled snapshot (person/cat/bird/car) over generic latest snap;
  // fall back to the generic latest, then the live snapshot.
  const storedSnap = s.latest_object_snap_url || s.latest_snap_url || '';
  const liveSnap = `/api/camera/${encodeURIComponent(c.id)}/snapshot.jpg?t=${ts}`;
  const thumbSrc = storedSnap || liveSnap;
  // Camera-icon placeholder when the thumbnail img fails to load.
  // Earlier this wrapped the icon in an inline ``font-size:48px;
  // opacity:.25`` span — useless because SVGs ignore font-size for
  // their own dimensions. The .cam-ico-placeholder rule in
  // 03-dashboard.css now sizes the icon to 56 × 56 and centres it
  // inside the .moc-thumb's 16:9 box. The inline ``color:`` carries
  // the camera's identity tint so the placeholder reads as that
  // camera instead of a generic grey silhouette.
  // P21 · camColor is user-settable via cam-edit Color-Picker — pass
  // it through safeHexColor before interpolating into the inline JS
  // string below. Without the gate, a malicious value like
  // `'); evil(); //` would break out of the style.color string and
  // execute arbitrary JS in the onerror handler. iconEsc is the
  // already-quote-escaped SVG from a controlled icon map, safe.
  const iconEsc = icon.replace(/'/g, "\\'");
  const camColorSafe = safeHexColor(camColor);
  const replaceWithPh = `const s=document.createElement('span');s.className='cam-ico-placeholder';s.style.color='${camColorSafe}';s.innerHTML='${iconEsc}';this.replaceWith(s)`;
  const fallback = storedSnap
    ? `this.onerror=function(){${replaceWithPh}};this.src='${liveSnap}'`
    : replaceWithPh;
  const locationDesc = c.location ? `<div class="moc-desc">${esc(c.location)}</div>` : '';
  return `<div class="moc-card" data-cam-id="${esc(c.id)}" onclick="openMediaDrilldown('${esc(c.id)}')">
      <div class="moc-thumb"><img src="${esc(thumbSrc)}" alt="${esc(c.name)}" onerror="${esc(fallback)}" loading="lazy"/><div style="${_THUMB_BADGE_STYLE}">${_fmtMb(s.size_mb || 0)}</div></div>
      <div class="moc-body">
        <div class="moc-name"><span class="moc-name-icon" style="color:${camColorSafe}">${icon}</span> ${esc(c.name)}</div>
        ${locationDesc}
        <div class="moc-counts">
          ${_buildMocChips(s)}
        </div>
      </div>
    </div>`;
}

// Archived cameras section — cameras removed from config but with remaining media
function _archivedSectionHTML(archived) {
  if (!archived.length) return '';
  const archCards = archived
    .map((a) => {
      const thumbInner = a.latest_snap_url
        ? `<img src="${esc(a.latest_snap_url)}" alt="${esc(a.name)}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block;filter:grayscale(.45) brightness(.8)"/>`
        : `<span style="font-size:36px;opacity:.18">📦</span>`;
      const archBadgeStyle =
        'position:absolute;bottom:6px;right:6px;font-size:10px;font-weight:700;color:#a5bfce;background:rgba(0,0,0,.68);backdrop-filter:blur(3px);padding:2px 6px;border-radius:4px;z-index:2';
      return `<div class="moc-card moc-archived" data-cam-id="${esc(a.id)}" onclick="openMediaDrilldown('${esc(a.id)}')">
        <div class="moc-thumb moc-arch-thumb">${thumbInner}<div style="${archBadgeStyle}">${_fmtMb(a.size_mb || 0)}</div></div>
        <div class="moc-body">
          <div class="moc-name" style="display:flex;align-items:center;gap:6px">${_ARCHIVE_ICON} <span>${esc(a.name)}</span></div>
          <div class="moc-desc">Archiviert · <code style="font-size:10px;opacity:.6">${esc(a.id)}</code></div>
          <div class="moc-counts">${_buildMocChips(a)}</div>
          <div style="margin-top:8px">
            <button class="btn-action ghost btn-merge-archived" title="In aktive Kamera zusammenführen" data-merge-action="open" data-merge-id="${esc(a.id)}" data-merge-name="${esc(a.name)}">
              Zusammenführen ↗
            </button>
          </div>
        </div>
      </div>`;
    })
    .join('');
  return `<div class="moc-archive-section">
      <div class="moc-archive-hdr">${_ARCHIVE_ICON} Archivierte Kameras <span class="moc-archive-count">${archived.length}</span></div>
      <div class="moc-archive-grid">${archCards}</div>
    </div>`;
}

// ── Overview ────────────────────────────────────────────────────────────────
export function renderMediaOverview() {
  const ov = byId('mediaOverview');
  if (!ov) return;
  const cams = state.cameras;
  if (!cams.length) {
    ov.innerHTML = '';
    return;
  }
  const statsByid = {};
  (state.mediaStats || []).forEach((s) => {
    statsByid[s.camera_id || s.id || s.name] = s;
  });
  const totalStats = _totalStats();

  const allCard = `<div class="moc-card" data-cam-id="__all__" onclick="openAllMediaDrilldown()">
    <div class="moc-all-thumb">${_MOC_ALL_SVG}<div style="${_THUMB_BADGE_STYLE}">${_fmtMb(totalStats.size_mb)}</div></div>
    <div class="moc-body">
      <div class="moc-name">Alle Medien</div>
      <div class="moc-desc">${cams.length} Kamera${cams.length !== 1 ? 's' : ''} · Gesamtarchiv</div>
      <div class="moc-counts">
        ${_buildMocChips(totalStats)}
      </div>
    </div>
  </div>`;

  const ts = Date.now();
  const camCards = cams.map((c) => _camCardHTML(c, statsByid[c.id] || {}, ts)).join('');
  const quickTiles = _QUICK_LABEL_TILES.map(_quickLabelTileHTML).join('');
  const archivedHtml = _archivedSectionHTML(state.mediaArchived || []);

  // Category filter bar — populated dynamically (see renderMediaFilterPills('overview') below)
  const catSection = `<div class="media-filter-bar moc-filter-bar" id="mediaFilterBarOverview"></div>`;

  ov.innerHTML =
    catSection +
    `<div class="media-overview-grid">${allCard}${camCards}${quickTiles}</div>` +
    archivedHtml;
  renderMediaFilterPills('overview');
  _bindQuickLabelTiles();
}

// Single source of truth for which moc-card is highlighted. data-cam-id is
// stable across re-renders; pass null/undefined to clear all (used when the
// drilldown closes or "Alle Medien" opens).
export function _setActiveMocCard(camId) {
  document.querySelectorAll('.moc-card').forEach((c) => {
    c.classList.toggle('moc-active', !!camId && c.dataset.camId === camId);
  });
}
