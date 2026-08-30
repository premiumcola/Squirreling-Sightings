// ─── mediaview/live-detect-bbox.js ─────────────────────────────────────────
// The live bbox SVG overlay: pick which detections to paint (live tick,
// falling back to the hold-time buffer), size the viewBox to the snapshot,
// align the layer with the visible picture, paint one group per detection.
//
// The letterbox positioner lives in live-detect-bbox-fit.js (trails reuse
// it); the per-detection shapes live in live-detect-bbox-shapes.js. Reads
// state via S.
import { S } from './live-detect-state.js';
import {
  _debugDiagOn,
  _updateDiagStrip,
  _refreshMediaRow,
  _collectBboxDiagFields,
} from './live-detect-diag.js';
import { _ensureBboxOverlay } from './live-detect-overlays.js';
import { _renderDetailPill } from './live-detect-panels.js';
import { _positionSvgOverImage } from './live-detect-bbox-fit.js';
import { _overlayScale, _buildBboxGroup } from './live-detect-bbox-shapes.js';
import { _HOLD_MS_CEILING } from './live-detect.js';
import { paintableLabels } from './live-detect-classfilter.js';

// gp384 / C84 — hold-time merge. Prefer the live tick's detections (full
// opacity). If the tick is empty, fall back to the most recent detection
// per label from S.detBuffer — each entry carries its age so the render
// can fade the box out over the active hold-time (dynamic per cadence,
// see C84). One entry per label is enough; older entries on the same
// label are dominated by the most-recent one's opacity anyway. holdMs
// falls back to the legacy 1500 ms ceiling until the first cycle EMA
// observation lands, so the first tick still gets a sensible hold.
function _heldDetections() {
  const holdMs = Number.isFinite(S.holdMsActive) ? S.holdMsActive : _HOLD_MS_CEILING;
  // Foreign COCO classes are not painted — see live-detect-classfilter.js.
  const want = paintableLabels();
  const keep = (label) => !want || want.has(label);
  const live = (S.session.lastDetections || []).filter((d) => keep(d.label));
  if (live.length) return live.map((d) => ({ ...d, _holdMul: 1 }));
  const now = Date.now();
  const seen = new Set();
  const held = [];
  for (let i = S.detBuffer.length - 1; i >= 0; i--) {
    const e = S.detBuffer[i];
    const age = now - e.ms;
    if (age > holdMs) break; // push-order → everything older follows
    if (seen.has(e.label)) continue; // one box per label, most-recent wins
    seen.add(e.label);
    if (!keep(e.label)) continue;
    held.push({
      label: e.label,
      score: e.score,
      bbox: e.bbox,
      verdict: e.verdict,
      track_num: e.track_num,
      _holdMul: Math.max(0, 1 - age / holdMs),
    });
  }
  return held;
}

export function _renderBboxOverlay() {
  // SIMU-FIX-03b · the bbox SVG's visibility is gated SOLELY by the
  // `S.overlays.bboxes` boolean. The toggle pill is a CONTROL for that
  // boolean, never a GATE for the painting.
  const svg = _ensureBboxOverlay();
  if (!svg || !S.session) return;
  svg.style.display = S.overlays.bboxes ? 'block' : 'none';
  if (!S.overlays.bboxes) {
    svg.innerHTML = '';
    return;
  }
  const fs = S.session.lastFrameSize || { w: 1920, h: 1080 };
  // The backend states its bbox coordinate space in data.frame_size (=
  // the snapshot's pixel dims after the ≤960 px downscale, with the box
  // coords rewritten to match). Using it verbatim as the viewBox is what
  // keeps box and picture in one space — never substitute the element's
  // displayed size here.
  svg.setAttribute('viewBox', `0 0 ${fs.w} ${fs.h}`);
  _positionSvgOverImage(svg);
  _refreshMediaRow();
  if (_debugDiagOn()) {
    const diag = _collectBboxDiagFields(svg, fs);
    _updateDiagStrip('bbox', diag.fields, diag.opts);
  }
  const rect = svg.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) {
    _updateDiagStrip('position-fail', {
      svg: svg.id,
      svgRect: `${Math.round(rect.width)}×${Math.round(rect.height)}`,
    });
    svg.innerHTML = '';
    return;
  }
  const k = _overlayScale(fs.w, rect.width);
  svg.innerHTML = _heldDetections()
    .map((d) =>
      _buildBboxGroup(d, {
        k,
        frameW: fs.w,
        holdMul: d._holdMul,
        selected: S.selectedLabel === d.label,
      }),
    )
    .join('');
  // Click a box → pin/unpin its detail pill.
  svg.style.pointerEvents = 'auto';
  svg.querySelectorAll('[data-label]').forEach((g) => {
    g.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const lbl = g.dataset.label;
      S.selectedLabel = S.selectedLabel === lbl ? null : lbl;
      _renderBboxOverlay();
      _renderDetailPill();
    });
  });
}

// Per-label trail cap — newest N centroids drawn behind the box. Matches
// the batch-A Mediathek trail (mediaview/canvas/trail-layer.js) so the
// recorded and live UIs read identically.
export const _LIVE_TRAIL_MAX_POINTS = 20;
