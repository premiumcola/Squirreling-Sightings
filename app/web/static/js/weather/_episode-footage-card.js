// ─── weather/_episode-footage-card.js ──────────────────────────────────
// Footage-primary rendering for an episode card — split out of
// `_feed.js::episodeCardHTML` because this branch alone (thumbnail +
// play affordance + date/time overlay + the character/curve footer)
// would push that function past the 60-line ceiling, and because it is
// genuinely a different card SHELL, not a variant of the curve-only
// one: `.ws-card` (the 16:9 thumbnail shell `sightingCardHTML` already
// uses), not `.ws-recap-card` (the text-only shell the curve-only
// fallback keeps using, unchanged).
//
// The operator's ask, stated precisely: the recording that happened
// during the storm is the PRIMARY visual; the character badge + the
// curve become a smaller add-on attached to it. That maps onto this
// shell as thumbnail (primary, fills the card) + a footer strip below
// it (badge + sparkline, secondary) — not corner overlays competing
// with the image the way the badge/score chip do on a sighting card,
// because here the badge+curve are meant to read as one attached
// strip, not scattered chrome.
//
// Reuses, never reinvents:
//   - `_WS_BADGE_STYLE` / `_WS_SUB_BADGE_BASE` (weather/_card-style.js)
//     for the date/time corner badges, so they match every other
//     card's bottom-left stack pixel for pixel.
//   - `episodeSparklineSvg` (weather/_episode-sparkline.js) for the
//     curve — no second curve implementation.
//   - the `.ws-card` / `.ws-card-thumb-wrap` / `.ws-card-thumb` /
//     `.ws-card-play` / `.ws-card-stack` CSS vocabulary
//     (19-weather-1.css) `sightingCardHTML` already established —
//     this card is visually "a video card with a curve footer", not a
//     third design language.
//
// Click target: the WHOLE card still opens the full Gewitter-Archiv
// episode detail (library/_bind.js::_bindEpisodeCards →
// openStormEpisode), unchanged. That view already renders this exact
// clip inline via storms/_footage.js alongside the full chart,
// compare tools and notes — stealing the tap into a second, separate
// inline player here would duplicate storms/_footage.js's own opener
// logic (a file this task explicitly leaves untouched) for a strictly
// worse viewing context. The play icon is therefore a visual
// affordance only (`.ws-card-play` is already `pointer-events:none`
// in CSS), not a second tap target — one 44px+ touch target, the
// whole card, exactly like every other kind's card in this grid.
import { esc } from '../core/dom.js';
import { episodeSparklineSvg } from './_episode-sparkline.js';
import { fmtDayMonth, fmtTime } from '../storms/_helpers.js';
import { _WS_BADGE_STYLE, _WS_SUB_BADGE_BASE } from './_card-style.js';

// Same play-triangle path already used inline in sightingCardHTML
// (this file) and storms/_footage.js's own PLAY_ICON — kept as a local
// literal rather than imported, matching how each of those two
// existing call sites already carries its own copy rather than sharing
// one constant across packages.
const _PLAY_ICON =
  '<svg viewBox="0 0 24 24" width="34" height="34" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';

function _heroThumbHTML(hero) {
  const playable = !!hero.thumb_url && !!hero.video_url;
  const thumb = hero.thumb_url
    ? `<img class="ws-card-thumb" loading="lazy" src="${esc(hero.thumb_url)}" alt="" onerror="this.style.opacity=0.2"/>`
    : '<div class="ws-card-thumb ws-card-thumb--orphan" aria-hidden="true"></div>';
  return `${thumb}${playable ? `<span class="ws-card-play">${_PLAY_ICON}</span>` : ''}`;
}

function _heroFootHTML(characterHTML, sparkHTML) {
  if (!characterHTML && !sparkHTML) return '';
  return `<div class="ws-ep-foot">${characterHTML}${sparkHTML}</div>`;
}

/**
 * The footage-primary episode card. `characterHTML` is passed in
 * (built once by the caller, `_feed.js::episodeCardHTML`) rather than
 * recomputed here, so the character-badge markup exists in exactly one
 * place regardless of which shell an episode renders through.
 */
export function episodeFootageCardHTML(ep, meta, characterHTML) {
  const hero = ep.footage_hero;
  const dateLabel = fmtDayMonth(ep.started_at);
  const timeLabel = fmtTime(ep.started_at);
  const spark = episodeSparklineSvg(ep.curve_preview, meta.color);
  const sparkHTML = spark ? `<div class="ws-ep-spark-wrap">${spark}</div>` : '';
  return `
      <div class="ws-card ws-card--episode" data-ep-id="${esc(ep.id)}">
        <div class="ws-card-thumb-wrap">
          ${_heroThumbHTML(hero)}
          <div class="ws-card-stack ws-card-stack--l">
            <div style="${_WS_BADGE_STYLE}">${esc(dateLabel)}</div>
            <div style="${_WS_SUB_BADGE_BASE};color:${meta.color || '#94a3b8'}">${esc(timeLabel)}</div>
          </div>
        </div>
        ${_heroFootHTML(characterHTML, sparkHTML)}
      </div>`;
}
