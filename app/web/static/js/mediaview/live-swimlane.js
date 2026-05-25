// ─── mediaview/live-swimlane.js ───────────────────────────────────────────
// SIMU-03 · Live-Detect timeline renderer.
//
// The recorded-clip swimlane renderer in mediathek/bbox-overlay/
// timeline-panel.js is built around a scrubber bar + ticks + per-
// class strips + play cursor. Live-Detect doesn't have a scrubber
// (the window is always "live 60 s ago → now"), the visual language
// is icon-only lanes, the LIVE marker sits stacked above a single
// vertical green line spanning all lanes, bars flow right → left
// and drop off the left edge after 60 s. Trying to bend the recorded
// renderer to all of that would compromise both code paths; this
// dedicated renderer keeps the recorded one untouched.
//
// Caller contract:
//   renderLiveSwimlane(host, {
//     camId, detBuffer, windowMs, objectFilter,
//   })
//
// SIMU-03e · the renderer does TARGETED bar updates between ticks
// (existing bar's `left` is updated, CSS transitions over 500 ms)
// so the strip flows leftward smoothly instead of jumping in
// discrete tick-sized steps. Lane structure rebuilds only when the
// set of lanes changes (a new class appears, andere lane toggles).

import { esc } from '../core/dom.js';
import { OBJ_LABEL, OBJ_SVG, colors } from '../core/icons.js';

const _LANE_LABEL_ORDER = Object.keys(OBJ_LABEL);
const _ANDERE_ID = '__andere__';

export function renderLiveSwimlane(host, opts = {}) {
  if (!host) return;
  const detBuffer = Array.isArray(opts.detBuffer) ? opts.detBuffer : [];
  const windowMs = Number(opts.windowMs) || 60_000;
  const objectFilter = opts.objectFilter instanceof Set ? opts.objectFilter : null;
  const lanes = _computeLanes(detBuffer, windowMs, objectFilter);
  // Lane-structure fingerprint — rebuild only when lane membership
  // changes so bar elements survive across ticks (CSS `left`
  // transition then animates the leftward flow).
  const fp = lanes.map((l) => l.id).join('|');
  if (host.dataset.mvLdFp !== fp) {
    host.innerHTML = _buildStructure(lanes);
    host.dataset.mvLdFp = fp;
  }
  for (let i = 0; i < lanes.length; i++) {
    const lane = lanes[i];
    // SIMU-FIX-04b · SIMU-03g refactored the swimlane into a single
    // CSS grid, removing the `.mv-ld-swim-row` wrapper. The bar-sync
    // query was never updated to match the new structure → no cell
    // was ever found → no bars were ever appended. Query the event
    // cell directly by its lane-idx data attribute.
    const cell = host.querySelector(
      `.mv-ld-swim-cell-events[data-lane-idx="${i}"]`,
    );
    if (!cell) continue;
    // POLISH-01b · the Andere lane is a STATUS COUNTER, not a
    // visualisation. Render a single "Andere · N" pill instead of a
    // bar per off-filter detection (which flooded the lane with grey
    // dashed hash-noise + meaningless track-num badges on a TV-heavy
    // room). Per-class lanes keep their flowing bars.
    if (lane.id === _ANDERE_ID) {
      _renderAndereCounter(cell, lane);
    } else {
      _syncBars(cell, lane, windowMs);
    }
  }
}

// POLISH-01b · render the Andere lane's counter pill. N = total
// off-filter detections in the 60 s window. The pill carries a
// title attr with the top-3 class breakdown (browser-native
// long-press tooltip on iOS, hover on desktop) so the user can see
// WHAT was filtered without the lane screaming.
function _renderAndereCounter(cell, lane) {
  const byClass = lane.andereByClass || new Map();
  let total = 0;
  for (const n of byClass.values()) total += n;
  const top = Array.from(byClass.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([cls, n]) => `${cls} ${n}×`)
    .join(' · ');
  const title = total > 0 ? top : 'keine off-filter Detektionen';
  cell.innerHTML =
    `<span class="mv-ld-andere-counter" title="${esc(title)}">andere · ${total}</span>`;
}

function _computeLanes(detBuffer, windowMs, objectFilter) {
  const now = Date.now();
  const cutoff = now - windowMs;
  const byLabel = new Map();
  const andereByClass = new Map();
  for (const e of detBuffer) {
    if (!e || e.ms < cutoff) continue;
    if (objectFilter && !objectFilter.has(e.label)) {
      andereByClass.set(e.label, (andereByClass.get(e.label) || 0) + 1);
      _bucket(byLabel, _ANDERE_ID, e);
      continue;
    }
    _bucket(byLabel, e.label, e);
  }
  const labels = _sortedLabels(byLabel.keys());
  const lanes = [];
  for (const lbl of labels) {
    if (lbl === _ANDERE_ID) continue;
    lanes.push({ id: lbl, label: lbl, samples: byLabel.get(lbl) || [] });
  }
  if (objectFilter) {
    lanes.push({
      id: _ANDERE_ID,
      label: 'andere',
      samples: byLabel.get(_ANDERE_ID) || [],
      andereByClass,
    });
  }
  return lanes;
}

function _bucket(map, key, entry) {
  if (!map.has(key)) map.set(key, []);
  map.get(key).push(entry);
}

function _sortedLabels(iter) {
  const arr = Array.from(iter);
  arr.sort((a, b) => {
    if (a === _ANDERE_ID) return 1;
    if (b === _ANDERE_ID) return -1;
    const ai = _LANE_LABEL_ORDER.indexOf(a);
    const bi = _LANE_LABEL_ORDER.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
  return arr;
}

// SIMU-03g · single CSS-grid layout for the entire swimlane. The
// container is `display: grid; grid-template-columns: 36px 1fr;
// grid-auto-rows: 22px`. Per lane we emit BOTH the label cell and
// the event cell in a single pass with the SAME `grid-row`, which
// is the spec's guarantee against label ↔ event drift. The LIVE
// pill + vertical line span the full row range via grid-row: 1/-1
// and live in column 2 (right of the label band).
function _buildStructure(lanes) {
  const cells = [];
  for (let i = 0; i < lanes.length; i++) {
    cells.push(_renderLaneCells(lanes[i], i, i + 1));
  }
  const axisLabels = ['60 s', '45 s', '30 s', '15 s', 'jetzt'];
  const axisHtml = axisLabels
    .map(
      (txt, i) =>
        `<span class="mv-ld-axis-tick" style="left:calc(${(i * 100) / (axisLabels.length - 1)}% - ${i === 0 ? 0 : i === axisLabels.length - 1 ? 24 : 12}px)">${esc(txt)}</span>`,
    )
    .join('');
  const liveMarker =
    '<div class="mv-ld-swim-live" aria-hidden="true">' +
    '<span class="mv-ld-swim-pill"><span class="mv-ld-swim-pill-dot"></span><span class="mv-ld-swim-pill-lbl">LIVE</span></span>' +
    '<span class="mv-ld-swim-line"></span>' +
    '</div>';
  return `
    <div class="mv-ld-swim" data-lane-count="${lanes.length}">
      <div class="mv-ld-swim-grid" data-rows="${lanes.length}">${cells.join('')}${liveMarker}</div>
      <div class="mv-ld-swim-axis"><div class="mv-ld-swim-axis-track">${axisHtml}</div></div>
    </div>`;
}

function _renderLaneCells(lane, idx, gridRow) {
  const isAndere = lane.id === _ANDERE_ID;
  const labelCell = _renderLaneLabel(lane, isAndere);
  const andereAttr = isAndere ? ' data-andere="1"' : '';
  // Wrapped in a fragment-style pair so the renderer signals the
  // label and the event row together — same grid-row stamp on both.
  return (
    `<div class="mv-ld-swim-cell mv-ld-swim-cell-label" data-lane-idx="${idx}" data-label="${esc(lane.label)}"${andereAttr} style="grid-row:${gridRow};grid-column:1">${labelCell}</div>` +
    `<div class="mv-ld-swim-cell mv-ld-swim-cell-events" data-lane-idx="${idx}" data-label="${esc(lane.label)}"${andereAttr} style="grid-row:${gridRow};grid-column:2"></div>`
  );
}

function _renderLaneLabel(lane, isAndere) {
  if (isAndere) {
    const n = lane.andereByClass ? lane.andereByClass.size : 0;
    const title = n > 0 ? _andereTooltip(lane.andereByClass) : 'andere · keine Detektionen';
    return (
      '<span class="mv-ld-swim-icon mv-ld-swim-icon-andere" aria-hidden="true" ' +
      `title="${esc(title)}">` +
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<circle cx="6" cy="12" r="1.8" fill="#3d4654"/>' +
      '<circle cx="12" cy="12" r="1.8" fill="#3d4654"/>' +
      '<circle cx="18" cy="12" r="1.8" fill="#3d4654"/></svg>' +
      '</span>'
    );
  }
  const raw = OBJ_SVG[lane.label] || '';
  if (!raw) {
    return '<span class="mv-ld-swim-icon" aria-hidden="true"><span class="mv-ld-swim-icon-fallback"></span></span>';
  }
  return `<span class="mv-ld-swim-icon" aria-hidden="true">${raw}</span>`;
}

function _andereTooltip(byClass) {
  if (!byClass || byClass.size === 0) return 'andere · keine Detektionen';
  const parts = [];
  const sorted = Array.from(byClass.entries()).sort((a, b) => b[1] - a[1]);
  for (const [cls, n] of sorted) {
    parts.push(`${cls} (${n})`);
  }
  return `andere · ${parts.join(' · ')}`;
}

// Q2-1 · render a lane's detections as CLUSTERED chips. Dense
// detections used to stack as microscopic 10 px bars whose #N badges
// overlapped into unreadable "compressed Morse". We now merge any two
// chips that would sit <6 px apart into a single "#K ×N" chip, walking
// right→left so each cluster anchors at its newest member and the
// strip still reads "now" on the right. The cell is rebuilt each tick
// (no CSS transition — see the .mv-ld-swim-bar note in 30f); clustering
// caps the chip count per lane so the rebuild stays cheap.
const _CHIP_W = 24; // nominal chip width (px) for the merge heuristic
const _MERGE_GAP_PX = 6; // spec: merge when the gap would be <6 px
function _syncBars(cell, lane, windowMs) {
  const now = Date.now();
  const c = colors[lane.label] || colors.unknown;
  // Event-column pixel width turns the <6 px heuristic into a real
  // distance. 0 before first layout → one chip per sample (coarse but
  // never crashes).
  const cellW = cell.clientWidth || 0;
  const items = [];
  for (const s of lane.samples) {
    const ageMs = now - s.ms;
    if (ageMs < 0 || ageMs > windowMs) continue;
    items.push({ pct: 100 - (ageMs / windowMs) * 100, track_num: s.track_num });
  }
  // Newest (rightmost) first so the greedy walk absorbs older
  // neighbours leftward into the most-recent member.
  items.sort((a, b) => b.pct - a.pct);
  const chips = [];
  let cur = null;
  for (const it of items) {
    const rightPx = cellW > 0 ? (it.pct / 100) * cellW : null;
    // Merge when this (older) chip's right edge lands within _MERGE_GAP_PX
    // of the current cluster's left edge — i.e. the gap between "previous
    // chip ends" and "next chip starts" is <6 px.
    if (cur && rightPx != null && cur.leftPx != null && cur.leftPx - rightPx < _MERGE_GAP_PX) {
      cur.count += 1;
    } else {
      if (cur) chips.push(cur);
      cur = {
        rightPct: it.pct,
        leftPx: rightPx != null ? rightPx - _CHIP_W : null,
        count: 1,
        track_num: it.track_num, // newest member = representative #K
      };
    }
  }
  if (cur) chips.push(cur);
  cell.innerHTML = chips
    .map((ch) => {
      const hasTrack = Number.isFinite(ch.track_num) && ch.track_num > 0;
      let label = '';
      if (hasTrack && ch.count > 1) label = `#${ch.track_num} ×${ch.count}`;
      else if (hasTrack) label = `#${ch.track_num}`;
      else if (ch.count > 1) label = `×${ch.count}`;
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
