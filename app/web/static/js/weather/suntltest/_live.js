// ─── weather/suntltest/_live.js ────────────────────────────────────────────
// The in-flight view: per-slot heatmap, counter chips, current-action
// row with ETA, the status pills, and the log tail.

import { byId, esc } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { S } from './_state.js';

// Reolink day/night override result. `true` the CGI call went through,
// `false` it was attempted and failed, null/undefined it was never
// attempted (override disabled, or the camera has no rtsp_url to infer
// a host from — see _apply_daynight_override).
//
// The label is a parameter because the same three states describe both
// halves of the flip: the lead-in that forces Color before the window,
// and the revert that restores Auto/Black&White after it.
export function dnBadge(v, label = 'Tag/Nacht') {
  const cls = v === true ? 'ok' : v === false ? 'err' : 'mute';
  const word = v === true ? 'gesetzt' : v === false ? 'fehlgeschlagen' : 'übersprungen';
  return `<span class="suntltest-badge suntltest-badge--${cls}">${esc(label)}: ${word}</span>`;
}

// Profile pill — DAY (sun yellow) / TWILIGHT (horizon orange) / NIGHT
// (deep blue). Soft tinted background, rounded ≥ 8 px, no thin border
// per project rules.
export function profileBadge(profile, brightness) {
  if (!profile) return '';
  const labels = { day: 'DAY', twilight: 'TWILIGHT', night: 'NIGHT' };
  const cls = `suntltest-pill suntltest-pill--${profile}`;
  const lbl = labels[profile] || profile.toUpperCase();
  const sub =
    typeof brightness === 'number'
      ? ` <span class="suntltest-pill-sub">brightness ${brightness}</span>`
      : '';
  return `<span class="${cls}">${esc(lbl)}${sub}</span>`;
}

// Drift pill — only renders when the backend flagged a drift > limit.
// Amber tint. Reads e.g. "Sunset-Capture lief 312 min nach Sonnen-
// untergang — Frames sind reine Nacht".
export function driftBadge(warning) {
  if (!warning) return '';
  return `<span class="suntltest-pill suntltest-pill--drift">⚠ ${esc(warning)}</span>`;
}

// G3 · density-style per-slot heatmap. One cell per expected slot,
// coloured by the resolved outcome from the slot_events ring buffer
// the backend ships (G2). Cell width is governed by CSS flex; on a
// 75-min × 8-s window (562 cells) iPhone width collapses cells to
// ~2 px each (purely density visual). Desktop wider cells get a
// title-tooltip with the per-slot detail. Cap at 800 cells —
// extreme runs beyond that bound aren't realistic for sun-tl.
function _renderHeatmap(d) {
  const expected = Math.max(0, Math.min(800, parseInt(d.expected_frames, 10) || 0));
  if (expected === 0) return '';
  const cells = [];
  for (let i = 0; i < expected; i++) {
    const ev = S.eventBySlot.get(i);
    if (!ev) {
      cells.push(`<div class="suntltest-cell" data-outcome="empty" data-slot="${i}"></div>`);
      continue;
    }
    const reason = ev.reason ? ` · ${ev.reason}` : '';
    const age = typeof ev.age_ms === 'number' ? ` · ${ev.age_ms} ms` : '';
    const title = `Slot ${ev.slot} · ${ev.outcome}${reason}${age}`;
    cells.push(
      `<div class="suntltest-cell" data-outcome="${esc(ev.outcome)}" data-slot="${ev.slot}" title="${esc(title)}"></div>`,
    );
  }
  return `<div class="suntltest-heatmap" aria-label="Slot-Heatmap (${expected} Slots)">${cells.join('')}</div>`;
}

// Average frame-age across the events we've seen that carry one.
function _avgFrameAge() {
  let sum = 0,
    count = 0;
  for (const ev of S.eventBySlot.values()) {
    if (typeof ev.age_ms === 'number') {
      sum += ev.age_ms;
      count++;
    }
  }
  return count > 0 ? `${Math.round(sum / count)} ms` : '—';
}

// G3 · counter chips coloured to match the heatmap legend. Each chip
// renders even when its count is 0 so the user can see the full set
// at a glance; counts are tabular-num so the row doesn't shift as
// values increment.
function _renderCounterRow(d) {
  const expected = parseInt(d.expected_frames, 10) || 0;
  const fresh = parseInt(d.fresh_captures, 10) || 0;
  const back = parseInt(d.backfilled_slots, 10) || 0;
  const skip = parseInt(d.skipped_slots, 10) || 0;
  const rej = Math.max(0, (parseInt(d.invalid_frames, 10) || 0) - back - skip);
  const cached = parseInt(d.api_cached_grabs_total, 10) || 0;
  const currentSlot = Math.min(expected, S.eventBySlot.size);
  const profileStr = d.validator_profile ? d.validator_profile : '—';
  return `
    <div class="suntltest-counter-row">
      <span class="suntltest-counter-progress">Slot <b>${currentSlot}</b> / ${expected}</span>
      <span class="suntltest-counter-chip" data-outcome="fresh">fresh ${fresh}</span>
      <span class="suntltest-counter-chip" data-outcome="cached">cached ${cached}</span>
      <span class="suntltest-counter-chip" data-outcome="rejected">rejected ${rej}</span>
      <span class="suntltest-counter-chip" data-outcome="backfilled">backfilled ${back}</span>
      <span class="suntltest-counter-chip" data-outcome="skipped">skipped ${skip}</span>
    </div>
    <div class="suntltest-counter-meta">
      <span>Frame-Alter ⌀ <b>${_avgFrameAge()}</b></span>
      <span>Validator: <b>${esc(profileStr)}</b></span>
    </div>`;
}

// G3 · current-action row + ETA. During capture: "Slot N wird
// erfasst — ETA HH:MM (M min S s verbleiben)". Between capture-end
// and finished=true: "Encoding … (ffmpeg)". Hidden after finished
// (the result diff panel takes over).
function _renderActionRow(d) {
  if (d.finished) return '';
  const elapsed = Math.max(0, parseInt(d.elapsed_s, 10) || 0);
  const target = Math.max(1, parseInt(d.target_s, 10) || 1);
  const expected = parseInt(d.expected_frames, 10) || 0;
  if (elapsed >= target) {
    return `
      <div class="suntltest-action">
        <span class="suntltest-action-ico">▶</span>
        <span class="suntltest-action-text">Aktuell: <b>Encoding …</b> (ffmpeg)</span>
      </div>`;
  }
  const remaining = Math.max(0, target - elapsed);
  const remMin = Math.floor(remaining / 60);
  const remSec = remaining % 60;
  const remStr = remMin > 0 ? `${remMin} min ${remSec} s` : `${remSec} s`;
  const etaTs = new Date(Date.now() + remaining * 1000);
  const etaStr = etaTs.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const currentSlot = Math.min(expected, S.eventBySlot.size + 1);
  return `
    <div class="suntltest-action">
      <span class="suntltest-action-ico">▶</span>
      <span class="suntltest-action-text">Aktuell: Slot <b>${currentSlot}</b> wird erfasst …</span>
      <span class="suntltest-action-eta">ETA <b>${esc(etaStr)}</b> · noch ${esc(remStr)}</span>
    </div>`;
}

function _rawDirBlock(rawDir) {
  if (!rawDir) return '';
  return `
    <div class="suntltest-section suntltest-rawdir">
      <span class="suntltest-rawdir-label">Roh-Frames:</span>
      <code class="suntltest-rawdir-path">${esc(rawDir)}</code>
      <button type="button" class="suntltest-rawdir-copy" data-suntltest-copy="${esc(rawDir)}" title="Pfad kopieren" aria-label="Pfad kopieren">⧉ kopieren</button>
    </div>`;
}

// Wire the copy button. Falls back to a transient text-selection when
// navigator.clipboard is unavailable (older Safari, http contexts) so
// the path is still selectable manually.
function _bindCopyButton(wrap) {
  const copyBtn = wrap.querySelector('[data-suntltest-copy]');
  if (!copyBtn) return;
  copyBtn.addEventListener('click', async () => {
    const path = copyBtn.getAttribute('data-suntltest-copy') || '';
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(path);
      } else {
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(wrap.querySelector('.suntltest-rawdir-path'));
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
      copyBtn.textContent = '✓ kopiert';
      setTimeout(() => {
        copyBtn.textContent = '⧉ kopieren';
      }, 1500);
    } catch (_e) {
      /* noop — selection fallback already ran */
    }
  });
}

export function pillRow(d) {
  // The daynight result is the first signal this panel's own header
  // comment promises, and the backend has filled daynight_color_set on
  // every session since the feature landed — but dnBadge was never
  // called, so a Color flip that failed outright looked exactly like
  // one that worked. The revert badge only appears once a revert was
  // actually attempted (it is null for the whole capture).
  const pills =
    profileBadge(d.validator_profile, d.baseline_brightness) +
    driftBadge(d.phase_drift_warning) +
    dnBadge(d.daynight_color_set, 'Tag/Nacht → Color') +
    (d.daynight_revert_set == null ? '' : dnBadge(d.daynight_revert_set, 'Tag/Nacht zurück'));
  return pills ? `<div class="suntltest-pill-row">${pills}</div>` : '';
}

export function renderLive(d) {
  const wrap = byId('suntltestLive');
  if (!wrap) return;
  if (!d || !d.cam_id) {
    wrap.hidden = true;
    wrap.innerHTML = '';
    return;
  }
  wrap.hidden = false;
  // G3 · live view built around a per-slot heatmap. The old card-in-
  // card tile grid + per-reason reject list moved out (the post-run
  // diff panel surfaces the same data in a tighter form).
  // Row 1 heatmap, row 2 counter chips, row 3 action/ETA, row 4 log
  // tail — flat layout, no nested boxes.
  const phaseLabel = d.phase === 'sunrise' ? '🌄 Sonnenaufgang' : '🌇 Sonnenuntergang';
  const camName = (state.cameras || []).find((c) => c.id === d.cam_id)?.name || d.cam_id;
  const stateClass = d.finished ? 'is-done' : d.running ? 'is-running' : 'is-idle';
  const logBlock = (d.last_log_lines || [])
    .slice(-60)
    .map((line) => `<div class="suntltest-log-line">${esc(line)}</div>`)
    .join('');
  wrap.className = `suntltest-live ${stateClass}`;
  wrap.innerHTML = `
    <div class="suntltest-live-head">
      <div class="suntltest-live-title">${esc(camName)} · ${phaseLabel}</div>
      <div class="suntltest-live-status">${d.finished ? '✅ fertig' : d.running ? '⏺ läuft' : '⏸ pausiert'}</div>
    </div>
    ${pillRow(d)}
    ${_renderHeatmap(d)}
    ${_renderCounterRow(d)}
    ${_renderActionRow(d)}
    <div class="suntltest-section">
      <div class="suntltest-section-title">Log-Tail</div>
      <div class="suntltest-log-box" id="suntltestLog">${logBlock || '<div class="suntltest-log-line muted">— kein Log —</div>'}</div>
    </div>
    ${_rawDirBlock(d.raw_dir)}
  `;
  // Auto-stick the log to the bottom while it grows.
  const logBox = byId('suntltestLog');
  if (logBox) logBox.scrollTop = logBox.scrollHeight;
  _bindCopyButton(wrap);
}
