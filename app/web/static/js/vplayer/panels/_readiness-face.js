// ─── vplayer/panels/_readiness-face.js ─────────────────────────────────────
// One FACE per readiness state — the markup half of the note.
//
// Before this file the states shared two banner styles and differed only
// in their sentence, which is a label rather than a design: „nichts
// gefunden" never said what the bar had been, „keine Quelle" never said
// what was missing, and the in-flight state rendered as literally
// nothing, so a clip whose sidecar request had not come back looked
// exactly like a healthy one. Each builder below shows what its state
// actually knows:
//
//   building  which phase, and how long it has been in it. The stage
//             meter is the chain, not a spinner.
//   pending   a request in flight, said out loud.
//   empty     the gate that produced the verdict, drawn: the bar is the
//             clip's best score, the tick is the spawn threshold.
//   coarse    how many boxes, from where, and that they only stand while
//             the clip is paused.
//   missing   the reason, plus the rebuild — but ONLY when a rebuild
//             could succeed.
//   ready     nothing at all. A healthy clip carries no status line.
//
// PURE string building: no DOM reads, no fetches, no state. The one
// import with a side effect is mediathek/_processing.js, which assigns
// to `window` at module load — a panel may reach for it, a model may
// not, which is why the stage vocabulary is joined here and not in
// _model/readiness.js. It is the same vocabulary the library tile
// renders, so one clip cannot say two different things in two places.

import { esc } from '../../core/dom.js';
import { fmtElapsed, procStateOf } from '../../mediathek/_processing.js';
import {
  CLIP_BUILDING,
  CLIP_COARSE,
  CLIP_EMPTY,
  CLIP_MISSING,
  CLIP_PENDING,
} from '../_model/readiness.js';

/** Flat 20 px glyphs, one per state. currentColor, so the tone drives them. */
function _svg(body) {
  return (
    `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ` +
    `stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
    `${body}</svg>`
  );
}

/** Which visual tone a state gets. A gap and an answer must not match. */
const _TONE = {
  [CLIP_BUILDING]: 'is-building',
  [CLIP_PENDING]: 'is-pending',
  [CLIP_EMPTY]: 'is-empty',
  [CLIP_COARSE]: 'is-coarse',
  [CLIP_MISSING]: 'is-missing',
};

const _MARK = {
  // A magnifier over an empty field: the walk RAN and came back with
  // nothing. NOT the tick it used to be — a tick is the mark of a thing
  // confirmed, and this banner sits directly above a row naming a
  // subject the live pipeline did confirm. Two verdicts, and the tick
  // was on the wrong one.
  [CLIP_EMPTY]: _svg('<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4 20 20"/>'),
  // A frame holding a pause: geometry that exists, and stands still.
  [CLIP_COARSE]: _svg(
    '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M10 9.5v5M14 9.5v5"/>',
  ),
  // A struck-through frame: the source itself is not there.
  [CLIP_MISSING]: _svg(
    '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M5.5 20 18.5 4"/>',
  ),
};

/**
 * The stage chain as three segments, the current one lit.
 *
 * `step` is mediathek/_processing.js's own (0 = Aufnahme, 1 = Umwandlung,
 * 2 = fertig), so the player and the library card agree on how far along
 * a clip is. Deliberately NOT a percentage: ffmpeg can only report one by
 * rewriting the event JSON at ~1 Hz per clip, which _stages.py refuses
 * for a job that usually takes seconds. Elapsed-in-stage is free and true.
 */
function _steps(step, kind) {
  const cls = (i) =>
    kind !== 'busy' && i >= step ? 'is-halted' : i < step ? 'is-done' : i === step ? 'is-now' : '';
  const seg = (i) => `<i class="${cls(i)}"></i>`;
  return `<span class="vp-rn-steps" aria-hidden="true">${seg(0)}${seg(1)}${seg(2)}</span>`;
}

/**
 * The score gate, drawn. Fill = the best score this clip ever produced,
 * tick = the spawn threshold the indexer applied. A fill that stops short
 * of the tick IS the explanation; a fill that passes it says the score
 * was not what rejected the track, which is just as useful to know.
 */
function _gateBar(gate) {
  if (!gate || gate.threshold == null || gate.best == null) return '';
  const pct = (v) => Math.max(0, Math.min(100, Math.round(v * 100)));
  const best = pct(gate.best);
  const thr = pct(gate.threshold);
  return (
    `<span class="vp-rn-gate" role="img" ` +
    `aria-label="bester Wert ${best} Prozent, Schwelle ${thr} Prozent">` +
    `<i class="vp-rn-gate-fill${best >= thr ? ' is-over' : ''}" style="width:${best}%"></i>` +
    `<i class="vp-rn-gate-tick" style="left:${thr}%"></i>` +
    `</span>`
  );
}

/** The `{label, value}` chips a state carries, or nothing. */
function _facts(list) {
  if (!list || !list.length) return '';
  const li = list
    .map((f) => `<li><b>${esc(f.value)}</b><span>${esc(f.label)}</span></li>`)
    .join('');
  return `<ul class="vp-rn-facts">${li}</ul>`;
}

/**
 * Seconds-in-stage as the library already words it — `40 s`, `3 min`.
 *
 * Re-exported so the mount's one-second tick rewrites the clock in the
 * SAME words the first paint used, without reaching past this module for
 * the stage vocabulary a second time.
 */
export function elapsedLabel(seconds) {
  return fmtElapsed(seconds);
}

/**
 * The clip is still being produced: name the phase, count the seconds.
 *
 * `liveAge` is the ticking value the mount recomputes; without one the
 * server's own `stage_age_s` is printed unchanged.
 */
function _buildingFace(readiness, item, liveAge) {
  const st = procStateOf(item || {});
  const elapsed = elapsedLabel(liveAge == null ? st.age : liveAge);
  const clock = elapsed ? ` · <span class="vp-rn-clock">${esc(elapsed)}</span>` : '';
  const sub = st.error ? `<span class="vp-rn-sub">${esc(st.error)}</span>` : '';
  return (
    `<div class="vp-rn is-building is-${esc(st.kind)}">` +
    `${_steps(st.step, st.kind)}` +
    `<span class="vp-rn-body">` +
    `<span class="vp-rn-head">${esc(st.label)}${clock}</span>` +
    `<span class="vp-rn-text">${esc(readiness.note)}</span>${sub}` +
    `</span></div>`
  );
}

/**
 * The whole banner for one readiness verdict.
 *
 * @param {object|null} readiness  from _model/readiness.js
 * @param {object|null} item       the event, for the stage vocabulary
 * @param {string} action          the trailing button / status span
 * @param {number|null} liveAge    ticking seconds-in-stage, if any
 * @returns {string}  '' for a healthy clip — no banner is its face
 */
export function readinessFaceHTML(readiness, item, action = '', liveAge = null) {
  if (!readiness || !readiness.note) return '';
  if (readiness.state === CLIP_BUILDING) return _buildingFace(readiness, item, liveAge);
  const mark =
    readiness.state === CLIP_PENDING
      ? `<span class="vp-rn-shimmer" aria-hidden="true"></span>`
      : `<span class="vp-rn-mark">${_MARK[readiness.state] || ''}</span>`;
  // The backend's own sentence about a failure is prose, not a value —
  // it gets its own quiet line rather than a chip built for „50 %".
  const sub = readiness.sub ? `<span class="vp-rn-sub">${esc(readiness.sub)}</span>` : '';
  // A quiet verdict is the default; only one that contradicts its own
  // trigger frame is allowed to raise its voice.
  const tone = `${_TONE[readiness.state] || 'is-pending'}${
    readiness.contradicts ? ' is-contradiction' : ''
  }`;
  return (
    `<div class="vp-rn ${tone}">${mark}` +
    `<span class="vp-rn-body">` +
    `<span class="vp-rn-text">${esc(readiness.note)}</span>${sub}` +
    `${_gateBar(readiness.gate)}${_facts(readiness.facts)}` +
    `</span>${action}</div>`
  );
}
