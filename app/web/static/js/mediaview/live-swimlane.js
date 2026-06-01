// ─── mediaview/live-swimlane.js ───────────────────────────────────────────
// SIMU-03 / J · Live-Detect timeline renderer.
//
// The recorded-clip swimlane renderer in mediathek/bbox-overlay/
// timeline-panel.js is built around a scrubber bar + ticks + per-class
// strips + play cursor. Live-Detect has no scrubber (the window is always
// "live 60 s ago → now"). J reworks the lanes from per-CLASS to per-TRACK:
// one lane per active track, coloured by the track number (matching the
// bbox), with bars flowing right → now and dropping off the left edge after
// 60 s. Motion-only detections (no track number) collapse into one neutral
// grey lane so an unfiltered room can't flood the strip.
//
// Caller contract:
//   renderLiveSwimlane(host, { camId, detBuffer, windowMs })
//
// Lane structure rebuilds only when the set of lanes (or their colours)
// changes; between rebuilds each event cell's bars are re-synced so the strip
// flows leftward.

import { esc } from '../core/dom.js';
import { OBJ_LABEL, OBJ_SVG } from '../core/icons.js';
import { liveTrackColor, LIVE_MOTION_COLOR } from '../core/track-color.js';

// Lane id for the catch-all motion lane (detections without a track number).
const _MOTION_ID = '__motion__';
const _MASKED_COLOR = '#64748b';

export function renderLiveSwimlane(host, opts = {}) {
  if (!host) return;
  const detBuffer = Array.isArray(opts.detBuffer) ? opts.detBuffer : [];
  const windowMs = Number(opts.windowMs) || 60_000;
  const lanes = _computeLanes(detBuffer, windowMs);
  // Lane-structure fingerprint — rebuild only when lane membership or colour
  // changes so bar elements survive across ticks.
  const fp = lanes.map((l) => `${l.id}:${l.color}`).join('|');
  if (host.dataset.mvLdFp !== fp) {
    host.innerHTML = _buildStructure(lanes);
    host.dataset.mvLdFp = fp;
  }
  for (let i = 0; i < lanes.length; i++) {
    const cell = host.querySelector(`.mv-ld-swim-cell-events[data-lane-idx="${i}"]`);
    if (!cell) continue;
    _syncBars(cell, lanes[i], windowMs);
  }
}

// J3 · group the 60 s detection window into per-TRACK lanes. Detections with a
// positive track_num bucket by that number; everything else collapses into one
// neutral motion lane. Lane colour matches the bbox: a normal track uses its
// track colour, an off-filter (masked) track uses slate, motion uses grey.
function _computeLanes(detBuffer, windowMs) {
  const now = Date.now();
  const cutoff = now - windowMs;
  const byKey = new Map();
  for (const e of detBuffer) {
    if (!e || e.ms < cutoff) continue;
    const hasTrack = Number.isFinite(e.track_num) && e.track_num > 0;
    const key = hasTrack ? `t${e.track_num}` : _MOTION_ID;
    let lane = byKey.get(key);
    if (!lane) {
      lane = { id: key, num: hasTrack ? e.track_num : null, label: e.label, samples: [] };
      byKey.set(key, lane);
    }
    lane.samples.push(e);
    lane.label = e.label; // push-order ≈ chronological → most-recent class wins
    lane.lastVerdict = e.verdict;
  }
  const lanes = Array.from(byKey.values());
  lanes.sort((a, b) => {
    if (a.id === _MOTION_ID) return 1;
    if (b.id === _MOTION_ID) return -1;
    return (a.num || 0) - (b.num || 0);
  });
  for (const lane of lanes) {
    lane.color =
      lane.id === _MOTION_ID
        ? LIVE_MOTION_COLOR
        : lane.lastVerdict === 'filtered'
          ? _MASKED_COLOR
          : liveTrackColor(lane.num);
  }
  return lanes;
}

// J5 · the swimlane is a labelled panel: "Timeline · letzte 60 s" heading, a
// CSS-grid of per-track lanes (44 px label column + elastic event column),
// vertical time gridlines behind the lanes, and the green LIVE marker pinned
// to the right edge that bars flow into.
function _buildStructure(lanes) {
  const cells = [];
  for (let i = 0; i < lanes.length; i++) {
    cells.push(_renderLaneCells(lanes[i], i, i + 1));
  }
  const axisLabels = ['60 s', '45 s', '30 s', '15 s', 'jetzt'];
  const lastIdx = axisLabels.length - 1;
  const axisHtml = axisLabels
    .map(
      (txt, i) =>
        `<span class="mv-ld-axis-tick" style="left:calc(${(i * 100) / lastIdx}% - ${i === 0 ? 0 : i === lastIdx ? 24 : 12}px)">${esc(txt)}</span>`,
    )
    .join('');
  // Vertical time gridlines at the same ticks, behind the lanes.
  const gridlines = axisLabels
    .map((_, i) => `<span class="mv-ld-swim-gridline" style="left:${(i * 100) / lastIdx}%"></span>`)
    .join('');
  const liveMarker =
    '<div class="mv-ld-swim-live" aria-hidden="true">' +
    '<span class="mv-ld-swim-pill"><span class="mv-ld-swim-pill-dot"></span><span class="mv-ld-swim-pill-lbl">LIVE</span></span>' +
    '<span class="mv-ld-swim-line"></span>' +
    '</div>';
  return `
    <div class="mv-ld-swim" data-lane-count="${lanes.length}">
      <div class="mv-ld-swim-heading">Timeline<span class="mv-ld-swim-heading-sub"> · letzte 60 s</span></div>
      <div class="mv-ld-swim-grid" data-rows="${lanes.length}">
        <div class="mv-ld-swim-gridlines" aria-hidden="true">${gridlines}</div>
        ${cells.join('')}${liveMarker}
      </div>
      <div class="mv-ld-swim-axis"><div class="mv-ld-swim-axis-track">${axisHtml}</div></div>
    </div>`;
}

function _renderLaneCells(lane, idx, gridRow) {
  const labelCell = _renderLaneLabel(lane);
  return (
    `<div class="mv-ld-swim-cell mv-ld-swim-cell-label" data-lane-idx="${idx}" style="grid-row:${gridRow};grid-column:1">${labelCell}</div>` +
    `<div class="mv-ld-swim-cell mv-ld-swim-cell-events" data-lane-idx="${idx}" style="grid-row:${gridRow};grid-column:2"></div>`
  );
}

// J4 · the lane's object-class icon, flat-tinted in the lane's track colour
// (one per lane), so the colour reads as the track and the glyph as the class.
function _renderLaneLabel(lane) {
  const isMotion = lane.id === _MOTION_ID;
  const title = isMotion
    ? 'Bewegung (ohne Track)'
    : `${OBJ_LABEL[lane.label] || lane.label} · Track #${lane.num}`;
  return `<span class="mv-ld-swim-icon" title="${esc(title)}">${_tintedIcon(lane.label, lane.color)}</span>`;
}

// Flat-tint an OBJ_SVG glyph to a single colour — the class hue no longer
// carries meaning (colour = track number), so every hex fill/stroke becomes
// the track colour. fill="none" + rgba shading are left intact so stroke-only
// icons (e.g. motion) still draw rather than collapsing into solid blobs.
// `color` is always an internal palette constant, never user input.
function _tintedIcon(label, color) {
  const raw = OBJ_SVG[label] || OBJ_SVG.motion;
  return raw.replaceAll(/(fill|stroke)="#[0-9a-fA-F]{3,8}"/g, `$1="${color}"`);
}

// Q2-1 / J · cluster a lane's detections into chips so dense strips stay
// readable, then paint every chip in the lane (track) colour with a thin
// connector line behind them. Walk right → left so each cluster anchors at its
// newest member and the strip reads "now" on the right. The cell rebuilds each
// tick (no CSS transition); clustering caps the chip count so it stays cheap.
const _CHIP_W = 24; // nominal chip width (px) for the merge heuristic
const _MERGE_GAP_PX = 6; // merge when the gap would be < 6 px
function _syncBars(cell, lane, windowMs) {
  const now = Date.now();
  const c = lane.color;
  const cellW = cell.clientWidth || 0;
  const items = [];
  for (const s of lane.samples) {
    const ageMs = now - s.ms;
    if (ageMs < 0 || ageMs > windowMs) continue;
    items.push({ pct: 100 - (ageMs / windowMs) * 100 });
  }
  // Newest (rightmost) first so the greedy walk absorbs older neighbours.
  items.sort((a, b) => b.pct - a.pct);
  const chips = [];
  let cur = null;
  for (const it of items) {
    const rightPx = cellW > 0 ? (it.pct / 100) * cellW : null;
    if (cur && rightPx != null && cur.leftPx != null && cur.leftPx - rightPx < _MERGE_GAP_PX) {
      cur.count += 1;
    } else {
      if (cur) chips.push(cur);
      cur = { rightPct: it.pct, leftPx: rightPx != null ? rightPx - _CHIP_W : null, count: 1 };
    }
  }
  if (cur) chips.push(cur);
  // J4 · connector line in the lane colour through the vertical centre, behind
  // the bars, spanning the event column up to the LIVE marker on the right.
  const conn = `<span class="mv-ld-swim-conn" style="background:${c}"></span>`;
  cell.innerHTML =
    conn +
    chips
      .map((ch) => {
        const label = ch.count > 1 ? `×${ch.count}` : '';
        const left = `calc(${ch.rightPct.toFixed(2)}% - ${_CHIP_W}px)`;
        const title = ch.count > 1 ? `${ch.count} Detektionen` : '1 Detektion';
        return (
          `<span class="mv-ld-swim-bar" style="left:${left};background:${c}" title="${esc(title)}">` +
          (label ? `<span class="mv-ld-swim-chip-lbl">${esc(label)}</span>` : '') +
          '</span>'
        );
      })
      .join('');
}
