import { esc } from '../../core/dom.js';
import { _renderClusterHeader, _CLUSTER_CHEVRON } from './_clusters-1.js';
import { _scheduleSave } from './_save.js';
// SIMU-05d · Cluster 3 · False Positives. Pills only; one-tap adds
// an off-filter class to the excluded_classes list. Zonen-editor
// link surfaces the existing cam-edit zones view.
export function _renderCluster3(ctx, cam) {
  const ev = ctx.fullData?.cluster_evidence?.cluster3;
  const offFilter = ev && ev.off_filter_60s_counts ? ev.off_filter_60s_counts : {};
  const topPills = Object.entries(offFilter)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(
      ([lbl, n]) =>
        `<button type="button" class="mv-ld-fp-pill" data-fp-pill="${esc(lbl)}">${esc(lbl)} <span class="mv-ld-fp-count">${n}</span> <span class="mv-ld-fp-x" aria-hidden="true">×</span></button>`,
    )
    .join('');
  const zoneCount = Array.isArray(cam.zones) ? cam.zones.length : 0;
  const maskCount = Array.isArray(cam.masks) ? cam.masks.length : 0;
  return `
    <div class="mv-ld-cluster mv-ld-cluster-warn" data-cluster-id="3">
      ${_renderClusterHeader(3, 'Cluster 3 · Falsche Klasse / False Positives',
        'Andere Klassen werden fälschlicherweise erkannt · z.B. „couch" oder „tv"',
        _cluster3HeaderHint(ev))}
      <div class="mv-ld-cluster-body">
        <div class="mv-ld-subsection-head">SCHNELLFILTER (TOP FALSE POSITIVES)</div>
        <div class="mv-ld-subsection-desc">Direkt aus den Top-False-Positives der letzten 60 s · ein Tap entfernt sie aus der Detection-Pipeline</div>
        <div class="mv-ld-fp-pills" data-cluster-evidence="3">
          ${topPills || '<div class="mv-ld-empty-row">Keine False Positives in den letzten 60 s</div>'}
        </div>
        <div class="mv-ld-subsection-head">ZONEN / MASKEN</div>
        <div class="mv-ld-profil-line">
          <span>Aktiv: <span class="mv-ld-profil-val">${zoneCount} Zone(n) · ${maskCount} Maske(n)</span></span>
          <button type="button" class="mv-ld-link-btn" data-action="open-zone-editor">Zonen-Editor öffnen</button>
        </div>
        <div class="mv-ld-cluster-actions">
          <button type="button" class="mv-ld-action-btn" data-action="defaults-cluster3">Defaults</button>
          <span class="mv-ld-save-status" data-save-status data-save-state="idle"></span>
        </div>
      </div>
    </div>`;
}

export function _cluster3HeaderHint(ev) {
  if (!ev) return { tone: 'mute', text: '· Live-Daten in Vorbereitung' };
  const offFilter = ev.off_filter_60s_counts || {};
  const entries = Object.entries(offFilter)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  if (!entries.length) return { tone: 'ok', text: '✓ Letzte 60 s: keine False Positives' };
  const summary = entries.map(([k, v]) => `${k} (${v})`).join(', ');
  return { tone: 'warn', text: `⚠ Letzte 60 s: ${summary}` };
}

export function _wireCluster3(host, cam, ctx) {
  const camId = (ctx.session || {}).camId || cam.id;
  host.querySelectorAll('[data-fp-pill]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const lbl = btn.dataset.fpPill;
      const existing = Array.isArray(cam.excluded_classes) ? cam.excluded_classes.slice() : [];
      if (!existing.includes(lbl)) existing.push(lbl);
      const statusEl = btn.closest('.mv-ld-cluster')?.querySelector('[data-save-status]');
      _scheduleSave(camId, { excluded_classes: existing }, statusEl);
      btn.remove();
    });
  });
  host
    .querySelector('[data-action="defaults-cluster3"]')
    ?.addEventListener('click', () => {
      const statusEl = host
        .querySelector('[data-action="defaults-cluster3"]')
        .closest('.mv-ld-cluster')
        .querySelector('[data-save-status]');
      _scheduleSave(camId, { excluded_classes: [] }, statusEl);
    });
  host
    .querySelector('[data-action="open-zone-editor"]')
    ?.addEventListener('click', () => {
      const url = `/#cam-edit?cam=${encodeURIComponent(camId)}&tab=zonen`;
      window.location.href = url;
    });
}

// SIMU-05e · Cluster 4 · Performance. Read-only metrics block; the
// header tints green when all values are in target, amber/red when
// any threshold is crossed. Auto-diagnose surfaces specific repair
// hints below the metrics when something is off.
const _PERF_TARGETS = {
  tickCycle: 500,
  inference: 200,
  frameAge: 100,
  subFps: 5,
};

export function _renderCluster4(ctx) {
  const t = ctx.tickState || {};
  const diag = ctx.fullData?.diag || {};
  const ev = ctx.fullData?.cluster_evidence?.cluster4 || {};
  const tickCycle = Number.isFinite(ctx.cycleEmaMs)
    ? Math.round(ctx.cycleEmaMs)
    : Number.isFinite(t.lastCycleMs)
      ? Math.round(t.lastCycleMs)
      : null;
  const inference = Number(diag.inference_ms) > 0 ? Math.round(Number(diag.inference_ms)) : null;
  const frameAge = Number(diag.frame_age_ms) >= 0 ? Math.round(Number(diag.frame_age_ms)) : null;
  const drops = Number(t.ticksDroppedLate || 0);
  const subFps = Number(ev.sub_fps) >= 0 ? Number(ev.sub_fps).toFixed(0) : '—';
  const mainFps = Number(ev.main_fps) >= 0 ? Number(ev.main_fps).toFixed(0) : '—';
  const frameSrc = ctx.session?.lastFrameSrc || diag.frame_src;
  const issues = [];
  const okTick = tickCycle == null || tickCycle <= _PERF_TARGETS.tickCycle;
  if (!okTick) issues.push('tick');
  const okInfer = inference == null || inference <= _PERF_TARGETS.inference;
  if (!okInfer) issues.push('inference');
  const okFrame = frameAge == null || frameAge <= _PERF_TARGETS.frameAge;
  if (!okFrame) issues.push('frame');
  const okDrops = drops === 0;
  if (!okDrops) issues.push('drops');
  const okSub = Number(ev.sub_fps || 0) >= _PERF_TARGETS.subFps || !ev.sub_fps;
  if (!okSub) issues.push('sub');
  const healthy = issues.length === 0;
  const hint = healthy
    ? { tone: 'ok', text: '✓ Alle Werte im grünen Bereich' }
    : { tone: 'warn', text: `⚠ ${issues.length} Werte über Schwelle` };
  const diagnoseLines = [];
  if (!okTick && frameSrc === 'main_fallback') {
    diagnoseLines.push('Sub-Stream wieder herstellen — main-fallback ist aktiv');
  }
  if (!okInfer && frameSrc === 'sub') {
    diagnoseLines.push('TPU prüfen — Inference auf sub sollte unter 150 ms liegen');
  }
  if (!okDrops) {
    diagnoseLines.push(`Tick-Loop hat ${drops} Ticks während laufender Fetch verworfen — Backend-Last prüfen`);
  }
  if (!okSub) {
    diagnoseLines.push('Sub-Stream liefert sehr wenig — Reolink Sub-Stream-Konfiguration prüfen');
  }
  const diagnoseHtml = diagnoseLines.length
    ? `<div class="mv-ld-perf-diagnose">${diagnoseLines.map((l) => `<div>${esc(l)}</div>`).join('')}</div>`
    : '';
  return `
    <div class="mv-ld-cluster ${healthy ? 'mv-ld-cluster-ok' : 'mv-ld-cluster-warn'}" data-cluster-id="4">
      <div class="mv-ld-cluster-head mv-ld-cluster-head-${healthy ? 'ok' : 'warn'}" role="button" tabindex="0" aria-expanded="false">
        ${_CLUSTER_CHEVRON}
        <div class="mv-ld-cluster-head-text">
          <div class="mv-ld-cluster-head-title">Cluster 4 · Performance / Hänger</div>
          <div class="mv-ld-cluster-head-sub">${healthy ? 'aktuell unauffällig · Detection läuft flüssig' : '⚠ Tick-Cycle oder Inference über Schwelle'}</div>
        </div>
        <div class="mv-ld-cluster-head-hint" data-hint-tone="${hint.tone}">${esc(hint.text)}</div>
      </div>
      <div class="mv-ld-cluster-body">
        <div class="mv-ld-perf-grid">
          ${_perfRow('Tick-Cycle', tickCycle == null ? '—' : `${tickCycle} ms`, `Ziel < ${_PERF_TARGETS.tickCycle} ms`, okTick)}
          ${_perfRow('Inference', inference == null ? '—' : `${inference} ms`, `Ziel < ${_PERF_TARGETS.inference} ms`, okInfer)}
          ${_perfRow('Frame-Age', frameAge == null ? '—' : `${frameAge} ms`, `Ziel < ${_PERF_TARGETS.frameAge} ms`, okFrame)}
          ${_perfRow('Dropped Ticks', String(drops), 'Ziel = 0', okDrops)}
          ${_perfRow('Sub-Stream', `${subFps} fps`, 'verfügbar', okSub)}
          ${_perfRow('Main-Stream', `${mainFps} fps`, 'parallel · ungenutzt für Detection', true)}
        </div>
        ${diagnoseHtml}
      </div>
    </div>`;
}

export function _perfRow(label, value, target, ok) {
  const cls = ok ? 'mv-ld-perf-ok' : 'mv-ld-perf-bad';
  const mark = ok ? '✓' : '✗';
  return `
    <div class="mv-ld-perf-row ${cls}">
      <span class="mv-ld-perf-label">${esc(label)}</span>
      <span class="mv-ld-perf-value">${esc(value)}</span>
      <span class="mv-ld-perf-target">(${esc(target)} ${mark})</span>
    </div>`;
}

// SIMU-05f · Cluster 5 · Tracker events log. Read-only chronological
// log of SPAWN/CONT/DEATH/RE-ID events. Pulls from cluster_evidence
// when present (SIMU-05h); falls back to the decision_trace stream
// the response already carries.
const _EVENT_KIND_COLORS = {
  spawn: '#6ee7b7',
  cont: '#b6d4be',
  death: '#fda4af',
  reid: '#ffcd6e',
};

export function _renderCluster5(ctx) {
  const ev = ctx.fullData?.cluster_evidence?.cluster5;
  const events = ev && Array.isArray(ev.events_60s) ? ev.events_60s : null;
  const traceLines = Array.isArray(ctx.fullData?.decision_trace) ? ctx.fullData.decision_trace : [];
  const lines = events
    ? events.map(_renderEventLine).join('')
    : _renderFromTrace(traceLines);
  return `
    <div class="mv-ld-cluster" data-cluster-id="5">
      <div class="mv-ld-cluster-head mv-ld-cluster-head-neutral" role="button" tabindex="0" aria-expanded="false">
        ${_CLUSTER_CHEVRON}
        <div class="mv-ld-cluster-head-text">
          <div class="mv-ld-cluster-head-title">Cluster 5 · Tracker-Ereignisse letzte 60 s</div>
          <div class="mv-ld-cluster-head-sub">Pure Beobachtung · keine Steuerung</div>
        </div>
      </div>
      <div class="mv-ld-cluster-body">
        <div class="mv-ld-events-log">
          ${lines || '<div class="mv-ld-empty-row">Noch keine Track-Ereignisse in den letzten 60 s</div>'}
        </div>
      </div>
    </div>`;
}

export function _renderEventLine(e) {
  if (!e) return '';
  const kind = String(e.kind || 'cont').toLowerCase();
  const color = _EVENT_KIND_COLORS[kind] || '#b6d4be';
  const tag = kind === 'cont' ? 'CONT.' : kind.toUpperCase();
  const tn = Number.isFinite(e.track_num) ? `#${e.track_num}` : '#?';
  const lbl = e.label || '';
  const tAgo = Number.isFinite(e.t_ago_seconds) ? `t=-${Math.round(e.t_ago_seconds)}s` : '';
  const extra = e.extra || '';
  const body = [tn, lbl, extra, tAgo].filter(Boolean).join(' · ');
  return `<div class="mv-ld-event-line">
    <span class="mv-ld-event-tag" style="color:${color}">${tag}</span>
    <span class="mv-ld-event-body">${esc(body)}</span>
  </div>`;
}

export function _renderFromTrace(traceLines) {
  if (!traceLines.length) return '';
  return traceLines
    .slice(-60)
    .map((line) => {
      const text = String(line || '');
      let kind = 'cont';
      if (text.indexOf('PASS') !== -1) kind = 'spawn';
      else if (text.indexOf('REJECTED') !== -1 || text.indexOf('grace') !== -1) kind = 'death';
      else if (text.indexOf('re-id') !== -1 || text.indexOf('RE-ID') !== -1) kind = 'reid';
      const color = _EVENT_KIND_COLORS[kind];
      const tag = kind === 'cont' ? 'CONT.' : kind.toUpperCase();
      return `<div class="mv-ld-event-line">
        <span class="mv-ld-event-tag" style="color:${color}">${tag}</span>
        <span class="mv-ld-event-body">${esc(text)}</span>
      </div>`;
    })
    .join('');
}

