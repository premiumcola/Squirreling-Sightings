// ─── mediaview/telemetry/_device.js ────────────────────────────────────────
// Block A · which device and which model per stage.
//
// Device and interface are two separate columns, never one badge:
// mode="coral" with the tflite delegate means "runs on the TPU, reached
// without pycoral", and collapsing that into a single chip is how a
// working delegate gets reported as a CPU fallback.
//
// A classifier on the CPU is neutral grey, not amber. It is the shipped
// design: the TPU caches model parameters in ~8 MB of on-chip SRAM and
// the live path switches models inside a single frame (detect → classify
// → refine), so every switch would rewrite that cache over USB. The
// detector runs on every frame and belongs on the stick; the classifiers
// run only on gated frames and a 32-thread 5950X swallows them. Amber is
// reserved for an UNWANTED fallback (reason starts with cpu_fallback).
import { esc } from '../../core/dom.js';

const _STAGE_LABEL = {
  detector: 'Objekt-Detektor',
  bird: 'Vogel-Klassifikator',
  wildlife: 'Wildtier-Klassifikator',
  wildlife_inat: 'Wildtier · iNat-Zweitmeinung',
};

const _DEVICE_LABEL = { tpu: 'TPU', cpu: 'CPU', off: 'aus' };

export function renderDeviceBlock(data) {
  const dev = data.device || {};
  const rt = dev.runtime || {};
  const rows = _dedupe(data.stages || []).map(_card).join('');
  return (
    '<div class="mv-tele-block">' +
    '<div class="mv-ld-subsection-head">Gerät &amp; Modelle</div>' +
    '<div class="mv-tele-note">' +
    `USB: ${esc(dev.usb || 'unbekannt')} · Python ${esc(rt.python || '?')} · ` +
    `tflite-runtime ${esc(rt.tflite_runtime || '—')} · pycoral ${esc(rt.pycoral || '—')}` +
    '</div>' +
    (rows || '<div class="mv-ld-empty-row">Keine aktive Erkennungsstufe</div>') +
    '</div>'
  );
}

// One card per STAGE, not per camera·stage: every camera loads the same
// model on the same device, so four rows answer the question and twelve
// only repeat it. The camera count rides along as a suffix.
function _dedupe(stages) {
  const byKey = new Map();
  for (const s of stages) {
    const key = `${s.stage}|${s.device}|${s.model || ''}`;
    const hit = byKey.get(key);
    if (hit) {
      hit._cams += 1;
      continue;
    }
    byKey.set(key, { ...s, _cams: 1 });
  }
  return Array.from(byKey.values());
}

function _card(s) {
  const tone = s.fallback ? 'warn' : s.device === 'off' ? 'mute' : 'ok';
  const deviceTxt = _DEVICE_LABEL[s.device] || s.device;
  const badge = s.deliberate ? `${deviceTxt} (bewusst)` : deviceTxt;
  const t = s.timing_ms || {};
  const timing = t.invoke
    ? `${Number(t.invoke).toFixed(1)} ms Berechnung · ${Number(t.total || 0).toFixed(1)} ms gesamt`
    : 'noch keine Messwerte';
  const reason = s.deliberate
    ? 'Klassifikatoren laufen absichtlich auf der CPU — die TPU behält so das Detektor-Modell im Cache.'
    : s.reason && s.reason !== 'ok'
      ? s.reason
      : '';
  return (
    `<div class="mv-tele-stage" data-tone="${esc(tone)}">` +
    '<div class="mv-tele-stage-top">' +
    `<span class="mv-tele-stage-name">${esc(_STAGE_LABEL[s.stage] || s.stage)}` +
    (s._cams > 1 ? `<span class="mv-tele-stage-cams"> · ${s._cams} Kameras</span>` : '') +
    '</span>' +
    `<span class="mv-tele-badge" data-tone="${esc(tone)}">${esc(badge)}</span>` +
    (s.api ? `<span class="mv-tele-badge" data-tone="mute">${esc(s.api)}</span>` : '') +
    '</div>' +
    `<div class="mv-tele-stage-model" title="${esc(s.model || '')}">${esc(s.model || '—')}</div>` +
    `<div class="mv-tele-note">${esc(timing)}</div>` +
    (reason ? `<div class="mv-tele-note mv-tele-reason">${esc(reason)}</div>` : '') +
    '</div>'
  );
}
