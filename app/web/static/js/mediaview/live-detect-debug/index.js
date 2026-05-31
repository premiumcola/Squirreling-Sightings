import { _renderCopyBar, _wireCopyBar } from './_copy-bar.js';
import { _renderCluster1, _renderCluster1Evidence, _wireCluster1 } from './_clusters-1.js';
import { _renderCluster2, _renderCluster2Evidence, _wireCluster2 } from './_clusters-2.js';
import { _renderCluster3, _wireCluster3, _renderCluster4, _renderCluster5 } from './_clusters-345.js';
export { startSnapshotPrefetch, stopSnapshotPrefetch } from './_copy-bar.js';
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

import { esc } from '../../core/dom.js';
import { state } from '../../core/state.js';

const _STUCK_MS = 5000;

// Q2-2 · per-cluster collapse state. Every cluster BODY (sliders,
// evidence, perf grid, event log — the long blocks the user scrolls
// past) starts collapsed so the Debug tab fits roughly one screenful:
// only the always-on LIVE-STATUS strip + the five cluster headers
// (each carrying its live "what's wrong right now" hint) show. Tapping
// a header expands that cluster. State persists across ticks + reopens.
const _CLUSTER_COLLAPSE_KEY = 'tam.ld.debug.clusters';
const _clusterCollapsed = _loadClusterCollapse();
// Down-chevron; CSS rotates it -90° (points right) when collapsed.
function _loadClusterCollapse() {
  // Default: every cluster collapsed. A stored map overrides per id.
  const def = { 1: true, 2: true, 3: true, 4: true, 5: true };
  try {
    const raw = JSON.parse(localStorage.getItem(_CLUSTER_COLLAPSE_KEY) || '{}');
    for (const k of Object.keys(def)) {
      if (typeof raw[k] === 'boolean') def[k] = raw[k];
    }
  } catch {
    /* private mode / corrupt — keep all-collapsed default */
  }
  return def;
}

function _saveClusterCollapse() {
  try {
    localStorage.setItem(_CLUSTER_COLLAPSE_KEY, JSON.stringify(_clusterCollapsed));
  } catch {
    /* private mode / quota — silent */
  }
}

// Apply the collapse state to every rendered cluster + start the
// delegated header-click toggle (once per host). Re-applied after the
// per-tick dynamic refresh too, since clusters 4/5 are swapped wholesale.
function _applyClusterCollapse(host) {
  host.querySelectorAll('[data-cluster-id]').forEach((root) => {
    const id = root.dataset.clusterId;
    const collapsed = _clusterCollapsed[id] !== false;
    root.dataset.collapsed = collapsed ? '1' : '0';
    const head = root.querySelector('.mv-ld-cluster-head');
    if (head) head.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  });
  if (!host.dataset.mvLdCollapseWired) {
    host.dataset.mvLdCollapseWired = '1';
    const toggle = (head) => {
      const root = head.closest('[data-cluster-id]');
      if (!root) return;
      const id = root.dataset.clusterId;
      const next = root.dataset.collapsed !== '1'; // toggle → next collapsed?
      _clusterCollapsed[id] = next;
      root.dataset.collapsed = next ? '1' : '0';
      head.setAttribute('aria-expanded', next ? 'false' : 'true');
      _saveClusterCollapse();
    };
    host.addEventListener('click', (ev) => {
      const head = ev.target.closest?.('.mv-ld-cluster-head');
      if (head && host.contains(head)) toggle(head);
    });
    host.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      const head = ev.target.closest?.('.mv-ld-cluster-head');
      if (head && host.contains(head)) {
        ev.preventDefault();
        toggle(head);
      }
    });
  }
}

export function renderDebugPanel(host, ctx = {}) {
  if (!host) return;
  // Idempotent rebuild: when the lane structure is unchanged from
  // last render, skip the full innerHTML refresh and just update the
  // dynamic cells (live-status + evidence boxes). This preserves the
  // in-progress slider drag state across ticks. Detection: the
  // structural fingerprint encodes the cam-id + filter membership.
  const session = ctx.session || {};
  const camId = session.camId || '';
  const cam = (state.cameras || []).find((c) => c.id === camId) || {};
  const filterArr = Array.isArray(cam.object_filter) ? cam.object_filter : [];
  const fp = `${camId}|${filterArr.join(',')}`;
  if (host.dataset.mvLdDebugFp === fp) {
    _refreshDynamic(host, ctx, cam);
    return;
  }
  host.innerHTML =
    '<div class="mv-ld-debug">' +
    _renderCopyBar() +
    _renderLiveStatusHeader(ctx) +
    _renderCluster1(ctx, cam) +
    _renderCluster2(ctx, cam) +
    _renderCluster3(ctx, cam) +
    _renderCluster4(ctx) +
    _renderCluster5(ctx) +
    '</div>';
  host.dataset.mvLdDebugFp = fp;
  _wireCluster1(host, cam, ctx);
  _wireCluster2(host, cam, ctx);
  _wireCluster3(host, cam, ctx);
  _wireCopyBar(host, ctx);
  _applyClusterCollapse(host);
}

// Refresh the dynamic content (live-status + evidence boxes) without
// destroying the structural skeleton — slider drag state survives a
// tick refresh because the slider DOM persists.
function _refreshDynamic(host, ctx, cam) {
  const headerHost = host.querySelector('.mv-ld-debug-header');
  if (headerHost) {
    headerHost.outerHTML = _renderLiveStatusHeader(ctx);
  }
  const ev1 = host.querySelector('[data-cluster-evidence="1"]');
  if (ev1) ev1.outerHTML = _renderCluster1Evidence(ctx, cam);
  const ev2 = host.querySelector('[data-cluster-evidence="2"]');
  if (ev2) ev2.outerHTML = _renderCluster2Evidence(ctx, cam);
  const c4 = host.querySelector('[data-cluster-id="4"]');
  if (c4) c4.outerHTML = _renderCluster4(ctx);
  const c5 = host.querySelector('[data-cluster-id="5"]');
  if (c5) c5.outerHTML = _renderCluster5(ctx);
  // Clusters 4/5 were swapped wholesale (fresh nodes) → re-stamp their
  // collapse state so a tick refresh can't silently re-expand them.
  _applyClusterCollapse(host);
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
    <div class="mv-ld-debug-header" data-mv-ld-live-status="1">
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
