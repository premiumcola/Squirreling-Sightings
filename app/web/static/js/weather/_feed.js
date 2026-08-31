// ─── weather/_feed.js ───────────────────────────────────────────────────
// Card builders for every record type that renders inline in the
// unified Wetter-Ereignisse grid: sightings (auto-detected clips),
// recaps (multi-clip period summaries), Gewitter-episodes (the storm
// archive's own records), and manual events (user-saved chart ranges
// from the Wetterdaten-chart's drag-zoom). None but the sighting is a
// single event_type, so the other three ignore the sighting filter
// chips and always show — matching the old recap strip's always-visible
// behaviour. The sighting card builder moved in here from sightings.js
// when that file crossed the JS line ceiling — "how does a record
// become a grid cell" is exactly this module's concern regardless of
// which of the four record kinds it is.
import { esc, byId } from '../core/dom.js';
import { WEATHER_TYPES } from '../core/weather-types.js';
import { precipitationLabel } from '../core/weather-precip.js';
import { _LB_TRASH_ICON_ONLY } from '../mediaview/panels/lb-helpers.js';
import { pinToggleHTML } from './pin-toggle.js';
import { manualEventCategories, manualCategoryMeta } from './_manual-event-cats.js';
import { episodeSparklineSvg } from './_episode-sparkline.js';
import {
  episodeTitle,
  fmtDayMonth,
  fmtTime,
  fmtDuration,
  classMeta,
  characterMeta,
  effectiveClass,
} from '../storms/_helpers.js';

// Pick the right human-readable label for a sighting badge. For
// `heavy_rain` we band the actual current precipitation reading
// (api_snapshot.precipitation) — the static "Starkregen" from
// WEATHER_TYPES is the *event-type* name and would mislabel a card
// captured at e.g. 0.1 mm/h. For all other event types we fall back
// to the static WEATHER_TYPES label. Exported — the MediaView item
// builder (weather/_lightbox.js::_sightingItem) needs the same label.
export function sightingLabel(s, meta) {
  if (s && s.event_type === 'heavy_rain') {
    const snap = s.api_snapshot || {};
    if (snap.precipitation !== null && snap.precipitation !== undefined) {
      return precipitationLabel(snap.precipitation);
    }
  }
  return meta.de;
}

// ── Mediathek-style card chrome ───────────────────────────────────────────
// The two inline-style strings below are copied verbatim from mediaCardHTML()
// in mediathek/orchestration.js so the badge font / blur / radius match the
// Library cards 1:1 without re-exporting private constants. _WS_SUB_BADGE_BASE
// gets the event's own colour appended per card at build time.
const _WS_BADGE_STYLE =
  'font-size:10px;font-weight:700;color:#e2e8f0;background:rgba(0,0,0,.68);backdrop-filter:blur(3px);padding:2px 6px;border-radius:4px;line-height:1.45;white-space:nowrap';
const _WS_SUB_BADGE_BASE =
  'font-size:10px;background:none;backdrop-filter:blur(3px);padding:0 6px;border-radius:4px;line-height:1.45;white-space:nowrap;margin-top:1px;opacity:0.85';

// Duration m:ss + byte→KB/MB formatters — mirror Mediathek's fmtDur / fmtByt
// so the bottom-right stack reads identically to the Library cards.
function _wsFmtDur(s) {
  if (!s || s <= 0) return '';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}
function _wsFmtBytes(b) {
  if (!b || b <= 0) return '';
  if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB';
  return Math.round(b / 1024) + ' KB';
}

// Build one weather-sighting card, mirroring the Mediathek media-card:
// type badge + score top-left, hover-reveal delete top-right, date/time
// bottom-left, duration/size bottom-right. `idx` is the absolute index into
// the filtered list (data-idx → lightbox prev/next); `isActive` is false
// when the camera was removed — that dims the card and swaps the thumb for
// the striped orphan placeholder.
export function sightingCardHTML(s, idx, isActive) {
  const meta = WEATHER_TYPES[s.event_type] || { de: s.event_type, color: '#94a3b8', icon: '' };
  // Sun-timelapse cards prefer the real sunrise/sunset time over the
  // window-end timestamp; older records without sun_event_at fall back.
  const t = new Date(s.sun_event_at || s.started_at);
  const dateLabel = t.toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
  });
  const timeLabel = t.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  const sevPct = Math.round((s.score || s.severity || 0) * 100);
  // The percentage means different things per type; the same text feeds the
  // tap-to-explain toast since title= doesn't surface on touch.
  const isSunTl = typeof s.event_type === 'string' && s.event_type.startsWith('sun_timelapse');
  const scoreTip = isSunTl
    ? 'Himmelsqualität · 100% = klarer Himmel, 50% = stark bewölkt'
    : 'Stärke des Wetterereignisses';
  const color = meta.color || '#94a3b8';
  const subBadge = `${_WS_SUB_BADGE_BASE};color:${color}`;
  const displayLabel = sightingLabel(s, meta);
  const durLabel = _wsFmtDur(s.duration_s);
  const sizeLabel = _wsFmtBytes(s.file_size_bytes);
  const thumbHtml = isActive
    ? `<img class="ws-card-thumb" loading="lazy" src="/api/weather/sightings/${encodeURIComponent(s.id)}/thumb" alt="${esc(displayLabel)}" onerror="this.style.opacity=0.2"/>`
    : `<div class="ws-card-thumb ws-card-thumb--orphan" aria-hidden="true"></div>`;
  const scoreChip =
    sevPct > 0
      ? `<span class="ws-score-chip" role="button" tabindex="0" style="pointer-events:auto" title="${esc(scoreTip)}" aria-label="${sevPct} Prozent, ${esc(scoreTip)}" data-score-tip="${esc(scoreTip)}">${sevPct}%<span class="ws-score-info" aria-hidden="true">ⓘ</span></span>`
      : '';
  const rightStack =
    durLabel || sizeLabel
      ? `<div class="ws-card-stack ws-card-stack--r">${durLabel ? `<div style="${_WS_BADGE_STYLE}">${durLabel}</div>` : ''}${sizeLabel ? `<div style="${subBadge}">${sizeLabel}</div>` : ''}</div>`
      : '';
  return `
      <div class="ws-card${isActive ? '' : ' ws-card--orphan'}" data-idx="${idx}" data-id="${esc(s.id)}">
        <div class="ws-card-thumb-wrap">
          ${thumbHtml}
          <span class="ws-card-play">
            <svg viewBox="0 0 24 24" width="34" height="34" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>
          </span>
          <div class="ws-card-cluster">
            <span class="mmc-tl-badge ws-type-badge" style="border-color:${color}b3;color:${color}"><span class="ws-card-badge-icon">${meta.icon}</span>${esc(displayLabel)}</span>
            ${scoreChip}
          </div>
          <div class="ws-card-stack ws-card-stack--l">
            <div style="${_WS_BADGE_STYLE}">${dateLabel}</div>
            <div style="${subBadge}">${timeLabel}</div>
          </div>
          ${rightStack}
          <div class="mmc-actions">
            ${pinToggleHTML(s)}
            <button type="button" class="mmc-btn mmc-delete" title="Löschen" aria-label="Löschen">${_LB_TRASH_ICON_ONLY}</button>
          </div>
        </div>
      </div>`;
}

export function recapCardHTML(m, idx) {
  const dur = parseInt(m.duration_s || 0, 10);
  const mm = Math.floor(dur / 60),
    ss = dur % 60;
  const durLbl = `${mm}:${ss.toString().padStart(2, '0')} min`;
  return `
      <div class="ws-recap-card" data-recap-idx="${idx}" data-id="${esc(m.id)}">
        <div class="ws-recap-card-period">${esc(m.period_label || m.id)}</div>
        <div class="ws-recap-card-meta">${m.n_clips || 0} Clips · ${esc(durLbl)}</div>
        <span class="ws-recap-card-play" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>
        </span>
      </div>`;
}

// A card into the Gewitter-Archiv's own detail view (storms/index.js's
// hash router), not the MediaView lightbox — an episode is a whole
// window with compare/footage/notes, not a single playable clip.
export function episodeCardHTML(ep) {
  const meta = classMeta(effectiveClass(ep));
  const fc = ep.footage_count;
  const metaLine = [
    fmtDayMonth(ep.started_at),
    fmtTime(ep.started_at),
    fmtDuration(ep.duration_min),
    Number.isFinite(Number(fc)) && Number(fc) > 0 ? `${fc} Aufnahmen` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  // The curve's own SHAPE, alongside (never instead of) the alarm-class
  // icon in the play slot. Absent on a bare fixture or a record from
  // before this feature existed — both render no badge / no sparkline
  // rather than a placeholder.
  const charMeta = ep.character ? characterMeta(ep.character) : null;
  const characterHTML = charMeta
    ? `<div class="ws-ep-character" title="${esc(charMeta.de)}">` +
      `<span class="ws-ep-character-icon" aria-hidden="true">${charMeta.icon}</span>` +
      `<span class="ws-ep-character-label">${esc(charMeta.de)}</span></div>`
    : '';
  const spark = episodeSparklineSvg(ep.curve_preview, meta.color);
  const sparkHTML = spark ? `<div class="ws-ep-spark-wrap">${spark}</div>` : '';
  return `
      <div class="ws-recap-card" data-ep-id="${esc(ep.id)}">
        <div class="ws-recap-card-period">${esc(episodeTitle(ep))}</div>
        <div class="ws-recap-card-meta">${esc(metaLine)}</div>
        ${characterHTML}
        ${sparkHTML}
        <span class="ws-recap-card-play" aria-hidden="true">${meta.icon}</span>
      </div>`;
}

// A user-saved chart range (the Wetterdaten-chart's drag-zoom "als
// Ereignis speichern" action) — its categories drive the badge
// icons/colours via the SAME WEATHER_TYPES map every other event card
// uses, so a manual event reads as an ordinary weather event, not a
// bolted-on fourth visual identity. Clicking it re-draws the chart for
// exactly this saved range/curves
// (weather/_manual-events.js::openManualEventView).
//
// One event can carry up to three categories (a thunderstorm that also
// brings heavy rain). They stack VERTICALLY in the same right-hand slot
// the single badge always occupied: the card is only ~140 px wide on an
// iPhone SE, so a horizontal row would eat the name — a column costs no
// width at all and stays inside the card's 84 px min-height. A
// one-category card therefore looks exactly as it always did. The full
// German labels ride along as the slot's accessible name and the card's
// tooltip; the detail modal spells them out in text.
export function manualEventCardHTML(m) {
  const metas = manualEventCategories(m).map(manualCategoryMeta);
  const primary = metas[0] || manualCategoryMeta('');
  const metaLine = [
    fmtDayMonth(m.range_start),
    `${fmtTime(m.range_start)}–${fmtTime(m.range_end)}`,
    m.curves && m.curves.length ? `${m.curves.length} Kurven` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const catLabel = metas.map((meta) => meta.de).join(' · ');
  const badges = metas
    .map((meta) => `<span class="ws-manual-cat" style="--cb:${meta.color}">${meta.icon}</span>`)
    .join('');
  return `
      <div class="ws-recap-card ws-manual-card" data-manual-id="${esc(m.id)}" title="${esc(catLabel)}">
        <div class="ws-recap-card-period">${esc(m.name || primary.de)}</div>
        <div class="ws-recap-card-meta">${esc(metaLine)}</div>
        <span class="ws-manual-cats" data-n="${metas.length}" role="img" aria-label="${esc(catLabel)}">${badges}</span>
      </div>`;
}

// Jump into the Gewitter-Archiv's own detail state for this episode.
// The hash isn't an element id, so a plain <a href> would silently
// leave the viewport where it was — storms/index.js's hashchange
// listener still renders the detail, just off-screen, without this.
export function openStormEpisode(id) {
  if (!id) return;
  location.hash = `#/gewitter/${encodeURIComponent(id)}`;
  byId('storms')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
