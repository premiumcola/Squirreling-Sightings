// ─── library/_timelapse-card.js ─────────────────────────────────────────
// Stage 4 of the Mediathek + Wetter-Ereignisse merge: the ONE card kind
// with no pre-existing builder to adapt into. `mediathek/_cards.js`'s
// private `_tlCardHTML` renders a DIFFERENT normalised shape — the
// per-camera media-browser's own timelapse rows (`window_key`, `day`,
// `target_s`, `size_mb`, `filename` — see `media_index/_timelapse.py`).
// A `/api/library` timelapse item is one daily/rolling MP4 straight from
// `weather_episodes._footage_sources.timelapse_candidates`, whose
// `extra` is just `{"profile": "..."}`; everything else the card needs
// (cam name, span, thumb, video) already lives on the item's own
// top-level fields (see `library._weather_readers` module docstring —
// this is the one library kind whose `extra` really is tiny, not a full
// manifest, so this builder reads the TOP-LEVEL item, not `item.extra`).
//
// Visually mirrors mediathek's own tl-card chrome (same `.mmc-*` classes,
// same play-button treatment) so a timelapse tile looks like a timelapse
// tile regardless of which grid it landed in — no new CSS needed for
// this stage, which never mounts into a real page anyway.
import { esc, hexToRgba } from '../core/dom.js';
import { objIconSvg, colors } from '../core/icons.js';

const _BADGE_STYLE =
  'font-size:10px;font-weight:700;color:#e2e8f0;background:rgba(0,0,0,.68);backdrop-filter:blur(3px);padding:2px 6px;border-radius:4px;line-height:1.45;white-space:nowrap';

function _dateLabel(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' });
}
function _timeLabel(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

/**
 * One `/api/library` item of kind "timelapse" as a grid card. Takes the
 * item itself (not an adapted sub-shape) — see the module comment for why.
 */
export function timelapseCardHTML(item) {
  const accent = colors.timelapse || '#a855f7';
  const playBg = hexToRgba(accent, 0.18);
  const playBorder = hexToRgba(accent, 0.5);
  const thumb = item.thumb_url
    ? `<img src="${esc(item.thumb_url)}" alt="Zeitraffer" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.7" loading="lazy" onerror="this.remove()">`
    : '';
  const camName = item.cam_name || item.cam_id || '';
  const date = _dateLabel(item.start);
  const time = _timeLabel(item.start);
  return `<article class="media-card mmc-tl" data-lib-id="${esc(item.id || '')}">
      <div class="mmc-img-wrap">
        <div style="position:absolute;inset:0;background:#0a0e1a">${thumb}</div>
        <div style="position:absolute;inset:0;z-index:1;display:flex;align-items:center;justify-content:center">
          <div class="mmc-play-btn" style="background:${playBg};border:1.5px solid ${playBorder}"><svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style="color:${accent};margin-left:3px"><polygon points="5,3 19,12 5,21"/></svg></div>
        </div>
        <div style="position:absolute;bottom:7px;left:8px;z-index:2;pointer-events:none;width:fit-content">
          ${date ? `<div style="${_BADGE_STYLE}">${esc(date)}</div>` : ''}
          ${time ? `<div style="${_BADGE_STYLE};color:${accent};background:none;opacity:.85">${esc(time)}</div>` : ''}
        </div>
        <div style="position:absolute;top:6px;left:6px;z-index:2"><span class="mmc-tl-badge">${objIconSvg('timelapse', 12)}${esc(camName)}</span></div>
      </div>
    </article>`;
}
