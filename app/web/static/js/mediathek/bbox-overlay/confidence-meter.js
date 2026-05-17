// ─── mediathek/bbox-overlay/confidence-meter.js ────────────────────────────
// Bottom-left pill that ticks per-gate confidence for every track
// active at videoEl.currentTime. Each row renders one of three gates
// (Score / Bbox-Höhe / Bbox-Fläche) with a 3 px bar + a 1 px white
// tick at the threshold and the threshold percent above the tick.
// Driven by _interpolateTrackAt so the bars move continuously across
// the clip; hidden entirely when no track is active.
import { byId } from '../../core/dom.js';
import { colors, OBJ_LABEL } from '../../core/icons.js';
import { lbState } from '../state.js';
import { _BBOX_FLOORS } from './track-loss-tooltip.js';
import {
  _interpolateTrackAt,
  _isPointInAnyMask,
  _resolveMaskPolygonsForCam,
} from './renderer.js';
import { _getHiddenClassesForCam } from './hidden-classes.js';

function _ensureConfidenceMeter(){
  let host = byId('lightboxConfidenceMeter');
  if (host) return host;
  const wrap = byId('lightboxMediaWrap');
  if (!wrap) return null;
  host = document.createElement('div');
  host.id = 'lightboxConfidenceMeter';
  host.hidden = true;
  wrap.appendChild(host);
  return host;
}

function _findActiveTracksAt(currentTime, opts = {}){
  const tracks = lbState.item?._tracks?.tracks || [];
  const out = [];
  const hidden = opts.hidden || new Set();
  const masks = opts.masks || [];
  const natW = opts.natW || 0;
  const natH = opts.natH || 0;
  for (const tr of tracks){
    // Filter out hidden classes (the per-class toggle in the
    // timeline-panel sidebar) so toggling a class off also
    // removes it from the characteristic card.
    if (hidden.has(tr.label)) continue;
    const sample = _interpolateTrackAt(tr, currentTime);
    if (!sample) continue;
    // Filter out masked-out tracks — same ground-point-in-mask
    // test the bbox renderer uses, so the card stays aligned
    // with which boxes are actually surfaced as alerting.
    if (masks.length){
      const bb = sample.bbox || {};
      const cx = (bb.x1 + bb.x2) / 2;
      const cy = bb.y2;
      if (_isPointInAnyMask(cx, cy, natW, natH, masks)) continue;
    }
    out.push({ track: tr, sample, num: tr._num || 0 });
  }
  return out;
}

// Amber used when a Score gauge's value sits below the configured
// threshold — the gauge fills with class colour when ≥ threshold so
// the operator's eye lands on under-threshold tracks immediately.
// Matches the warning hue used elsewhere in the chrome (heartbeat
// pill, inference status, telegram badge).
const _GAUGE_AMBER = '#f59e0b';

function _buildMeterRow(label, valFrac, thresholdFrac, color, opts = {}){
  // Both values are 0..1. Bar maps the value to width%; tick to
  // (threshold * 100)%. The threshold-pct rendered above the tick is
  // the integer percent for a stable mono-width readout.
  //
  // opts.showTick — pass false for the Bbox rows (per the task #5
  // mockup: only Score carries a Settings-Limit tick marker; the
  // bbox-frac gauges have no configurable threshold to mark).
  // opts.amberBelowThreshold — when true (Score row), fill colour
  // flips to amber whenever valFrac < thresholdFrac.
  const valPct = Math.min(100, Math.max(0, valFrac * 100));
  const tickPct = Math.min(100, Math.max(0, (thresholdFrac ?? 0) * 100));
  const tickNum = Math.round(tickPct);
  const showPct = Math.round(valPct);
  const showTick = opts.showTick !== false && thresholdFrac != null;
  const fillColor = (opts.amberBelowThreshold
                     && thresholdFrac != null
                     && valFrac < thresholdFrac)
                    ? _GAUGE_AMBER : color;
  return `
    <div class="lbcm-row">
      <div class="lbcm-row-head">
        <span class="lbcm-row-label">${label}</span>
        <span class="lbcm-row-pct">${showPct} %</span>
      </div>
      <div class="lbcm-row-bar">
        <span class="lbcm-row-fill" style="width:${valPct.toFixed(1)}%;background:${fillColor}"></span>
        ${showTick
          ? `<span class="lbcm-row-tick" style="left:${tickPct.toFixed(1)}%"></span>
             <span class="lbcm-row-tick-num" style="left:${tickPct.toFixed(1)}%">${tickNum}</span>`
          : ''}
      </div>
    </div>`;
}

// Legend strip rendered once below the gauge rows. The block-quarter
// glyph (▍) matches the Score tick visual (a vertical 2 px line);
// the small square (▪) hints at the filled bar segment. Kept inline
// in the pill so the operator doesn't need to hover for what the
// tick means.
const _GAUGE_LEGEND_HTML = `
  <div class="lbcm-legend" aria-hidden="true">
    <span class="lbcm-legend-item"><span class="lbcm-legend-tick">▍</span> Settings-Limit</span>
    <span class="lbcm-legend-item"><span class="lbcm-legend-fill">▪</span> Messwert</span>
  </div>`;

export function _renderConfidenceMeter(){
  const v = byId('lightboxVideo');
  const host = _ensureConfidenceMeter();
  if (!host || !v || !lbState.item){
    if (host) host.hidden = true;
    return;
  }
  // Only paint in full-screen video mode — photo events / timelapse
  // shouldn't see this pill at all.
  if (!byId('lightboxModal')?.classList.contains('lb-fs-video')){
    host.hidden = true;
    return;
  }
  const t = Number.isFinite(v.currentTime) ? v.currentTime : 0;
  const natW = v.videoWidth || 1;
  const natH = v.videoHeight || 1;
  const camId = lbState.item.camera_id || '';
  const hidden = _getHiddenClassesForCam(camId);
  const masks  = _resolveMaskPolygonsForCam(camId);
  const active = _findActiveTracksAt(t, { hidden, masks, natW, natH });
  if (active.length === 0){
    host.hidden = true;
    return;
  }
  const rs = lbState.item.recording_settings;
  const hasRs = !!(rs && typeof rs === 'object'
                   && (rs.mode || rs.conf_thresh_general != null));
  // H3 · the card now lists ALL currently-visible / non-masked
  // tracks (was capped at 2). Hidden classes + masked-out subjects
  // were filtered upstream so what survives is by definition
  // worth showing.
  const blocks = active.map(({ track, sample, num }) => {
    const lbl = OBJ_LABEL[track.label] || track.label || '?';
    // H3 · header color is the TRACK's per-clip identity color so
    // the card visually links to the box + the timeline lane for
    // the same person. The per-class palette is a fallback for
    // legacy sidecars that never stamped tr.color.
    const c = track.color || colors[track.label] || colors.unknown;
    // Score threshold: per-class override else general floor — only
    // read when the clip actually has recording_settings captured.
    // Older clips fall back to a missing tick + a subtitle note.
    let scoreThresh = null;
    if (hasRs){
      scoreThresh = rs.conf_thresh_general ?? null;
      const perCls = rs.conf_thresh_per_class || {};
      if (Object.prototype.hasOwnProperty.call(perCls, track.label)){
        scoreThresh = perCls[track.label];
      }
    }
    const rows = [];
    rows.push(_buildMeterRow(
      'Score', sample.score || 0,
      scoreThresh != null ? parseFloat(scoreThresh) : null, c,
      { showTick: hasRs, amberBelowThreshold: true }));
    // Older sidecars (schema < 2) don't carry last_bbox_frac_*. Fall
    // back to computing the bbox fraction from the current sample's
    // pixel coords so the gauge stays useful — but prefer the
    // sidecar value when available (it's the LAST observed bbox of
    // the track, which matches what the worker uses to evaluate the
    // per-class minimum-size gate).
    const floors = _BBOX_FLOORS[track.label];
    if (floors){
      let fracH = track.last_bbox_frac_h;
      let fracArea = track.last_bbox_frac_area;
      if (fracH == null || fracArea == null){
        const bb = sample.bbox || {};
        const bbW = Math.max(0, (bb.x2 || 0) - (bb.x1 || 0));
        const bbH = Math.max(0, (bb.y2 || 0) - (bb.y1 || 0));
        if (fracH == null) fracH = bbH / natH;
        if (fracArea == null) fracArea = (bbW * bbH) / (natW * natH);
      }
      if (floors.min_h_frac > 0){
        rows.push(_buildMeterRow(
          'Bbox-Höhe', fracH, null, c, { showTick: false }));
      }
      if (floors.min_area_frac > 0){
        rows.push(_buildMeterRow(
          'Bbox-Fläche', fracArea, null, c, { showTick: false }));
      }
    }
    const missingNote = hasRs
      ? ''
      : `<div class="lbcm-missing">Schwelle nicht aufgezeichnet</div>`;
    return `
      <div class="lbcm-track">
        <div class="lbcm-track-head" style="color:${c}">${lbl} #${num}</div>
        ${missingNote}
        ${rows.join('')}
      </div>`;
  }).join('');
  host.innerHTML = `${blocks}${_GAUGE_LEGEND_HTML}`;
  host.hidden = false;
}
