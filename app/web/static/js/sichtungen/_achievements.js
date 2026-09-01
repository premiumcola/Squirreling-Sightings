// ─── sichtungen/_achievements.js ─────────────────────────────────────────
// The species achievement grid (medal SVGs, bronze/silver/gold tiers,
// the progress bar) — split out of the former sichtungen.js monolith.
//
// Tile click routing (2026-08-31 species-dossier redesign):
//   * bird tile (locked OR unlocked)  → the species dossier panel
//     (_dossier-panel.js) — a locked bird still has a pre-built
//     reference dossier once the daily prebuild sweep has reached it
//     (bird_dossiers.py::sweep_prebuild), so even a never-detected
//     species shows something immediately.
//   * unlocked mammal tile            → the clips-only accordion
//     (_drilldown.js) — mammals have no dossier data at all
//     (bird_dossiers.py is bird-only), so there is nothing to show
//     beyond the camera clips.
//   * locked mammal tile              → not clickable, unchanged.
import { byId, esc } from '../core/dom.js';
import { BIRD_SVGS, MAMMAL_SVGS } from '../core/animal-icons.js';
import { ACH_DEFS, _achTier, _rarityText } from './_ach-defs.js';
import { _currentAchOpenId, _reflowAchDrilldownIfOpen } from './_drilldown.js';
import { isSpeciesDossierActive } from './_dossier-panel.js';

let _achData = {};

export function setAchievementsData(achData) {
  _achData = achData || {};
}

function _medalSVG(achId, tier, birdSvg, isUnlocked, size = 88) {
  const uid = achId.replaceAll(/[^a-z0-9]/g, '');
  // Locked medals are deliberately drab: two flat neutral greys, no
  // highlight arc. The silhouette is rendered faintly so the shape is
  // still recognisable without announcing itself.
  if (!isUnlocked) {
    let silhouette = '';
    if (birdSvg) {
      silhouette = birdSvg.replace(
        '<svg ',
        '<svg x="10" y="10" width="80" height="80" style="filter:grayscale(1) brightness(0.18) opacity(0.45)" ',
      );
    }
    return `<svg viewBox="0 0 100 100" width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">
      <circle cx="50" cy="50" r="47" fill="rgba(255,255,255,0.06)"/>
      <circle cx="50" cy="50" r="36" fill="rgba(255,255,255,0.03)"/>
      <circle cx="50" cy="50" r="36" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
      ${silhouette}
    </svg>`;
  }
  const rimC = {
    bronze: ['#4a2408', '#c87840'],
    silver: ['#303840', '#a0b4c4'],
    gold: ['#402e08', '#e0c050'],
  };
  const faceC = {
    bronze: ['#3a2010', '#1e0e04'],
    silver: ['#202e38', '#101820'],
    gold: ['#2a2010', '#140e04'],
  };
  const hlC = { bronze: '#e09860', silver: '#c0d0e0', gold: '#f0e060' };
  const [rc, re] = rimC[tier];
  const [fc, fe] = faceC[tier];
  const hl = hlC[tier];
  const bird = birdSvg
    ? birdSvg.replace('<svg ', `<svg x="10" y="10" width="80" height="80" `)
    : '';
  return `<svg viewBox="0 0 100 100" width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <radialGradient id="rg${uid}" cx="50%" cy="40%" r="55%">
        <stop offset="0%" stop-color="${rc}"/>
        <stop offset="100%" stop-color="${re}"/>
      </radialGradient>
      <radialGradient id="fg${uid}" cx="42%" cy="38%" r="65%">
        <stop offset="0%" stop-color="${fc}"/>
        <stop offset="100%" stop-color="${fe}"/>
      </radialGradient>
    </defs>
    <circle cx="50" cy="50" r="47" fill="url(#rg${uid})"/>
    <circle cx="50" cy="50" r="36" fill="url(#fg${uid})"/>
    <circle cx="50" cy="50" r="36" fill="none" stroke="${re}" stroke-width="1.5" opacity=".5"/>
    <path d="M 25 30 A 28 28 0 0 1 70 22" fill="none" stroke="${hl}" stroke-width="5" stroke-linecap="round" opacity=".35"/>
    ${bird}
  </svg>`;
}

// Icon-based bronze/silver/gold legend — moved here from its old spot
// below the grid (ask #1) to replace the plain-text "Top-20 Bayern ·
// Bronze / Silber / Gold" subtitle that used to sit top-right of the
// grid header. Renders into #achievementsLegendSlot, a fixed element in
// sichtungen.html's header row — CLAUDE.md forbids showing the same
// info twice, so the old plain-text subtitle span is gone, not merely
// hidden.
function _renderLegend() {
  const slot = byId('achievementsLegendSlot');
  if (!slot) return;
  slot.innerHTML = `
    <span><span class="ach-leg-dot" style="background:#c87840"></span><span class="ach-leg-label">Bronze 1–4×</span></span>
    <span><span class="ach-leg-dot" style="background:#a0b4c4"></span><span class="ach-leg-label">Silber 5–19×</span></span>
    <span><span class="ach-leg-dot" style="background:#e0c050"></span><span class="ach-leg-label">Gold 20×+</span></span>`;
}

function _tileClickAttrs(a, isUnlocked) {
  if (a.cat === 'birds') {
    // Locked or unlocked — a pre-built or real dossier may already
    // exist (see the module docstring above). selectSpeciesDossierByName
    // itself no-ops gracefully when nothing is available yet.
    return {
      attr: `onclick="selectSpeciesDossierByName('${esc(a.name)}')" style="cursor:pointer"`,
      active: isSpeciesDossierActive(a.name),
    };
  }
  if (isUnlocked) {
    return {
      attr: `onclick="toggleAchDrilldown('${esc(a.id)}','${esc(a.name)}')" style="cursor:pointer"`,
      active: _currentAchOpenId() === a.id,
    };
  }
  return { attr: '', active: false };
}

function _renderCard(a) {
  const info = _achData[a.id];
  const isUnlocked = !!info;
  const count = isUnlocked ? info.count || 1 : 0;
  const tier = _achTier(count);
  const isSquirrelXL = a.cat === 'mammals' && a.id.startsWith('eichhoernchen_');
  const medalSize = isSquirrelXL ? 132 : 88;
  const iconSvg = a.cat === 'birds' ? BIRD_SVGS[a.id] || null : MAMMAL_SVGS[a.id] || null;
  const medalHtml = _medalSVG(a.id, tier, iconSvg, isUnlocked, medalSize);
  const emojiOverlay = !iconSvg
    ? `<span class="medal-emoji${isUnlocked ? '' : ' medal-emoji-locked'}">${isUnlocked ? a.icon : '🔒'}</span>`
    : '';
  const badge = isUnlocked
    ? `<span class="medal-count-badge ${tier}">${count}×</span>`
    : `<div class="medal-lock-overlay"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.8)" stroke-width="2.2" stroke-linecap="round"><rect x="3" y="11" width="18" height="11" rx="3"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg></div>`;
  const countColors = { bronze: '#d4894a', silver: '#90a8be', gold: '#d4a820' };
  const countSpan = isUnlocked
    ? `<span class="medal-count" style="color:${countColors[tier] || '#d4a820'}">${count}× gesehen</span>`
    : '';
  const footline = isSquirrelXL
    ? `<div class="medal-footline">${countSpan}</div>`
    : `<div class="medal-footline">${countSpan}${_rarityText(a.freq, isUnlocked)}</div>`;
  const nameParts = a.name.match(/^(.+?)\s*(\(.+\))?$/);
  const baseName = nameParts?.[1] || a.name;
  const variantSuffix = nameParts?.[2] || '';
  const nameHtml = isSquirrelXL
    ? `<div class="medal-name-base">${esc(baseName)}</div>${variantSuffix ? `<div class="medal-variant">${esc(variantSuffix)}</div>` : ''}`
    : `${esc(baseName)}${variantSuffix ? `<span style="font-size:10px;font-weight:400;color:rgba(255,255,255,0.3);font-style:italic;margin-left:3px">${esc(variantSuffix)}</span>` : ''}`;
  const { attr: clickable, active } = _tileClickAttrs(a, isUnlocked);
  const xlCls = isSquirrelXL ? ' ach-card--xl' : '';
  return `<div class="ach-card ${tier}${active ? ' ach-card--active' : ''}${xlCls}" ${clickable}>
    <div class="medal-wrap">
      ${medalHtml}
      ${emojiOverlay}
      ${badge}
    </div>
    <div class="medal-name">${nameHtml}</div>
    ${footline}
  </div>`;
}

export function renderAchievements() {
  _renderLegend();
  const unlocked = ACH_DEFS.filter((a) => _achData[a.id]);
  const total = ACH_DEFS.length;
  const pct = Math.round((unlocked.length / total) * 100);
  const progressEl = byId('achievementsProgress');
  if (progressEl) {
    progressEl.innerHTML = `
      <span class="ach-progress-text">${unlocked.length} von ${total} gesichtet</span>
      <div class="ach-progress-track"><div class="ach-progress-fill" style="width:${pct}%"></div></div>
      <span class="ach-progress-pct">${pct}%</span>`;
  }

  // Pinned items (negative pin rank) come first regardless of category
  // so the Eichhörnchen variants sit at the very front. Then birds (by
  // rank), then the remaining mammals (by rank).
  const sorted = [...ACH_DEFS].sort((a, b) => {
    const pa = a.pin ?? 0,
      pb = b.pin ?? 0;
    if (pa !== pb) return pa - pb;
    const catOrder = (a.cat === 'birds' ? 0 : 1) - (b.cat === 'birds' ? 0 : 1);
    if (catOrder) return catOrder;
    return (a.rank || 99) - (b.rank || 99);
  });
  const cards = sorted.map(_renderCard).join('');
  // Drilldown accordion (mammal clips-only) — sits between the grid and
  // the (now header-hosted) legend so an open card's context stays close.
  const drilldown = `
    <div class="ach-drilldown-wrap${_currentAchOpenId() ? ' ach-drilldown-wrap--open' : ''}" id="achDrilldownWrap">
      <div class="ach-drilldown">
        <div class="ach-drill-header">
          <div class="ach-drill-title">🌿 <span id="achDrillName"></span></div>
          <span class="ach-drill-count" id="achDrillCount"></span>
          <button type="button" class="ach-drill-close" onclick="closeAchDrilldown()" aria-label="Schließen">✕</button>
        </div>
        <div class="ach-drill-grid" id="achDrillGrid"></div>
        <div class="ach-drill-more" id="achDrillMore" style="display:none">
          <button type="button" class="btn-action" onclick="loadMoreAchDrill()">Mehr laden</button>
        </div>
      </div>
    </div>`;
  const grid = byId('achievementsGrid');
  if (grid) {
    grid.innerHTML = `<div class="ach-cards-grid">${cards}</div>${drilldown}`;
  }
  // If we re-rendered while a mammal drilldown was open, re-populate it
  // from the in-memory cache instead of showing "Lade…" again.
  _reflowAchDrilldownIfOpen();
}
