// ─── camedit/erk-sim/timeline.js ───────────────────────────────────────────
// Sliding 30 s class-presence timeline shown below the preview image
// while live mode is running. One row per class with at least one
// confirmed track in the window; the right edge always reads "now"
// and bars age leftward as the polling loop ticks. A custom
// hover/tap tooltip surfaces the distinct-track count and peak score
// per slice; "× lost" markers tag the trailing edge of any track
// that just transitioned from confirmed → dropped.
//
// Pure DOM rendering (no SVG) so the badge column gives us natural
// touch targets for the per-row tooltip without manual hit-area math.
import { byId, esc } from '../../core/dom.js';
import { OBJ_LABEL, objBubble, colors } from '../../core/icons.js';

const _WINDOW_MS = 30_000;
const _SLICE_MS  = 1_000;
const _N_SLICES  = _WINDOW_MS / _SLICE_MS;

export class LiveTimeline {
  constructor(){
    this._slices = new Map();   // label -> Array<{ t, ids:Set<number>, peak:number }>
    this._lost   = new Map();   // label -> Array<{ t }>
  }

  // Append the latest tick into the rolling history. `confirmed` is
  // the tracker's confirmed-tracks output for THIS tick; `dropped`
  // is tracker.lastDropped() — newly-stale confirmed tracks. Trims
  // every entry older than the 30 s window to keep memory bounded.
  observe(confirmed, dropped, now_ms){
    const sliceT = Math.floor(now_ms / _SLICE_MS) * _SLICE_MS;

    const byLabel = new Map();
    for (const tr of confirmed){
      if (!byLabel.has(tr.label)) byLabel.set(tr.label, []);
      byLabel.get(tr.label).push(tr);
    }
    for (const [label, tracks] of byLabel){
      const arr = this._slices.get(label) || [];
      let slice = (arr.length > 0 && arr[arr.length - 1].t === sliceT)
        ? arr[arr.length - 1]
        : null;
      if (!slice){
        slice = { t: sliceT, ids: new Set(), peak: 0 };
        arr.push(slice);
      }
      for (const tr of tracks){
        slice.ids.add(tr.id);
        const s = tr.last_score || 0;
        if (s > slice.peak) slice.peak = s;
      }
      this._slices.set(label, arr);
    }

    for (const tr of dropped || []){
      const arr = this._lost.get(tr.label) || [];
      arr.push({ t: tr.last_seen_ms });
      this._lost.set(tr.label, arr);
    }

    const cutoff = now_ms - _WINDOW_MS;
    for (const [label, arr] of Array.from(this._slices.entries())){
      while (arr.length > 0 && arr[0].t < cutoff) arr.shift();
      if (arr.length === 0) this._slices.delete(label);
    }
    for (const [label, arr] of Array.from(this._lost.entries())){
      while (arr.length > 0 && arr[0].t < cutoff) arr.shift();
      if (arr.length === 0) this._lost.delete(label);
    }
  }

  // Render into `host` (the #erkSimTimeline div). `startedAt` is the
  // wall-clock ms the live session began — used for the empty-state
  // "läuft seit Xs" line. Idempotent: safe to call every tick.
  render(host, now_ms, startedAt){
    if (!host) return;
    const labels = Array.from(this._slices.keys());
    if (labels.length === 0){
      const seconds = Math.max(0, Math.round((now_ms - startedAt) / 1000));
      host.innerHTML = `<div class="erk-tl-empty">Noch keine Erkennungen — Live-Modus läuft seit ${seconds} s</div>`;
      return;
    }
    // Order rows by class colour palette index so swaps don't flip
    // row order between ticks (Map iteration is insertion-order, but
    // a class that drops out and re-appears would otherwise jump).
    labels.sort((a, b) => a.localeCompare(b));

    const windowStart = now_ms - _WINDOW_MS;
    const rows = labels.map(label => this._renderRow(label, windowStart, now_ms)).join('');
    host.innerHTML = `
      <div class="erk-tl-grid" role="group" aria-label="Erkennungs-Timeline der letzten 30 Sekunden">
        ${rows}
      </div>`;
    _wireTooltips(host);
  }

  // Hard reset — called when live mode stops so the next start
  // doesn't paint stale slices from the previous session. The render
  // host is left alone; live.js clears it at start.
  reset(){
    this._slices.clear();
    this._lost.clear();
  }

  _renderRow(label, windowStart, now_ms){
    const arr  = this._slices.get(label) || [];
    const lost = this._lost.get(label)   || [];
    const lblText = esc(OBJ_LABEL[label] || label);
    const colour  = colors[label] || colors.unknown;

    // Slice rectangles — we render every slot of the 30-slice strip
    // so the strip's geometry is stable across ticks; absent slices
    // get an "empty" class. Fast path: build a sparse map of t →
    // slice for O(1) lookup per slot.
    const slotByT = new Map();
    for (const sl of arr) slotByT.set(sl.t, sl);
    const slots = [];
    for (let i = 0; i < _N_SLICES; i++){
      const slotT = windowStart + i * _SLICE_MS;
      const slotKey = Math.floor(slotT / _SLICE_MS) * _SLICE_MS;
      const sl = slotByT.get(slotKey);
      const left = (i / _N_SLICES) * 100;
      const width = (1 / _N_SLICES) * 100;
      if (sl){
        const trackCount = sl.ids.size;
        const peakPct = Math.round((sl.peak || 0) * 100);
        const tt = `${trackCount} Track${trackCount === 1 ? '' : 's'} · Peak ${peakPct}%`;
        slots.push(
          `<span class="erk-tl-slot is-hit" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%;background:${colour}" data-tip="${esc(tt)}"></span>`
        );
      } else {
        slots.push(
          `<span class="erk-tl-slot" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%"></span>`
        );
      }
    }

    // Lost markers — a small × at the lost-time x position. Multiple
    // losses for the same class show stacked × at their respective
    // positions.
    const lostMarks = lost.map(l => {
      const pct = ((l.t - windowStart) / _WINDOW_MS) * 100;
      return `<span class="erk-tl-lost" style="left:${pct.toFixed(2)}%" aria-label="Track verloren">×</span>`;
    }).join('');

    return `
      <div class="erk-tl-row">
        <button type="button" class="erk-tl-badge" aria-label="${lblText}">
          ${objBubble(label, 28)}
          <span class="erk-tl-badge-text">${lblText}</span>
        </button>
        <div class="erk-tl-strip">
          ${slots.join('')}
          ${lostMarks}
        </div>
      </div>`;
  }
}


// Single page-level tooltip element re-used across every row. Lazy-
// created on the first hover/tap so an inactive timeline doesn't
// leave a stray element in the DOM. Clears its content on
// pointerleave/scroll so it doesn't ghost into a different page
// section if the user navigates mid-render.
let _tipEl = null;
function _ensureTip(){
  if (_tipEl) return _tipEl;
  _tipEl = document.createElement('div');
  _tipEl.className = 'erk-tl-tooltip';
  _tipEl.setAttribute('role', 'tooltip');
  _tipEl.hidden = true;
  document.body.append(_tipEl);
  return _tipEl;
}

function _showTip(target){
  const txt = target?.getAttribute('data-tip');
  if (!txt) return;
  const tip = _ensureTip();
  tip.textContent = txt;
  tip.hidden = false;
  const r = target.getBoundingClientRect();
  // Position above the slot when there's space, otherwise below.
  const tipR = tip.getBoundingClientRect();
  const above = r.top - tipR.height - 8;
  const top = above >= 0 ? above : r.bottom + 8;
  // Centre horizontally over the slot, but clamp to the viewport
  // so the tip never gets cropped on iPhone widths.
  const vw = window.innerWidth || document.documentElement.clientWidth;
  let left = r.left + r.width / 2 - tipR.width / 2;
  left = Math.max(8, Math.min(vw - tipR.width - 8, left));
  tip.style.top = `${Math.round(top)}px`;
  tip.style.left = `${Math.round(left)}px`;
}

function _hideTip(){
  if (_tipEl) _tipEl.hidden = true;
}

function _wireTooltips(host){
  // Idempotent: re-applying every tick is fine — the dataset.wired
  // guard keeps the listeners single-shot.
  if (host.dataset.tipWired === '1') return;
  host.dataset.tipWired = '1';
  host.addEventListener('pointerover', (ev) => {
    const slot = ev.target.closest('.erk-tl-slot.is-hit');
    if (slot) _showTip(slot);
  });
  host.addEventListener('pointerout', (ev) => {
    if (!host.contains(ev.relatedTarget)) _hideTip();
  });
  // Touch: a tap on a slot shows the tip; another tap hides it.
  host.addEventListener('click', (ev) => {
    const slot = ev.target.closest('.erk-tl-slot.is-hit');
    if (!slot){ _hideTip(); return; }
    if (_tipEl && !_tipEl.hidden && _tipEl.dataset.activeFor === slot.getAttribute('data-tip')){
      _hideTip();
      return;
    }
    _showTip(slot);
    if (_tipEl) _tipEl.dataset.activeFor = slot.getAttribute('data-tip') || '';
  });
  // Page scroll dismisses the tip — otherwise it stays floating on a
  // stale screen position while the user reads further down.
  window.addEventListener('scroll', _hideTip, { passive: true });
}
