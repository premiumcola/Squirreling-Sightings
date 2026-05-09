// ─── camedit/erk-sim/trace.js ──────────────────────────────────────────────
// Decision-trace rendering for the simulation sheet. Three deliverables
// land here:
//   1. A compact "active config" chip strip at the top — global
//      threshold, per-class overrides, object_filter, parsed straight
//      out of the [coral] trace lines so it agrees with what actually
//      ran.
//   2. The trace block itself — collapsed by default, summary header
//      that doubles as the toggle, per-line color classes by [prefix]
//      so PASS / REJECTED / FILTERED / [final] visually pop. Open
//      preference persists per-camera in localStorage.
//   3. A size-floor hint surfaced under the trace whenever a
//      detection got rejected for being too small — points the user
//      at the Coral settings section that controls the floor.
//
// Pure DOM rendering. No backend changes; all signals come from
// `data.decision_trace` (already shipped) and `data.detections[].reason`.
import { byId, esc } from '../../core/dom.js';

const _LS_KEY_PREFIX = 'erkSimTraceOpen:';


// Public — call per render tick from snapshot.js. Idempotent.
export function renderTrace(data, camId){
  const wrap = byId('erkSimLog');
  if (!wrap) return;
  const trace = Array.isArray(data?.decision_trace) ? data.decision_trace : [];
  if (trace.length === 0){
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;

  const dets = data?.detections || [];
  const passCount = dets.filter(d => d.verdict === 'pass').length;

  _renderSummary(dets.length, passCount);
  _renderLines(trace, dets.length, passCount);
  _renderConfigStrip(trace);
  _renderSizeHint(dets, data?.frame_size);
  _wireToggle(camId);
}


function _renderSummary(detCount, passCount){
  const summaryEl = byId('erkSimLogSummary');
  if (!summaryEl) return;
  const detWord = detCount === 1 ? 'Detection' : 'Detections';
  const verb = passCount === 1 ? 'würde' : 'würden';
  summaryEl.textContent = `${detCount} ${detWord} · ${passCount} ${verb} Alarm auslösen · Trace`;
}


function _renderLines(traceLines, detCount, passCount){
  const bodyEl = byId('erkSimLogBody');
  if (!bodyEl) return;
  const ts = new Date().toLocaleTimeString('de-DE');
  const headerLine = `[${ts}] simulate → ${detCount} dets, ${passCount} pass`;
  const all = [headerLine, ...traceLines];
  bodyEl.innerHTML = all.map(line =>
    `<div class="erk-sim-log-line ${_classifyLine(line)}">${esc(line)}</div>`
  ).join('');
}


// Classify a trace line by its [prefix] head + verdict suffix. The
// renderer paints each line via the matching is-* class — see
// 06-cam-edit-1.css for the colour table.
function _classifyLine(line){
  if (/^\[det\]/.test(line)){
    if (/\bPASS\b/.test(line))     return 'is-pass';
    if (/\bREJECTED\b/.test(line)) return 'is-rejected';
    if (/\bFILTERED\b/.test(line)) return 'is-filtered';
    return 'is-info';
  }
  if (/^\[verdict\]/.test(line)){
    return /no detection/i.test(line) ? 'is-verdict-fail' : 'is-info';
  }
  if (/^\[final\]/.test(line)){
    return /no push/i.test(line) ? 'is-final-fail' : 'is-final-pass';
  }
  if (/^\[cooldown\]/.test(line)){
    if (/would SKIP/i.test(line)) return 'is-cooldown-skip';
    if (/would PASS/i.test(line)) return 'is-cooldown-pass';
    return 'is-info';
  }
  if (/^\[(capture|coral|matrix|armed|telegram_enabled|schedule_notify)\]/.test(line)){
    return 'is-infra';
  }
  return 'is-info';
}


// Pull effective settings out of the trace lines and render them as
// a chip strip. Single-pass scan over the small (≤30 line) trace —
// no perf concerns. The patterns below mirror the literal strings
// app/app/routes/coral.py emits; if those change, update both.
function _renderConfigStrip(traceLines){
  const cfgEl = byId('erkSimCfg');
  if (!cfgEl) return;

  let globalThr = null;
  const perClassThr = [];
  let filterList = null;

  for (const line of traceLines){
    let m;
    if ((m = /^\[coral\]\s+threshold floor\s+([\d.]+)\s+·\s+per-class:\s*(.+)$/.exec(line))){
      globalThr = parseFloat(m[1]);
      const tail = m[2].trim();
      // Backend prints a Python dict literal. Walk it with a cheap
      // regex; "(none)" sentinel produces zero matches and the
      // per-class chip group stays empty.
      const re = /['"]?(\w+)['"]?\s*:\s*([\d.]+)/g;
      let mm;
      while ((mm = re.exec(tail))){
        perClassThr.push({ label: mm[1], thr: parseFloat(mm[2]) });
      }
    } else if ((m = /^\[coral\]\s+object_filter:\s*(.+)$/.exec(line))){
      const tail = m[1].trim();
      if (!/^\(/.test(tail)){
        // Python list literal — pull each quoted token.
        const tokens = tail.match(/['"](\w+)['"]/g);
        if (tokens) filterList = tokens.map(t => t.replace(/['"]/g, ''));
      }
    }
  }

  const chips = [];
  if (globalThr !== null){
    chips.push(_chip('Schwelle', `${Math.round(globalThr * 100)}%`));
  }
  for (const { label, thr } of perClassThr){
    chips.push(_chip(label, `${Math.round(thr * 100)}%`));
  }
  if (filterList && filterList.length > 0){
    chips.push(_chip('Filter', filterList.map(esc).join(' · ')));
  }

  if (chips.length === 0){
    cfgEl.hidden = true;
    cfgEl.innerHTML = '';
    return;
  }
  cfgEl.hidden = false;
  cfgEl.innerHTML = chips.join('');
}

function _chip(key, val){
  return `<span class="erk-sim-cfg-chip"><span class="erk-sim-cfg-key">${esc(key)}</span><span class="erk-sim-cfg-val">${val}</span></span>`;
}


// Surface a size-floor diagnostic when at least one detection got
// rejected because its bbox was below the minimum height/area
// fraction. The reason text shape comes from
// app/app/detectors/coral_object.py:
//   size_floor (h_frac=0.12 < 0.18)
//   size_floor (area_frac=0.005 < 0.012)
function _renderSizeHint(dets){
  const hintEl = byId('erkSimSizeHint');
  if (!hintEl) return;
  const sizeRej = dets.find(d => /^size_floor/i.test(d?.reason || ''));
  if (!sizeRej){
    hintEl.hidden = true;
    hintEl.innerHTML = '';
    return;
  }
  const reason = sizeRej.reason || '';
  let body;
  let m;
  if ((m = /h_frac=([\d.]+)\s*<\s*([\d.]+)/.exec(reason))){
    const had = Math.round(parseFloat(m[1]) * 100);
    const floor = Math.round(parseFloat(m[2]) * 100);
    body = `Tipp: '<b>${esc(sizeRej.label)}</b>' war nur ${had}% der Bildhöhe. Aktuelle Untergrenze: ${floor}% — bei der Coral Settings-Sektion 'Größenboden pro Klasse' anpassbar.`;
  } else if ((m = /area_frac=([\d.]+)\s*<\s*([\d.]+)/.exec(reason))){
    const had = (parseFloat(m[1]) * 100).toFixed(1);
    const floor = (parseFloat(m[2]) * 100).toFixed(1);
    body = `Tipp: '<b>${esc(sizeRej.label)}</b>' deckte nur ${had}% der Bildfläche ab. Aktuelle Untergrenze: ${floor}% — bei der Coral Settings-Sektion 'Größenboden pro Klasse' anpassbar.`;
  } else {
    body = `Tipp: '<b>${esc(sizeRej.label)}</b>' wurde wegen Größenuntergrenze verworfen — bei der Coral Settings-Sektion 'Größenboden pro Klasse' anpassbar.`;
  }
  hintEl.hidden = false;
  hintEl.innerHTML = `<span class="erk-sim-size-hint-icon" aria-hidden="true">!</span><span class="erk-sim-size-hint-text">${body}</span>`;
}


// Wire the trace toggle and apply the per-camera localStorage
// preference. Idempotent — the wired flag guards against double-
// binding when the simulate sheet re-renders mid-session, and
// dataset.camId is updated on each call so a camera switch picks
// up the new key.
function _wireToggle(camId){
  const toggle = byId('erkSimLogToggle');
  const body   = byId('erkSimLogBodyWrap');
  if (!toggle || !body) return;
  if (!toggle.dataset.wired){
    toggle.dataset.wired = '1';
    toggle.addEventListener('click', () => {
      const open = toggle.getAttribute('aria-expanded') === 'true';
      _applyOpen(!open);
      const cid = toggle.dataset.camId || '';
      if (!cid) return;
      try {
        if (!open) localStorage.setItem(_LS_KEY_PREFIX + cid, '1');
        else       localStorage.removeItem(_LS_KEY_PREFIX + cid);
      } catch { /* private mode / quota — silently keep session-only */ }
    });
  }
  toggle.dataset.camId = camId || '';
  let stored = null;
  try { stored = camId ? localStorage.getItem(_LS_KEY_PREFIX + camId) : null; } catch { /* ignore */ }
  _applyOpen(stored === '1');
}

function _applyOpen(open){
  const toggle = byId('erkSimLogToggle');
  const body   = byId('erkSimLogBodyWrap');
  if (!toggle || !body) return;
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  toggle.classList.toggle('is-open', open);
  body.hidden = !open;
}
