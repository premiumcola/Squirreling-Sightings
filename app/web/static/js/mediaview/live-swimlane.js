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
import { mvStatusCategory } from './status-legend.js';

// Lane id for the catch-all motion lane (detections without a track number).
const _MOTION_ID = '__motion__';

// ── Do filtered detections belong in the timeline at all? ──────────────
// Yes, but folded away. Three arguments decided it:
//
//  · Dropping them would make the timeline lie by omission. A workbench
//    recognised at 46 % nine times a minute IS what the detector is
//    spending its inferences on, and the operator's next move — adding
//    "bench" to the class filter — is one they can only decide to make if
//    they can see how much noise there is.
//  · Showing them inline crowds out the real ones. That is the reported
//    symptom: a strip dense with grey blocks, with the one track that
//    matters lost among them. Lanes are equal-height rows, so N filtered
//    tracks cost exactly as much vertical space as N real ones.
//  · So: segregated and collapsed by default, with a count in the toggle.
//    The information stays reachable in one tap and stops competing for
//    the same pixels. A lane counts as filtered only when EVERY sample in
//    the 60 s window was filtered — a track that passed even once is a
//    real track having a bad frame, not noise.
const _FILTERED_KEY = 'tam.ld.swim.filtered';
let _showFiltered = _loadShowFiltered();

function _loadShowFiltered() {
  try {
    return localStorage.getItem(_FILTERED_KEY) === '1';
  } catch {
    return false; // private mode / quota — default to the calm state
  }
}

function _saveShowFiltered() {
  try {
    localStorage.setItem(_FILTERED_KEY, _showFiltered ? '1' : '0');
  } catch {
    /* private mode / quota — the session-local flag still works */
  }
}

export function renderLiveSwimlane(host, opts = {}) {
  if (!host) return;
  const detBuffer = Array.isArray(opts.detBuffer) ? opts.detBuffer : [];
  const windowMs = Number(opts.windowMs) || 60_000;
  const { active, filtered } = _computeLanes(detBuffer, windowMs);
  const lanes = _showFiltered ? active.concat(filtered) : active;
  // Lane-structure fingerprint — rebuild only when lane membership, colour
  // or the fold state changes so bar elements survive across ticks.
  const fp =
    `${_showFiltered ? 1 : 0}/${filtered.length}|` +
    lanes.map((l) => `${l.id}:${l.color}:${l.filtered ? 'f' : 'a'}`).join('|');
  if (host.dataset.mvLdFp !== fp) {
    host.innerHTML = _buildStructure(lanes, filtered.length);
    host.dataset.mvLdFp = fp;
    _wireFilteredToggle(host, opts);
  }
  for (let i = 0; i < lanes.length; i++) {
    const cell = host.querySelector(`.mv-ld-swim-cell-events[data-lane-idx="${i}"]`);
    if (!cell) continue;
    _syncBars(cell, lanes[i], windowMs);
  }
}

// The toggle re-renders through the public entry so the fold state and the
// lane structure can never drift apart.
function _wireFilteredToggle(host, opts) {
  host.querySelector('[data-action="swim-filtered"]')?.addEventListener('click', (ev) => {
    ev.stopPropagation();
    _showFiltered = !_showFiltered;
    _saveShowFiltered();
    host.dataset.mvLdFp = '';
    renderLiveSwimlane(host, opts);
  });
}

// J3 · group the 60 s detection window into per-TRACK lanes. Detections with a
// positive track_num bucket by that number; everything else collapses into one
// neutral motion lane. Lane colour matches the bbox exactly — the track
// colour, or grey for the track-less motion lane. Returns the lanes split
// into `active` and `filtered` (see the fold rationale at the top).
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
    // COLOUR IS THE TRACK NUMBER. Nothing else. The legend says so in as
    // many words ("Farbe = Person-Nr."), the bbox stroke and the trail
    // polyline both derive it from track_num alone — and this lane used to
    // override it to slate whenever the track's last verdict was
    // "filtered". That is why an orange trail on the picture had no orange
    // anywhere in the strip below it: same track, two different hues, one
    // of them encoding STATUS in a channel reserved for IDENTITY. Status
    // now travels the way the legend already documents it: line style and
    // opacity (see .mv-ld-swim-cell[data-status]).
    lane.color = lane.id === _MOTION_ID ? LIVE_MOTION_COLOR : liveTrackColor(lane.num);
    lane.status = mvStatusCategory(lane.lastVerdict);
    // Filtered only when the whole window was filtered — one pass makes it
    // a real track, not noise.
    lane.filtered =
      lane.samples.length > 0 && lane.samples.every((s) => s.verdict === 'filtered');
  }
  return {
    active: lanes.filter((l) => !l.filtered),
    filtered: lanes.filter((l) => l.filtered),
  };
}

// J5 · the swimlane is a labelled panel: "Timeline · letzte 60 s" heading, a
// CSS-grid of per-track lanes (44 px label column + elastic event column),
// vertical time gridlines behind the lanes, and the green LIVE marker pinned
// to the right edge that bars flow into.
function _buildStructure(lanes, filteredCount) {
  const cells = [];
  for (let i = 0; i < lanes.length; i++) {
    cells.push(_renderLaneCells(lanes[i], i, i + 1));
  }
  const axisLabels = ['60 s', '45 s', '30 s', '15 s', 'jetzt'];
  const lastIdx = axisLabels.length - 1;
  // M · the end ticks anchor to their own edge instead of guessing a pixel
  // nudge from a centred position — "jetzt" used to be pushed out past the
  // track by a hard-coded 24 px that no longer matched its rendered width.
  const axisHtml = axisLabels
    .map((txt, i) => {
      const pos =
        i === 0
          ? 'left:0'
          : i === lastIdx
            ? 'right:0'
            : `left:calc(${(i * 100) / lastIdx}% - 12px)`;
      return `<span class="mv-ld-axis-tick" style="${pos}">${esc(txt)}</span>`;
    })
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
      ${_filteredToggle(filteredCount)}
      <div class="mv-ld-swim-axis"><div class="mv-ld-swim-axis-track">${axisHtml}</div></div>
    </div>`;
}

// The fold control for the filtered lanes. Full-width row below the grid,
// 44 px tall so it is a real touch target, and it states the count so the
// operator knows what they are not looking at.
function _filteredToggle(count) {
  if (!count) return '';
  const word = count === 1 ? 'gefilterte Spur' : 'gefilterte Spuren';
  const verb = _showFiltered ? 'ausblenden' : 'einblenden';
  return (
    `<button type="button" class="mv-ld-swim-filtered" data-action="swim-filtered" ` +
    `aria-expanded="${_showFiltered ? 'true' : 'false'}" data-on="${_showFiltered ? '1' : '0'}">` +
    `<span class="mv-ld-swim-filtered-dot" aria-hidden="true"></span>` +
    `${count} ${esc(word)} ${esc(verb)}</button>`
  );
}

function _renderLaneCells(lane, idx, gridRow) {
  const labelCell = _renderLaneLabel(lane);
  // data-status carries the SAME vocabulary the legend explains
  // (confirmed / weak / ghost / masked); the CSS turns it into dash + alpha
  // so a filtered lane reads as filtered without borrowing the hue channel.
  // --lane-color publishes the track hue to CSS so a status style can
  // restyle the connector (dotted for "maskiert") without inventing a
  // second colour for it. `color` is always an internal palette constant.
  const st = ` data-status="${lane.status || 'confirmed'}"`;
  const cv = `--lane-color:${lane.color};`;
  return (
    `<div class="mv-ld-swim-cell mv-ld-swim-cell-label" data-lane-idx="${idx}"${st} style="${cv}grid-row:${gridRow};grid-column:1">${labelCell}</div>` +
    `<div class="mv-ld-swim-cell mv-ld-swim-cell-events" data-lane-idx="${idx}"${st} style="${cv}grid-row:${gridRow};grid-column:2"></div>`
  );
}

// J4 · the lane's object-class icon, flat-tinted in the lane's track colour
// (one per lane), so the colour reads as the track and the glyph as the class.
function _renderLaneLabel(lane) {
  const isMotion = lane.id === _MOTION_ID;
  const suffix = lane.filtered ? ' · gefiltert' : '';
  const title = isMotion
    ? `Bewegung (ohne Track)${suffix}`
    : `${OBJ_LABEL[lane.label] || lane.label} · Track #${lane.num}${suffix}`;
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
        // M · anchor by the chip's RIGHT edge, not its left. A chip is
        // wider than the nominal _CHIP_W once it carries an "×6" label, so
        // `left: calc(pct% - 24px)` pushed the newest chips past 100 % and
        // the cell's overflow:hidden sheared their labels off at the
        // viewport edge. Anchoring right means a chip at "now" ends exactly
        // at the lane's right edge and grows leftward instead.
        const right = `calc(${(100 - ch.rightPct).toFixed(2)}%)`;
        const title = ch.count > 1 ? `${ch.count} Detektionen` : '1 Detektion';
        return (
          `<span class="mv-ld-swim-bar" style="right:${right};background:${c}" title="${esc(title)}">` +
          (label ? `<span class="mv-ld-swim-chip-lbl">${esc(label)}</span>` : '') +
          '</span>'
        );
      })
      .join('');
}
