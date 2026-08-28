// ─── mediaview/telemetry/_projection.js ────────────────────────────────────
// Block D · the mode comparison, the one-sentence answer, and the fold
// that says how much the answer can be trusted.
//
// The inverted number ("an inference may cost up to X ms for this mode to
// fit") is the headline rather than the duty percentage, because it is the
// form the operator can check against a measurement they already have on
// screen. "27.9 % Auslastung" still needs interpreting; "3×3 trägt bis
// 32 ms, gemessen 24,8 ms" does not.
import { esc } from '../../core/dom.js';
import { mvModeLabel, mvModeInvokes } from '../mode-indicator.js';

const _MODES = ['off', 'roi', '2x2', '3x3'];

const _VERDICT_LABEL = { ok: 'läuft', tight: 'eng', over: 'zu teuer' };

// Every one of these can move the answer, so each is spelled out rather
// than buried. They are also the reason the table says "Schätzung" on
// every row but the measured one.
const _CAVEATS = {
  rescue_rate_upper_bound:
    'Die Rettungsrate ist eine obere Schranke: ein Modus, der mehr findet, ' +
    'löst danach seltener aus. Die Schätzung irrt also zur sicheren Seite.',
  roi_tiles_variable:
    'ROI hat kein festes Kachel-Budget — je nach Bewegungsbox 1 bis 4 Teile. ' +
    'Deshalb steht dort eine Spanne und kein Punktwert.',
  model_dependent:
    'Alles hängt am geladenen Modell: zwischen 4,1 ms und 40,4 ms je Inferenz ' +
    'liegt Faktor 10. Nach einem Modellwechsel neu messen.',
  fps_feedback:
    'Der Kamera-Loop schläft NACH der Arbeit. Mehr Kosten heißen darum nicht ' +
    '120 % Last, sondern: die Analyse-Rate fällt. Über 100 % ist ein Hinweis, ' +
    'keine Messgröße.',
};

/**
 * The projection row for one mode. Works before the first fetch too —
 * the inference count is known without any hardware.
 */
export function modeRow(data, mode) {
  const rows = data?.projection?.modes || [];
  const hit = rows.find((r) => r.mode === mode);
  if (hit) return hit;
  return { mode, invokes: [mvModeInvokes(mode), mvModeInvokes(mode)], duty: null, stall_ms: null };
}

export function renderProjectionBlock(data) {
  const p = data.projection || {};
  const measured = p.measured_mode || 'off';
  const rows = _MODES.map((m) => _row(p, m, m === measured)).join('');
  return (
    '<div class="mv-tele-block">' +
    '<div class="mv-ld-subsection-head">Modus-Vergleich</div>' +
    `<div class="mv-tele-modes">${rows}</div>` +
    _headline(p) +
    _caveats(p) +
    '</div>'
  );
}

function _row(p, mode, isMeasured) {
  const row = (p.modes || []).find((r) => r.mode === mode) || {};
  const inv = row.invokes || [mvModeInvokes(mode), mvModeInvokes(mode)];
  const invTxt = inv[0] === inv[1] ? `${inv[1]}` : `${inv[0]}–${inv[1]}`;
  const duty = row.duty;
  const dutyTxt =
    p.basis === 'tpu' && duty
      ? duty[0] === duty[1]
        ? `${Math.round(duty[1] * 100)} %`
        : `${Math.round(duty[0] * 100)}–${Math.round(duty[1] * 100)} %`
      : '—';
  const stall = row.stall_ms || [0, 0];
  const stallTxt =
    stall[1] > 0
      ? stall[0] === stall[1]
        ? `+${stall[1]} ms`
        : `+${stall[0]}–${stall[1]} ms`
      : '—';
  const verdict = row.verdict || null;
  return (
    `<div class="mv-tele-mode-row" data-verdict="${esc(verdict || 'none')}">` +
    `<span class="mv-tele-mode-name">${esc(mvModeLabel(mode))}` +
    `<span class="mv-tele-mode-sub">${esc(invTxt)} Inferenzen/Bild · ${esc(stallTxt)} je Rettung</span></span>` +
    `<span class="mv-tele-mode-duty">${esc(dutyTxt)}</span>` +
    `<span class="mv-tele-mode-tag">${isMeasured ? 'aktuell · gemessen' : 'Schätzung'}` +
    (verdict ? `<span class="mv-tele-verdict" data-v="${esc(verdict)}">${esc(_VERDICT_LABEL[verdict] || verdict)}</span>` : '') +
    '</span></div>'
  );
}

function _headline(p) {
  const afford = p.affordable_invoke_ms || {};
  const limit = afford['3x3'];
  const measured = Number(p.invoke_ms) || 0;
  if (!limit || !measured) {
    return '<div class="mv-tele-note">Machbarkeitsgrenze: noch keine Messwerte.</div>';
  }
  const verdict = measured <= limit ? 'ok' : 'over';
  return (
    `<div class="mv-tele-headline" data-tone="${verdict}">` +
    `3×3 ist tragbar, solange eine Inferenz unter ${esc(String(limit))} ms bleibt. ` +
    `Gemessen: ${esc(measured.toFixed(1))} ms.</div>`
  );
}

function _caveats(p) {
  const keys = (p.caveats || []).filter((k) => _CAVEATS[k]);
  if (!keys.length) return '';
  const items = keys.map((k) => `<li>${esc(_CAVEATS[k])}</li>`).join('');
  return (
    '<details class="mv-tele-fold"><summary>Wie sicher ist das?</summary>' +
    `<ul class="mv-tele-fold-list">${items}</ul></details>`
  );
}
