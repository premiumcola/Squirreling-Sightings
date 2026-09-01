// ─── library/_filter-chips.js ───────────────────────────────────────────
// Pure HTML builders for the three /api/library/facets-scoped chip rows
// (camera / object-class / weather-category). Split out of
// _filter-bar.js so this half stays leaf/testable — every import here
// (`core/icons.js`, `timeline.js::CAT_COLORS`, `core/weather-types.js`)
// loads cleanly under this repo's plain-node test harness on its own;
// the one vocabulary that does NOT (`MEDIA_FILTER_LABELS`, which only
// `mediathek/filters.js` exports, and importing THAT drags in the whole
// Mediathek module graph — `window.addEventListener` calls at module-
// load time that the harness's minimal `window` stub doesn't have) is
// taken as a plain array PARAMETER instead, so a test can hand these
// builders a small hand-built list without paying that cost. The
// orchestrator, _filter-bar.js, still imports the real constant and
// passes it through — one vocabulary, per CLAUDE.md's dedupe rule, just
// not imported from this file.
//
// A chip is visible when it would show something OR is already the
// user's own active selection — `count === 0` and inactive is exactly
// "would match nothing", the case the operator asked to hide entirely
// ("sollten dann gar nicht angezeigt werden"); `count === 0` and active
// stays on screen so a chip never vanishes out from under the tap that
// just turned it on. A whole row (the `<div class="media-filter-bar">`
// wrapper) renders as '' — omitted entirely, not an empty shell — once
// none of its chips clear that bar, which is what makes an entire
// dimension disappear when it is structurally irrelevant to the active
// `kinds` scope: the facets response already comes back with an empty
// dict for that dimension in that case (see `_facets.py`'s own
// `_resolve_want` narrowing), so no chip in the row ever qualifies.
import { esc } from '../core/dom.js';
import { getCameraIcon, getCameraColor, objIconSvg, OBJ_LABEL } from '../core/icons.js';
import { CAT_COLORS } from '../timeline.js';
import { WEATHER_TYPES } from '../core/weather-types.js';

export function chipVisible(count, active) {
  return (count || 0) > 0 || !!active;
}

function _chipHTML(group, val, active, iconHtml, label, color, count) {
  const cls = `media-pill cat-filter-btn${active ? ' active' : ''}`;
  const cntChip =
    count > 0 ? `<span class="mp-count" style="pointer-events:none">${count}</span>` : '';
  return (
    `<button type="button" class="${cls}" data-group="${group}" data-val="${esc(val)}" style="--cb:${color}">` +
    `<span class="cfb-icon" style="pointer-events:none">${iconHtml}</span>` +
    `<span style="pointer-events:none">${esc(label)}</span>${cntChip}</button>`
  );
}

function _rowHTML(group, entries) {
  const visible = entries.filter((e) => chipVisible(e.count, e.active));
  if (!visible.length) return '';
  const chips = visible
    .map((e) => _chipHTML(group, e.val, e.active, e.iconHtml, e.label, e.color, e.count))
    .join('');
  return `<div class="media-filter-bar" data-group="${group}">${chips}</div>`;
}

/** One chip per camera in `cameras`, badged from `counts` (facets'
 * `cameras` dict — `{cam_id: n}`). */
export function cameraChipsHTML(cameras, filter, counts) {
  const entries = (cameras || []).map((c) => ({
    val: c.id,
    active: filter.cameraIds.has(c.id),
    count: counts[c.id] || 0,
    iconHtml: getCameraIcon(c.name || c.id),
    label: c.name || c.id,
    color: getCameraColor(c),
  }));
  return _rowHTML('camera', entries);
}

/** One chip per label in `objectLabels` (the caller's vocabulary — see
 * this module's own header for why it isn't imported here), badged
 * from `counts` (facets' `labels` dict). */
export function labelChipsHTML(objectLabels, filter, counts) {
  const entries = (objectLabels || []).map((l) => ({
    val: l,
    active: filter.labels.has(l),
    count: counts[l] || 0,
    iconHtml: objIconSvg(l, 14),
    label: OBJ_LABEL[l] || l,
    color: CAT_COLORS[l] || '#94a3b8',
  }));
  return _rowHTML('label', entries);
}

/** One chip per `WEATHER_TYPES` key, badged from `counts` (facets'
 * `categories` dict). */
export function categoryChipsHTML(filter, counts) {
  const entries = Object.keys(WEATHER_TYPES).map((k) => {
    const meta = WEATHER_TYPES[k];
    return {
      val: k,
      active: filter.categories.has(k),
      count: counts[k] || 0,
      iconHtml: meta.icon,
      label: meta.de,
      color: meta.color,
    };
  });
  return _rowHTML('category', entries);
}
