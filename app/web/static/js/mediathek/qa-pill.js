// ─── mediathek/qa-pill.js ──────────────────────────────────────────────────
// Quality pill on every timelapse card in the Mediathek grid + a
// modal panel on tap that surfaces the full QA sidecar JSON for
// copy-paste-back-to-chat diagnostics.
//
// Data path:
//   * Each `.mmc-tl` card carries `data-event-id` + `data-camera-id`.
//   * We resolve the mp4 relpath from the item via the unified
//     `state._allMedia` cache (already populated by the mediathek
//     loader), then lazy-fetch `/api/timelapse/<relpath>/qa` on
//     IntersectionObserver entry.
//   * Sidecar response paints the pill: green / yellow / red / n-a.
//
// On tap → modal centred on the viewport with the full QA report
// (declared / effective / unique fps, dup ratio, top-3 reject
// reasons, freeze list, validator profile). A "QA-Bericht kopieren"
// button copies a markdown-formatted version to the clipboard.
//
// Touch targets ≥ 44 × 44 px on the pill itself (pill is small but
// the hit area is enlarged via a transparent ::before). Modal close
// button + copy button match the existing modal-action sizes.

import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { showToast } from '../core/toast.js';
import { copyText } from '../core/clipboard.js';
import { apiGet } from '../core/api.js';
import { qaCause, REJECT_REASON_DE } from './_qa-cause.js';

// GERMAN, and no jargon. „lossy" was an English word on a German
// surface, and it named a symptom nobody could act on.
const _GRADE_CLASSES = {
  green: { cls: 'mmc-qa-pill--green', label: 'vollständig' },
  yellow: { cls: 'mmc-qa-pill--yellow', label: 'lückenhaft' },
  red: { cls: 'mmc-qa-pill--red', label: 'stark lückenhaft' },
};

// One in-flight fetch per relpath — multiple cards for the same
// item (rare but possible across re-renders) share the result.
const _qaCache = new Map();

function _itemFor(card) {
  const eid = card.dataset.eventId;
  if (!eid) return null;
  const all = state._allMedia || state.media || [];
  return all.find((m) => m && m.event_id === eid) || null;
}

function _relpathOf(item) {
  // Preferred — the sidecar JSON carries the exact path.
  if (item.video_relpath) return item.video_relpath;
  // Fallback — derive from the canonical timelapse layout.
  if (item.filename && item.camera_id) {
    return `timelapse/${item.camera_id}/${item.filename}`;
  }
  return null;
}

async function _fetchQA(relpath) {
  if (_qaCache.has(relpath)) return _qaCache.get(relpath);
  const promise = (async () => {
    // 404 is the common case (clip never had QA run); apiGet throws on
    // non-2xx so we collapse all error paths to null here.
    try {
      return await apiGet(`/api/timelapse/${relpath}/qa`);
    } catch {
      return null;
    }
  })();
  _qaCache.set(relpath, promise);
  return promise;
}

function _renderPill(card, qa, item) {
  if (card.dataset.qaPainted === '1') return;
  card.dataset.qaPainted = '1';
  // tx518 — n/a means "no QA sidecar exists" (legacy build before the
  // quality-pass feature, or the sidecar hasn't been written yet).
  // Painting an "n/a" placeholder pill was both confusing (users asked
  // what it meant) and visually clashing with the delete-X in select
  // mode. Render nothing in that case; the tile stays clean. Users
  // who want to backfill grades can rebuild the timelapse via the
  // camera-edit timelapse panel, which writes a fresh sidecar.
  const grade = qa?.quality_grade || null;
  if (!grade || grade === 'n/a' || grade === 'unknown') return;
  const meta = _GRADE_CLASSES[grade];
  if (!meta) return;
  const wrap = card.querySelector('.mmc-img-wrap');
  if (!wrap) return;
  // A DOT, not a word. „bitte macht das Lossy sein irgendwie schöner,
  // es überragt beim iPhone" — the pill sat at a fixed `right: 42px`
  // between the „Timelapse" badge on the left and the delete button on
  // the right, and on a phone-width tile the three of them fought for
  // the same strip. A coloured dot cannot collide with anything, and
  // everything the word said is one tap away in the panel behind it —
  // where it can be said properly instead of in one English adjective.
  const cause = qaCause(qa, item);
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = `mmc-qa-pill ${meta.cls}`;
  btn.setAttribute('aria-label', `Aufnahmequalität: ${meta.label}. Antippen für den Grund.`);
  btn.title = cause ? `${meta.label} — ${cause.headline}` : meta.label;
  btn.innerHTML = `<span class="mmc-qa-dot"></span>`;
  btn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    _openModal(card, qa);
  });
  wrap.appendChild(btn);
}

function _paintIntoCard(card) {
  const item = _itemFor(card);
  if (!item) {
    _renderPill(card, null, null);
    return;
  }
  const rel = _relpathOf(item);
  if (!rel) {
    _renderPill(card, null, null);
    return;
  }
  // The ITEM travels with the sidecar: the cause block compares the
  // encoder's own frame_count against the capture counter, and only the
  // item carries it. See _qa-cause.js.
  _fetchQA(rel).then((qa) => _renderPill(card, qa, item));
}

// IntersectionObserver — lazy-paint pills only on cards that
// actually scroll into view. Avoids N parallel fetches when the
// user lands on a multi-page grid.
let _io = null;
function _ensureObserver() {
  if (_io) return _io;
  if (typeof IntersectionObserver === 'undefined') {
    return null; // ancient browser — skip lazy and paint eagerly below
  }
  _io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          _paintIntoCard(e.target);
          _io.unobserve(e.target);
        }
      }
    },
    { rootMargin: '120px' },
  );
  return _io;
}

// Public — call from the grid renderer after innerHTML rebuilds.
export function paintQAPillsForGrid() {
  const cards = document.querySelectorAll('.mmc-tl[data-event-id]:not([data-qa-painted])');
  const obs = _ensureObserver();
  if (obs) {
    cards.forEach((c) => obs.observe(c));
  } else {
    cards.forEach((c) => _paintIntoCard(c));
  }
}

window.paintQAPillsForGrid = paintQAPillsForGrid;

// ── Modal panel ────────────────────────────────────────────────────────────
function _markdownReport(qa, item) {
  if (!qa) return `# Timelapse QA · ${item?.filename || ''}\nKein Sidecar vorhanden.`;
  const pb = qa.playback || {};
  const cap = qa.capture || {};
  const reasons = cap.reject_reasons || {};
  const top3 = Object.entries(reasons)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  const freezes = qa.freezes || [];
  const freezeTotal = freezes.reduce((acc, f) => acc + (f.duration_s || 0), 0);
  const lines = [];
  lines.push(`# Timelapse QA · ${qa.video || item?.filename || ''}`);
  lines.push(`- camera: \`${qa.camera_id || item?.camera_id || ''}\``);
  lines.push(
    `- profile: ${qa.profile_name || '?'} · validator: ${qa.validator_profile_used || '?'}`,
  );
  lines.push(`- grade: **${qa.quality_grade || '?'}**`);
  lines.push(
    `- declared ${pb.declared_fps || 0} fps · effective ${pb.effective_fps || 0} fps · unique ${pb.unique_fps || 0} fps`,
  );
  lines.push(
    `- dup_ratio ${Math.round((pb.duplicate_ratio || 0) * 100)} % (${pb.duplicate_count || 0} of ${pb.frames_in_file || 0})`,
  );
  lines.push(`- freezes: ${freezes.length} (total ${freezeTotal.toFixed(2)} s)`);
  if (top3.length) {
    lines.push('- top reject reasons:');
    for (const [k, v] of top3) lines.push(`  - ${k}: ${v}`);
  }
  return lines.join('\n');
}

function _openModal(card, qa) {
  const item = _itemFor(card);
  // Always re-fetch on open in case the cached pill data is stale
  // (the post-build sidecar may have been re-generated by a rebuild
  // the user just kicked).
  const rel = item ? _relpathOf(item) : null;
  const loader = rel ? _fetchQA(rel) : Promise.resolve(qa || null);
  loader.then((fresh) => {
    const data = fresh || qa;
    _renderModal(item, data);
  });
}

/**
 * The panel's opening block: the cause, in words, before any number.
 *
 * THE ORDER IS THE POINT. The fps triplet and the duplicate ratio stay —
 * they are the evidence, and the copy button hands them to whoever is
 * debugging. But they came FIRST, and four English measurements are not
 * an answer to „wieso lossy?". Two clips on this box carry the same red
 * grade and the same high duplicate ratio for reasons that share
 * nothing: one camera barely captured, the other captured and had three
 * quarters thrown away as unusable. The numbers show neither; the
 * sentence shows both. See _qa-cause.js.
 */
function _causeHtml(qa, item) {
  const c = qaCause(qa, item);
  if (!c) return '';
  const nums = c.numbers
    .map(
      (n) =>
        `<div class="tl-qa-num"><span class="tl-qa-num-v">${esc(n.value)}</span>` +
        `<span class="tl-qa-num-l">${esc(n.label)}</span></div>`,
    )
    .join('');
  const lever = c.lever ? `<p class="tl-qa-lever">${esc(c.lever)}</p>` : '';
  return (
    `<div class="tl-qa-cause" data-kind="${esc(c.kind)}">` +
    `<p class="tl-qa-cause-head">${esc(c.headline)}</p>` +
    `<p class="tl-qa-cause-detail">${esc(c.detail)}</p>` +
    `<div class="tl-qa-nums">${nums}</div>${lever}</div>`
  );
}

function _renderModal(item, qa) {
  let modal = byId('tlQAModal');
  if (modal) modal.remove();
  modal = document.createElement('div');
  modal.id = 'tlQAModal';
  modal.className = 'tl-qa-modal';
  const pb = qa?.playback || {};
  const cap = qa?.capture || {};
  const reasons = cap.reject_reasons || {};
  const top3 = Object.entries(reasons)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  const freezes = qa?.freezes || [];
  const duration = pb.duration_s || 1;
  const freezeTicks = freezes
    .map((f) => {
      const startPct = ((f.playback_s?.[0] || 0) / duration) * 100;
      const widthPct = ((f.duration_s || 0) / duration) * 100;
      return `<span class="tl-qa-tick" style="left:${startPct.toFixed(2)}%;width:${Math.max(0.5, widthPct).toFixed(2)}%" title="${(f.duration_s || 0).toFixed(2)} s freeze"></span>`;
    })
    .join('');
  const grade = qa?.quality_grade || 'na';
  const gradeMeta = _GRADE_CLASSES[grade] || { cls: 'mmc-qa-pill--na', label: 'n/a' };
  const rebuildBtn = !qa
    ? `<button type="button" class="tl-qa-btn tl-qa-rebuild">Rebuild starten</button>`
    : '';
  modal.innerHTML = `
    <div class="tl-qa-backdrop"></div>
    <div class="tl-qa-shell" role="dialog" aria-labelledby="tlQATitle">
      <button type="button" class="tl-qa-close" aria-label="Schließen">✕</button>
      <div class="tl-qa-head">
        <span class="mmc-qa-pill ${gradeMeta.cls}" aria-hidden="true">
          <span class="mmc-qa-dot"></span><span>${gradeMeta.label}</span>
        </span>
        <span id="tlQATitle" class="tl-qa-filename">${esc(qa?.video || item?.filename || 'unbekannt')}</span>
      </div>
      ${
        qa
          ? `
        ${_causeHtml(qa, item)}
        <div class="tl-qa-stats">
          <div class="tl-qa-stat"><span class="tl-qa-stat-num">${pb.declared_fps || 0}</span><span class="tl-qa-stat-lbl">declared fps</span></div>
          <div class="tl-qa-stat"><span class="tl-qa-stat-num">${pb.effective_fps || 0}</span><span class="tl-qa-stat-lbl">effective fps</span></div>
          <div class="tl-qa-stat"><span class="tl-qa-stat-num">${pb.unique_fps || 0}</span><span class="tl-qa-stat-lbl">unique fps</span></div>
        </div>
        <div class="tl-qa-dup">duplicate ratio · <strong>${Math.round((pb.duplicate_ratio || 0) * 100)} %</strong> (${pb.duplicate_count || 0} of ${pb.frames_in_file || 0})</div>
        ${
          top3.length
            ? `
        <div class="tl-qa-section-title">Verworfene Bilder</div>
        <ul class="tl-qa-reasons">
          ${top3.map(([k, v]) => `<li><span>${esc(REJECT_REASON_DE[k] || k)}</span><span class="tl-qa-reason-n">${v}</span></li>`).join('')}
        </ul>`
            : ''
        }
        ${
          freezes.length
            ? `
        <div class="tl-qa-section-title">Freezes (${freezes.length})</div>
        <div class="tl-qa-freeze-bar" title="${freezes.length} freeze cluster(s)">${freezeTicks}</div>`
            : ''
        }
      `
          : `<div class="tl-qa-empty">Kein QA-Sidecar — älterer Build vor der Quality-Pass-Einführung.</div>`
      }
      <div class="tl-qa-actions">
        ${rebuildBtn}
        <button type="button" class="tl-qa-btn tl-qa-copy">QA-Bericht kopieren</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelector('.tl-qa-close').addEventListener('click', close);
  modal.querySelector('.tl-qa-backdrop').addEventListener('click', close);
  // core/clipboard.js, not navigator.clipboard directly. That API only
  // exists in a SECURE CONTEXT and this app is served over plain http://
  // on the LAN, so on the phone it is simply absent and every press
  // answered „Kopieren fehlgeschlagen". The shared helper starts with the
  // textarea path for exactly that reason — and it must be called
  // synchronously from the handler, because iOS grants the clipboard only
  // inside the original gesture and an `await` before the write loses it.
  modal.querySelector('.tl-qa-copy').addEventListener('click', () => {
    copyText(_markdownReport(qa, item), {
      onOk: () => showToast('QA-Bericht in der Zwischenablage', 'success'),
      onFail: () => showToast('Kopieren fehlgeschlagen — manuell aus dem Modal lesen', 'error'),
    });
  });
  const rb = modal.querySelector('.tl-qa-rebuild');
  if (rb) {
    rb.addEventListener('click', async () => {
      const camId = item?.camera_id;
      const day = (item?.window_key || item?.day || '').substring(0, 10);
      if (!camId || !day) {
        showToast('Rebuild nicht möglich — Camera / Day fehlt', 'error');
        return;
      }
      rb.disabled = true;
      try {
        await apiGet(
          `/api/camera/${encodeURIComponent(camId)}/timelapse?day=${encodeURIComponent(day)}&force=1`,
        );
        showToast('Rebuild läuft — Sidecar erscheint nach Encode', 'info');
      } catch {
        showToast('Rebuild-Request fehlgeschlagen', 'error');
      } finally {
        close();
      }
    });
  }
}
