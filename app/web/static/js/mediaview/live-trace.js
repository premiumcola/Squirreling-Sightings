// ─── mediaview/live-trace.js ──────────────────────────────────────────────
// Q2-3 · the Trace tab's per-tick decision-trace renderer.
//
// The trace data was always reaching the frontend (it shows up verbatim
// in the copied Debug snapshot), but it only ever flowed into the
// Fein-Analyse fold inside the Detections tab — the dedicated Trace tab
// panel (#mvLdPanel-trace) was created empty and never written to. This
// renderer fills that gap.
//
// The tick loop hands us the last ~20 server ticks (oldest→newest); we
// paint them NEWEST FIRST on a dark monospace surface, one block per
// tick separated by a faint divider, and tint each line by its
// [bracket] prefix so the eye can scan the pipeline
// capture → coral → det → matrix → armed → … → final.
//
// S3 · the tint carries one more distinction now, and it is the whole
// point of the panel: a gate the simulator RAN and a gate it refuses to
// run used to render identically, both falling through to the muted
// "info" tint — visually quieter than the [final] line they qualify.
// The five stated-but-unrun gates get their own amber "unchecked" tint,
// and diag.parity.not_simulated is rendered as a chip row above the
// stream so the declaration is visible without scrolling for it.

import { esc } from '../core/dom.js';

// Bracket-prefix → accent class (CSS in 30f-live-detect-skeleton.css).
// Each pipeline gate gets its own subtle colour; unknown prefixes fall
// back to the muted "info" tint.
const _PREFIX_CLASS = {
  capture: 'cap',
  coral: 'coral',
  det: 'det',
  verdict: 'verdict',
  matrix: 'matrix',
  armed: 'armed',
  telegram_enabled: 'tg',
  telegram: 'tg',
  schedule_notify: 'sched',
  schedule: 'sched',
  cooldown: 'cool',
  final: 'final',
  // Gates the panel actually EVALUATED. Grouped under one tint so
  // "this was measured" reads as a single category against the amber
  // "this was not looked at" below.
  filter: 'gate',
  mask: 'gate',
  zone: 'gate',
  tracker: 'gate',
  mute: 'gate',
  push_flag: 'gate',
  push_threshold: 'gate',
  suppress: 'gate',
  rate_limit: 'gate',
  // Gates production runs that the simulator deliberately does NOT —
  // they need consecutive frames at production cadence. Their lines say
  // so in German; the tint means the verdict below says nothing about
  // them. Mirrors diag.parity.not_simulated.
  motion: 'unchecked',
  confirmation: 'unchecked',
  wildlife: 'unchecked',
  event_cooldown: 'unchecked',
  recording: 'unchecked',
};

// diag.parity.not_simulated ids → the operator's words. Kept short: the
// chips wrap on a 430 px screen and a sentence per gate would bury the
// trace it is supposed to qualify.
const _GATE_DE = {
  motion_gate: 'Bewegung',
  confirmation_window: 'Bestätigung',
  wildlife_cascade: 'Wildtier-Kaskade',
  bird_species: 'Vogelarten',
  identity: 'Identität',
  event_cooldown: 'Ereignis-Cooldown',
  recording_schedule: 'Aufnahme-Zeitplan',
  frame_validator: 'Frame-Validator',
};

// "[coral] threshold floor …" → "coral". Leading-bracket scan only.
export function tracePrefix(line) {
  const m = /^\s*\[([a-z_]+)\]/i.exec(line || '');
  return m ? m[1].toLowerCase() : '';
}

// The parity declaration as a chip row. Empty string when the backend
// sent no parity block (older build) so nothing shifts on the page.
export function renderParityBanner(parity) {
  const gates = Array.isArray(parity?.not_simulated) ? parity.not_simulated : [];
  if (!gates.length) return '';
  const chips = gates
    .map((g) => `<span class="mv-ld-trace-parity-chip">${esc(_GATE_DE[g] || String(g))}</span>`)
    .join('');
  return (
    '<div class="mv-ld-trace-parity">' +
    '<div class="mv-ld-trace-parity-head">NICHT GEPRÜFT — das Urteil sagt dazu nichts</div>' +
    `<div class="mv-ld-trace-parity-chips">${chips}</div>` +
    '</div>'
  );
}

export function renderLiveTrace(host, ticks, parity) {
  if (!host) return;
  const banner = renderParityBanner(parity);
  if (!Array.isArray(ticks) || ticks.length === 0) {
    host.innerHTML = `${banner}<div class="mv-ld-trace-empty">Warte auf ersten Tick …</div>`;
    return;
  }
  // Newest tick first (the array arrives oldest→newest).
  const blocks = ticks
    .slice()
    .reverse()
    .map((tick) => {
      const head = _fmtTime(tick.ts);
      const lines = (tick.lines || [])
        .map((line) => {
          const text = typeof line === 'string' ? line : line.text || '';
          const prefix =
            line && typeof line === 'object' && line.prefix ? line.prefix : tracePrefix(text);
          const cls = _PREFIX_CLASS[prefix] || 'info';
          return `<div class="mv-ld-trace-line" data-prefix="${esc(cls)}">${esc(text)}</div>`;
        })
        .join('');
      return (
        '<div class="mv-ld-trace-tick">' +
        `<div class="mv-ld-trace-tick-head">${esc(head)}</div>${lines}` +
        '</div>'
      );
    })
    .join('');
  host.innerHTML = `${banner}<div class="mv-ld-trace">${blocks}</div>`;
}

function _fmtTime(ts) {
  if (!Number.isFinite(ts)) return '—';
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
