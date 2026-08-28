// ─── netz/_helpers.js ──────────────────────────────────────────────────────
// German formatters, provenance labels and the evidence encoding.
// Labels, colours and icons come from core/icons.js + core/class-colors.js
// — never re-declared here.

import { esc } from '../core/dom.js';
import { OBJ_LABEL, objIconSvg } from '../core/icons.js';
import { classColor } from '../core/class-colors.js';

export const NEUTRAL = '#8888aa';

export function labelDe(key) {
  return OBJ_LABEL[key] || key;
}

export function axisIcon(key, size = 16) {
  return objIconSvg(key, size);
}

export function axisColor(key) {
  return classColor(key, NEUTRAL);
}

export function pct(v) {
  return Number.isFinite(Number(v)) ? `${Math.round(Number(v) * 100)} %` : '—';
}

export function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

// ── provenance ────────────────────────────────────────────────────────
// A7.3 · which force last moved this axis, readable at a glance. The
// three fill states in A6 already carry EVIDENCE, so provenance takes
// the vertex OUTLINE colour instead — one channel, one meaning.

export const PROVENANCE_DE = {
  werk: 'Werk',
  manuell: 'manuell',
  automatisch: 'automatisch',
};

export function provenanceStroke(axis) {
  if (axis.provenance === 'manuell') return axisColor(axis.label);
  if (axis.provenance === 'automatisch') return `${axisColor(axis.label)}8c`;
  return NEUTRAL;
}

// ── evidence ──────────────────────────────────────────────────────────
// Three channels, no more — a fourth turns the chart to mush.
//
//   vertex RADIUS   8 / 11 / 14 px   0 judged / 1–49 / >= 50
//   vertex FILL     hollow / solid / solid + white ring
//   spoke OPACITY   .40 / 1.0        no data / data
//
// A class with no evidence must look unmistakably different from a
// tuned one: hollow 8 px dot on a 40 %-opacity spoke. Nobody mistakes
// that for a value somebody chose.

export function vertexRadius(axis) {
  const n = axis.evidence?.judged || 0;
  if (n === 0) return 8;
  return n >= (axis.evidence?.needed || 50) ? 14 : 11;
}

export function vertexFill(axis) {
  const n = axis.evidence?.judged || 0;
  if (n === 0) return 'none';
  return axisColor(axis.label);
}

export function isReady(axis) {
  return !!axis.evidence?.ready;
}

export function spokeOpacity(axis) {
  return (axis.evidence?.judged || 0) > 0 ? 1 : 0.4;
}

// ── archive ───────────────────────────────────────────────────────────

export const VERDICT_DE = {
  richtig: 'Richtig',
  falsch: 'Falsch',
  anders: 'Etwas anderes',
};

export function verdictWord(row) {
  if (!row.verdict) return 'noch nicht beurteilt';
  if (row.verdict === 'anders' && row.corrected_label) {
    return `Etwas anderes · ${labelDe(row.corrected_label)}`;
  }
  return VERDICT_DE[row.verdict] || row.verdict;
}

export function classChip(label) {
  if (!label) return '';
  const c = axisColor(label);
  return (
    `<span class="netz-chip" style="--cc:${esc(c)}">` +
    `<span class="netz-chip-ic">${axisIcon(label, 13)}</span>${esc(labelDe(label))}</span>`
  );
}

/** The one-line direction legend. Getting this backwards is the classic
 *  radar failure — so it is on screen, permanently, not in a tooltip. */
export const DIRECTION_LEGEND = [
  'innen · streng, meldet nur Sicheres',
  'außen · empfindlich, meldet mehr',
];
