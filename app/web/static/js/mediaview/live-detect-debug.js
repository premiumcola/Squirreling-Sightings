// ─── mediaview/live-detect-debug.js ───────────────────────────────────────
// SIMU-05 · Debug tab content renderer.
//
// The Debug tab is organised by USER PROBLEM, not by data theme:
//   - Live-Status header   (always-on compact metrics row)
//   - Cluster 1 · Track-continuity (sliders + evidence)
//   - Cluster 2 · Recognition (per-class sliders + filter pills)
//   - Cluster 3 · False positives (quick-filter pills + zone link)
//   - Cluster 4 · Performance (read-only with auto-diagnose)
//   - Cluster 5 · Tracker events (read-only log)
//
// renderDebugPanel(host, ctx) takes the tick context the caller
// already has on hand and rebuilds the panel. SIMU-05a · just the
// header is in here for now; clusters land in subsequent commits.

import { esc } from '../core/dom.js';
import { state } from '../core/state.js';

const _STUCK_MS = 5000;

export function renderDebugPanel(host, ctx = {}) {
  if (!host) return;
  const headerHtml = _renderLiveStatusHeader(ctx);
  host.innerHTML = `<div class="mv-ld-debug">${headerHtml}</div>`;
}

function _renderLiveStatusHeader(ctx) {
  const t = ctx.tickState || {};
  const session = ctx.session || {};
  const diag = ctx.fullData?.diag || {};
  const cam = (state.cameras || []).find((c) => c.id === session.camId) || {};
  const now = Date.now();
  const sinceTick = t.lastTickAt ? now - t.lastTickAt : Infinity;
  const sinceResp = t.lastRespAt ? now - t.lastRespAt : Infinity;
  const tickStatus = !t.lastTickAt
    ? 'idle'
    : Math.min(sinceTick, sinceResp) > _STUCK_MS
      ? 'stuck'
      : 'ok';
  const tickStuckClass =
    tickStatus === 'stuck' ? ' mv-ld-debug-warn' : '';
  const armed = cam.armed !== false;
  const armedClass = !armed ? ' mv-ld-debug-warn-red' : '';
  const cycleMs = Number.isFinite(t.lastCycleMs) ? Math.round(t.lastCycleMs) : '—';
  const delayMs = Number.isFinite(t.lastDelayMs) ? Math.round(t.lastDelayMs) : '—';
  const inferMs = Number(diag.inference_ms) > 0 ? Math.round(Number(diag.inference_ms)) : '—';
  const frameSrc = session.lastFrameSrc || diag.frame_src || '?';
  const sourceMode =
    frameSrc === 'sub' ? 'sub-fast' : frameSrc === 'main_fallback' ? 'main-slow' : frameSrc;
  const fs = session.lastFrameSize || diag.frame_size || { w: 0, h: 0 };
  const sourceDims = fs.w && fs.h ? `${fs.w}×${fs.h}` : '—';
  const avgCycle = Number.isFinite(ctx.cycleEmaMs) ? Math.round(ctx.cycleEmaMs) : '—';
  const holdMs = Number.isFinite(ctx.holdMs) ? Math.round(ctx.holdMs) : '—';
  const drops = Number(t.ticksDroppedLate || 0);
  const profil = diag.validator_profile || '—';
  return `
    <div class="mv-ld-debug-header">
      <div class="mv-ld-debug-mini-head">LIVE-STATUS</div>
      <div class="mv-ld-debug-row">
        <span class="mv-ld-debug-cell${tickStuckClass}">
          <span class="mv-ld-debug-k">TICK</span>
          <span class="mv-ld-debug-v mv-ld-debug-v-bright">${esc(tickStatus)}</span>
          <span class="mv-ld-debug-v">· ${esc(String(cycleMs))} ms · next ${esc(String(delayMs))} ms</span>
        </span>
        <span class="mv-ld-debug-cell">
          <span class="mv-ld-debug-k">QUELLE</span>
          <span class="mv-ld-debug-v mv-ld-debug-v-bright">${esc(sourceMode)}</span>
          <span class="mv-ld-debug-v">· ${esc(sourceDims)}</span>
        </span>
        <span class="mv-ld-debug-cell">
          <span class="mv-ld-debug-k">INFER</span>
          <span class="mv-ld-debug-v mv-ld-debug-v-bright">${esc(String(inferMs))} ms</span>
        </span>
      </div>
      <div class="mv-ld-debug-row">
        <span class="mv-ld-debug-cell">
          <span class="mv-ld-debug-k">CADENCE</span>
          <span class="mv-ld-debug-v">avg ${esc(String(avgCycle))} · hold ${esc(String(holdMs))} · drops ${esc(String(drops))}</span>
        </span>
        <span class="mv-ld-debug-cell">
          <span class="mv-ld-debug-k">PROFIL</span>
          <span class="mv-ld-debug-v">${esc(profil)}</span>
        </span>
        <span class="mv-ld-debug-cell${armedClass}">
          <span class="mv-ld-debug-k">ARMED</span>
          <span class="mv-ld-debug-v mv-ld-debug-v-bright">${armed ? 'true' : 'false'}</span>
        </span>
      </div>
    </div>`;
}
