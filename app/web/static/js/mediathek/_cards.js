// ─── mediathek/_cards.js ───────────────────────────────────────────────────
// R23 split of orchestration.js — owns the tile markup for one media item
// and nothing else. Pure string builders: no DOM reads, no state writes, no
// fetches, so the grid renderer can map over a list without side effects.
//
// mediaCardHTML() is the single entry point and dispatches into three
// branches, which is why it was split out — the combined function ran ~170
// lines against CLAUDE.md's 60-line ceiling:
//   * timelapse  → _tlCardHTML          (own thumb, duration, delete-only)
//   * processing → processingTileHTML   (lives in _processing.js)
//   * motion     → _motionCardHTML      (player inner or still inner)
//
// The per-item colour + date helpers live here too because the card is
// their only consumer; the inline onclicks stay as window.* lookups (the
// handlers are in _actions.js, bridged from orchestration.js).
import { esc, hexToRgba } from '../core/dom.js';
import { state } from '../core/state.js';
import { speciesChipText, subjectLabel } from '../core/clip-species.js';
import { colors, objIconSvg, objBubble } from '../core/icons.js';
import { primaryLabel } from '../core/primary-label.js';
import { _LB_TRASH_ICON_ONLY } from '../mediaview/panels/lb-helpers.js';
import { needsProcessingTile, processingTileHTML } from './_processing.js';

// ── Per-camera tints + helpers ──────────────────────────────────────────────
export const CAM_COLORS = [
  '#3b82f6',
  '#f59e0b',
  '#10b981',
  '#8b5cf6',
  '#ef4444',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
];
export function camColor(camId) {
  const idx = state.cameras.findIndex((c) => c.id === camId);
  return CAM_COLORS[(idx < 0 ? 0 : idx) % CAM_COLORS.length];
}
export function getMediaAccentColor(labels) {
  if (Array.isArray(labels)) {
    // `motion` is the fallback bucket, never a real match — same rule
    // core/primary-label.js::primaryLabel already applies for the badge
    // text. Without this, an event tagged `["motion", "person"]` (motion
    // fired first, classified as a person afterwards) hit `colors.motion`
    // before ever reaching `person`, so the play button rendered grey
    // while the badge right next to it correctly said "Person" — two
    // helpers reading the same `labels` array and disagreeing.
    for (const l of labels) {
      if (l !== 'motion' && colors[l]) return colors[l];
    }
  }
  return colors.motion || '#93c5fd';
}
export function fmtMediaDate(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts.replace(' ', 'T'));
    return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return '';
  }
}
export function fmtMediaTimeOnly(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts.replace(' ', 'T'));
    return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

// ── Shared badge styling ────────────────────────────────────────────────────
// Primary (bold white) badge — shared across all card types
const _BADGE_STYLE =
  'font-size:10px;font-weight:700;color:#e2e8f0;background:rgba(0,0,0,.68);backdrop-filter:blur(3px);padding:2px 6px;border-radius:4px;line-height:1.45;white-space:nowrap';
// Secondary (dimmer, accent-colored) badge — color added per-branch via accent
const _SUB_BADGE_BASE =
  'font-size:10px;background:none;backdrop-filter:blur(3px);padding:0 6px;border-radius:4px;line-height:1.45;white-space:nowrap;margin-top:1px;opacity:0.85';

function _fmtDur(s) {
  if (!s || s <= 0) return '';
  const m = Math.floor(s / 60),
    sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}
function _fmtByt(b) {
  if (!b || b <= 0) return '';
  if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB';
  return Math.round(b / 1024) + ' KB';
}

// Bottom-left date/time stack — identical geometry on every branch.
function _dateTimeBadges(date, time, subBadge) {
  if (!date && !time) return '';
  return `<div style="position:absolute;bottom:7px;left:8px;z-index:2;pointer-events:none;width:fit-content">
        ${date ? `<div style="${_BADGE_STYLE}">${esc(date)}</div>` : ''}
        ${time ? `<div style="${subBadge}">${esc(time)}</div>` : ''}
      </div>`;
}

// ── Timelapse branch ────────────────────────────────────────────────────────
function _tlCardHTML(item) {
  const wk = item.window_key || item.day || '';
  const datePart = wk.substring(0, 10);
  const timePart = wk.length >= 15 ? wk.substring(11, 13) + ':' + wk.substring(13, 15) : '';
  const durLabel =
    item.target_s != null
      ? item.target_s < 60
        ? item.target_s + 's'
        : Math.floor(item.target_s / 60) + 'min'
      : '';
  const sizeText = item.size_mb != null ? item.size_mb + ' MB' : '';
  const thumbSrc = item.thumb_url || '';
  const thumbEl = thumbSrc
    ? `<img src="${esc(thumbSrc)}" alt="preview" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:inherit;opacity:.7" loading="lazy" onerror="this.remove()">`
    : '';
  const tlAccent = getMediaAccentColor(['timelapse']);
  const tlPlayBg = hexToRgba(tlAccent, 0.18);
  const tlPlayBorder = hexToRgba(tlAccent, 0.5);
  const tlSubBadge = `${_SUB_BADGE_BASE};color:${tlAccent}`;
  return `<article class="media-card mmc-tl" data-event-id="${esc(item.event_id || '')}" data-camera-id="${esc(item.camera_id || '')}">
      <div class="mmc-img-wrap" onclick="window._openMediaItem('${esc(item.event_id || '')}')">
        ${thumbEl}
        <div style="position:absolute;inset:0;z-index:1;display:flex;align-items:center;justify-content:center">
          <div class="mmc-play-btn" style="background:${tlPlayBg};border:1.5px solid ${tlPlayBorder}"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="color:${tlAccent};margin-left:2px"><polygon points="5,3 19,12 5,21"/></svg></div>
        </div>
        <div style="position:absolute;bottom:7px;left:8px;z-index:2;pointer-events:none;width:fit-content">
          ${datePart ? `<div style="${_BADGE_STYLE}">${esc(datePart)}</div>` : ''}
          ${timePart ? `<div style="${tlSubBadge}">${esc(timePart)}</div>` : ''}
        </div>
        ${
          durLabel || sizeText
            ? `<div style="position:absolute;bottom:7px;right:8px;z-index:2;pointer-events:none;display:flex;flex-direction:column;align-items:flex-end;gap:2px">
          ${durLabel ? `<div style="${_BADGE_STYLE}">${esc(durLabel)}</div>` : ''}
          ${sizeText ? `<div style="${tlSubBadge}">${esc(sizeText)}</div>` : ''}
        </div>`
            : ''
        }
        <div style="position:absolute;top:6px;left:6px;z-index:2"><span class="mmc-tl-badge">${objIconSvg('timelapse', 12)}Timelapse</span></div>
        <div class="mmc-actions" style="z-index:3">
          <button class="mmc-btn mmc-delete" title="Löschen" onclick="event.stopPropagation();window.deleteTLCard('${esc(item.camera_id || '')}','${esc(item.filename || '')}','${esc(item.event_id || '')}')">${_LB_TRASH_ICON_ONLY}</button>
        </div>
      </div>
    </article>`;
}

// ── Motion branch — per-item derived values shared by both inner builders ───
function _motionCtx(item) {
  const accent = getMediaAccentColor(item.labels);
  // Top-left badge names the event's ONE triggering label — same helper
  // the recorded bbox overlay's class filter now uses (core/primary-label.js,
  // mirrors app/app/labels.py::primary_label()) so the badge and the boxes
  // that draw over the video always name the same subject.
  const badgeLabel = primaryLabel(item.labels);
  const badgeColor = colors[badgeLabel] || colors.motion || '#93c5fd';
  // When the bird classifier has identified a species, show it instead of the
  // generic "Vogel" — keeps bird colour + icon but tells the user what kind.
  // The rule lives in core/clip-species.js because the player's object rows
  // now ask the same question of the same data.
  const badgeText = subjectLabel(badgeLabel, item.bird_species);
  // The headline stays ONE species — that ranking is deliberate. A clip
  // that held more than one says so underneath, quietly, and a clip that
  // held exactly one grows nothing at all.
  const moreSpecies = speciesChipText(item, badgeText);
  const speciesChip = moreSpecies
    ? `<span class="mmc-species-more">${esc(moreSpecies)}</span>`
    : '';
  return {
    accent,
    subBadge: `${_SUB_BADGE_BASE};color:${accent}`,
    imgSrc: item.snapshot_relpath ? `/media/${item.snapshot_relpath}` : item.snapshot_url || '',
    vidDate: fmtMediaDate(item.time || ''),
    vidTime: fmtMediaTimeOnly(item.time || ''),
    vidDur: _fmtDur(item.duration_s),
    vidSize: _fmtByt(item.file_size_bytes),
    // Inline overrides only border-color and text color; .mmc-tl-badge supplies dark bg + blur + shadow
    motionBadge: `<div class="mmc-badges"><span class="mmc-tl-badge" style="border-color:${hexToRgba(badgeColor, 0.7)};color:${badgeColor}">${objIconSvg(badgeLabel, 12)}${esc(badgeText)}</span>${speciesChip}</div>`,
  };
}

// Finished clip (or one that failed to encode) — poster + play button.
function _playerInnerHTML(item, ctx) {
  const playBg = hexToRgba(ctx.accent, 0.18);
  const playBorder = hexToRgba(ctx.accent, 0.5);
  const errorBadge = item.encode_error
    ? `<div style="position:absolute;bottom:7px;left:50%;transform:translateX(-50%);z-index:4"><span title="${esc(item.encode_error)}" style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:rgba(250,204,21,.18);border:1px solid rgba(250,204,21,.5);color:#facc15;font-size:13px;font-weight:800;backdrop-filter:blur(4px)">⚠</span></div>`
    : '';
  const videoThumbEl = ctx.imgSrc
    ? `<img src="${esc(ctx.imgSrc)}" alt="preview" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.7" loading="lazy" onerror="this.remove()">`
    : '';
  return `<div style="position:absolute;inset:0;background:#0a0e1a">${videoThumbEl}</div>
      <div style="position:absolute;inset:0;z-index:1;display:flex;align-items:center;justify-content:center">
        <div class="mmc-play-btn" style="background:${playBg};border:1.5px solid ${playBorder}"><svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style="color:${ctx.accent};margin-left:3px"><polygon points="5,3 19,12 5,21"/></svg></div>
      </div>
      ${_dateTimeBadges(ctx.vidDate, ctx.vidTime, ctx.subBadge)}
      ${
        ctx.vidDur || ctx.vidSize
          ? `<div style="position:absolute;bottom:7px;right:8px;z-index:2;pointer-events:none;display:flex;flex-direction:column;align-items:flex-end;gap:2px">
        ${ctx.vidDur ? `<div style="${_BADGE_STYLE}">${ctx.vidDur}</div>` : ''}
        ${ctx.vidSize ? `<div style="${ctx.subBadge}">${ctx.vidSize}</div>` : ''}
      </div>`
          : ''
      }
      ${ctx.motionBadge}
      ${errorBadge}`;
}

// Snapshot-only event — no clip was ever written.
function _stillInnerHTML(ctx) {
  return `<img src="${esc(ctx.imgSrc)}" alt="event" loading="lazy" onerror="this.style.display='none'" />
      ${_dateTimeBadges(ctx.vidDate, ctx.vidTime, ctx.subBadge)}
      ${
        ctx.vidSize
          ? `<div style="position:absolute;bottom:7px;right:8px;z-index:2;pointer-events:none;display:flex;flex-direction:column;align-items:flex-end;gap:2px">
        <div style="${ctx.subBadge}">${ctx.vidSize}</div>
      </div>`
          : ''
      }`;
}

// A clip that isn't finished has nothing to open and nothing to
// confirm — the tile itself is the interaction (it toggles its stage
// detail), and delete is the only action that still means something.
// Its own badge already names the label, so the bubble row would say
// the same thing twice.
function _cardActionsHTML(item, isProcessing) {
  if (isProcessing) {
    return `<div class="mmc-actions">
        <button class="mmc-btn mmc-delete" title="Löschen" onclick="event.stopPropagation();window.deleteMediaCard(this)">${_LB_TRASH_ICON_ONLY}</button>
      </div>`;
  }
  if (item.confirmed) return `<span class="media-confirmed-badge">✓</span>`;
  return `<div class="mmc-actions">
        <button class="mmc-btn mmc-confirm" title="Bestätigen" onclick="event.stopPropagation();window.confirmMediaCard('${esc(item.camera_id || '')}','${esc(item.event_id || '')}',this)">✓</button>
        <button class="mmc-btn mmc-delete" title="Löschen" onclick="event.stopPropagation();window.deleteMediaCard(this)">${_LB_TRASH_ICON_ONLY}</button>
      </div>`;
}

function _motionCardHTML(item) {
  const isProcessing = needsProcessingTile(item);
  const hasVideo = !!(item.video_relpath || item.video_url);
  const showPlayer = hasVideo || !!item.encode_error;
  const confirmed = item.confirmed ? 'mmc-confirmed' : '';
  const labelBubbles = (item.labels || [])
    .slice(0, 3)
    .map((l) => objBubble(l, 26))
    .join('');
  const ctx = _motionCtx(item);
  const mediaInner = isProcessing
    ? processingTileHTML(item, ctx.motionBadge)
    : showPlayer
      ? _playerInnerHTML(item, ctx)
      : _stillInnerHTML(ctx);
  const wrapClick = isProcessing
    ? ''
    : ` onclick="window._openMediaItem('${esc(item.event_id || '')}')"`;
  return `<article class="media-card ${confirmed}" data-event-id="${esc(item.event_id || '')}" data-camera-id="${esc(item.camera_id || '')}">
    <div class="mmc-img-wrap"${wrapClick}>
      ${mediaInner}
      ${showPlayer || isProcessing ? '' : `<div class="media-label-bubbles">${labelBubbles}</div>`}
      ${_cardActionsHTML(item, isProcessing)}
    </div>
  </article>`;
}

// ── Entry point ─────────────────────────────────────────────────────────────
export function mediaCardHTML(item) {
  return item.type === 'timelapse' ? _tlCardHTML(item) : _motionCardHTML(item);
}
