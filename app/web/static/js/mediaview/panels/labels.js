// ─── mediaview/panels/labels.js ────────────────────────────────────────────
// Label-correction bubbles — tap an ALREADY-ACTIVE bubble to untoggle it,
// the "this is a Falscherkennung" gesture (see event_relabel.py on the
// backend, which both this POST and the Telegram "❌ Nein" verdict run
// through). Moved out of lightbox.js (Stage 23) so the same renderer has
// one home reachable from both surfaces that show it:
//   * the photo lightbox (recorded-mode.js::_openRecordedPhoto) — targets
//     the legacy #lightboxLabels node (absolute-positioned over the image,
//     no host arg passed, so `host` below defaults to it).
//   * the recorded-shell "Labels" tab (recorded-shell-compose.js, motion
//     clips only — timelapses carry no real classifier verdict to
//     correct) — targets the tab's own content div.
// Mirrors weather.js / recording-settings.js: one file per shell tab
// renderer, all under mediaview/panels/.
import { byId, esc } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { j } from '../../core/api.js';
import { showToast } from '../../core/toast.js';
import { colors, OBJ_LABEL, OBJ_SVG, TL_LABELS, objBubble } from '../../core/icons.js';
import { lbState } from '../../mediathek/state.js';
import { refreshTimelineAndStats } from '../../chrome/storage-stats.js';

// One bubble's markup — active state controls fill/opacity/border; the
// bird bubble additionally grows a species caption underneath while active.
function _labelBubbleHtml(l, active, species, birdColor) {
  const isActive = active.has(l);
  const rawSvg = OBJ_SVG[l] || OBJ_SVG.alarm;
  const svg = rawSvg.replace('width="16" height="16"', 'width="38" height="38"');
  const title = OBJ_LABEL[l] || l;
  const c = colors[l] || colors.unknown;
  const speciesSub =
    l === 'bird' && species && isActive
      ? `<span style="position:absolute;top:calc(100% + 4px);left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.72);color:${birdColor};font-size:11px;font-weight:700;padding:3px 8px;border-radius:8px;white-space:nowrap;border:1px solid ${birdColor}55;pointer-events:none">${esc(species)}</span>`
      : '';
  return `<span data-label="${l}" title="${title}" style="position:relative;width:54px;height:54px;border-radius:50%;background:${isActive ? c + '30' : 'rgba(0,0,0,0.60)'};filter:drop-shadow(0 2px 8px rgba(0,0,0,0.8));display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;cursor:pointer;pointer-events:auto;transition:background .15s,opacity .15s,border-color .15s;opacity:${isActive ? '1' : '0.6'};border:2px solid ${isActive ? c + 'cc' : 'rgba(255,255,255,0.08)'}">${svg}${speciesSub}</span>`;
}

// The full bubble row for `item` — one bubble per TL_LABELS entry.
function _buildLabelBubblesHtml(item) {
  const active = new Set(item.labels || []);
  const species = item.bird_species || '';
  const birdColor = colors.bird || '#0ea5e9';
  return TL_LABELS.map((l) => _labelBubbleHtml(l, active, species, birdColor)).join('');
}

// Sync the just-saved labels into every place that caches a copy of the
// event, re-render the bubbles, and nudge the thumbnail + timeline/stats
// so nothing downstream still shows the disproven label.
function _applyLabelSaveResult(res, host) {
  const applyRes = (target) => {
    target.labels = res.labels;
    if (res.top_label !== undefined) target.top_label = res.top_label;
    if ('cat_name' in res) target.cat_name = res.cat_name;
    if ('bird_species' in res) target.bird_species = res.bird_species;
  };
  applyRes(lbState.item);
  const idx = (state.media || []).findIndex((x) => x.event_id === lbState.item.event_id);
  if (idx >= 0) applyRes(state.media[idx]);
  const aIdx = (state._allMedia || []).findIndex((x) => x.event_id === lbState.item.event_id);
  if (aIdx >= 0) applyRes(state._allMedia[aIdx]);
  _renderLbLabels(host);
  // sync thumbnail in media grid
  const thumbCard = byId('mediaGrid')?.querySelector(
    `[data-event-id="${CSS.escape(lbState.item.event_id)}"]`,
  );
  if (thumbCard) {
    const bubblesEl = thumbCard.querySelector('.media-label-bubbles');
    if (bubblesEl)
      bubblesEl.innerHTML = res.labels
        .slice(0, 3)
        .map((l) => objBubble(l, 26))
        .join('');
  }
  // Re-pull timeline + storage stats so badges and dots reflect the retag.
  refreshTimelineAndStats();
}

// POST the toggled label set for the currently open item, then apply the
// result — or surface a toast if the request itself failed.
async function _toggleLabel(lbl, host) {
  const cur = new Set(lbState.item.labels || []);
  if (cur.has(lbl)) cur.delete(lbl);
  else cur.add(lbl);
  try {
    const res = await j(
      `/api/camera/${lbState.item.camera_id}/events/${lbState.item.event_id}/labels`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ labels: [...cur] }),
      },
    );
    if (res.ok) _applyLabelSaveResult(res, host);
  } catch (_err) {
    showToast('Label-Änderung fehlgeschlagen', 'error');
  }
}

// `host` lets a caller other than the photo lightbox (the recorded-shell
// "Labels" tab) target its own tab-content div instead of the legacy
// #lightboxLabels node. Defaults to that node so the existing photo-path
// call site (no arg) is unchanged.
export function _renderLbLabels(host) {
  const el = host || byId('lightboxLabels');
  if (!el || !lbState.item) return;
  // Wrapped in its own flex row rather than relying on `el`'s own
  // layout — #lightboxLabels supplies flex/gap via an inline style
  // (absolute-positioned over the photo), a shell tab-content div does
  // not, and this way the renderer needs no host-specific styling.
  el.innerHTML = `<div class="mv-labels-row">${_buildLabelBubblesHtml(lbState.item)}</div>`;
  el.querySelectorAll('[data-label]').forEach((btn) => {
    btn.onclick = () => _toggleLabel(btn.dataset.label, host);
  });
}
