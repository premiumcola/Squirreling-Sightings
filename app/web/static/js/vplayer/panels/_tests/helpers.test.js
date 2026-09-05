// ─── vplayer/panels/_tests/helpers.test.js ─────────────────────────────────
// These panels read a backend that is still being written. The contract
// this file pins is therefore not "the rows are right" but "the rows
// SURVIVE": a complete payload maps to every named row, and a payload
// missing model versions, thresholds or provenance entirely still
// renders every row, throws nothing, and never prints "undefined".
//
// Fields that are known-missing on purpose are asserted as such, so
// that when the backend grows them this file fails and someone updates
// the mapping instead of quietly rendering a placeholder forever. Model
// identity on the live surface WAS one of them and has since landed —
// its tests below now pin the join rather than its absence, and the
// degradation cases stay exactly as strict as they were.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PLACEHOLDER } from '../../_helpers.js';
import { mapFrame } from '../../_data/_map.js';
import {
  MODEL_STAGE_DE,
  computeChip,
  kvRowsHtml,
  modelLabel,
  provenanceRows,
  tpuBusyLabel,
  tpuFor,
  trackRow,
} from '../_helpers.js';
import { provenanceView } from '../_provenance.js';

/** A complete event, as the backend writes one today. */
const FULL_EVENT = {
  provenance: {
    schema: 1,
    tuning_hash: 'a1b2c3d4e5f6',
    build: { commit: 'abc1234', date: '2026-08-30', count: 811 },
    camera: { id: 'cam-1', name: 'Garten', role: 'wildlife', alarm_profile: 'standard' },
    effective: { roi_mode: '2x2', min_score: 0.4, spawn_default: 0.5 },
    zones: { count: 2, ids: ['a', 'b'] },
    masks: { count: 0, ids: [] },
    models: {
      tpu_active: true,
      detector: { file: 'coco_ssd_mobilenet_v2_edgetpu.tflite', sha256: 'deadbeef0123' },
      bird_classifier: { file: 'inat_bird_quant_edgetpu.tflite', sha256: 'cafebabe4567' },
    },
    timing: { pre_roll_s: 3, post_roll_s: 5, analysis_interval_ms: 400 },
  },
};

test('a complete provenance payload maps to every named row', () => {
  const rows = provenanceRows(FULL_EVENT);
  const by = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  assert.equal(by['Profil'], 'standard');
  assert.equal(by['Rolle'], 'wildlife');
  assert.equal(by['Rechenwerk'], 'TPU');
  assert.ok(by['Detektor'].includes('coco_ssd'), by['Detektor']);
  assert.ok(by['Vogel-Modell'].includes('inat_bird'), by['Vogel-Modell']);
  assert.equal(by['ROI-Modus'], '2x2');
  assert.equal(by['Zonen'], '2');
  assert.equal(by['Masken'], 'keine', 'zero zones is a fact, not a missing value');
  assert.equal(by['Schwelle'], '40 %');
  assert.equal(by['Spawn-Schwelle'], '50 %');
  assert.equal(by['Vorlauf'], '3 s');
  assert.equal(by['Nachlauf'], '5 s');
  assert.equal(by['Analyse-Takt'], '400 ms');
  assert.equal(by['Build'], 'abc1234');
});

test('an event with NO provenance still renders every row', () => {
  // Every clip recorded before provenance landed has provenance: null,
  // and so does any recording whose snapshot threw.
  const rows = provenanceRows({ provenance: null });
  assert.equal(rows.length, provenanceRows(FULL_EVENT).length, 'no row may disappear');
  for (const r of rows) {
    assert.equal(typeof r.value, 'string');
    assert.ok(r.value.length > 0, `${r.key} rendered empty`);
    assert.ok(!r.value.includes('undefined'), `${r.key}: ${r.value}`);
    assert.ok(!r.value.includes('NaN'), `${r.key}: ${r.value}`);
  }
});

test('a pre-provenance clip falls back to recording_settings', () => {
  // The older, narrower sibling. Prefer provenance, but do not throw
  // away the two numbers the old block did carry.
  const rows = provenanceRows({
    provenance: null,
    recording_settings: { conf_thresh_general: 0.35, pre_motion_seconds: 2, post_motion_seconds: 6 },
  });
  const by = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  assert.equal(by['Schwelle'], '0.35');
  assert.equal(by['Vorlauf'], '2 s');
  assert.equal(by['Nachlauf'], '6 s');
});

test('a payload missing model versions and thresholds throws nothing', () => {
  const partial = { provenance: { camera: { alarm_profile: 'standard' }, models: {} } };
  assert.doesNotThrow(() => provenanceRows(partial));
  const by = Object.fromEntries(provenanceRows(partial).map((r) => [r.key, r.value]));
  assert.equal(by['Profil'], 'standard');
  assert.equal(by['Detektor'], PLACEHOLDER);
  assert.equal(by['Vogel-Modell'], PLACEHOLDER);
  assert.equal(by['Spawn-Schwelle'], PLACEHOLDER);
});

test('provenanceRows survives null, undefined and a bare object', () => {
  for (const item of [null, undefined, {}, { provenance: 'nonsense' }]) {
    assert.doesNotThrow(() => provenanceRows(item));
    assert.ok(provenanceRows(item).length > 0);
  }
});

test('an event names the profile REVISION it was recorded under', () => {
  // WAS KNOWN-MISSING: the alarm profile NAME was all the backend
  // stored, so two clips recorded either side of a threshold change
  // were indistinguishable in this fold. provenance.tuning_hash is the
  // fingerprint of the tuning snapshot and is that missing id.
  const by = Object.fromEntries(provenanceRows(FULL_EVENT).map((r) => [r.key, r.value]));
  assert.equal(by['Profil'], 'standard', 'the NAME is still its own row');
  assert.equal(by['Profil-Version'], 'a1b2c3d4e5f6');
});

test('a clip older than the revision fingerprint still renders the row', () => {
  // Every clip recorded before tuning_hash shipped has no fingerprint.
  // The row stays — a disappearing row is how a fold starts lying about
  // which facts exist — and degrades like every other.
  const by = Object.fromEntries(
    provenanceRows({ provenance: { camera: { alarm_profile: 'standard' } } }).map((r) => [
      r.key,
      r.value,
    ]),
  );
  assert.equal(by['Profil-Version'], PLACEHOLDER);
});

test('modelLabel names the cascade stage, and the file when it can', () => {
  const models = FULL_EVENT.provenance.models;
  assert.equal(modelLabel('detector', models), `${MODEL_STAGE_DE.detector} · ${models.detector.file}`);
  // No table to join against — a clip recorded before the table
  // existed. The stage is still a fact and is still named.
  assert.equal(modelLabel('bird_classifier'), MODEL_STAGE_DE.bird_classifier);
});

test('a live frame joins its stage against the payload models table', () => {
  // WAS KNOWN-MISSING: the live/simulation payload carried no stage on
  // its rows and no model table at all, so a live row could never say
  // which model produced a label. Both now ship — the table under the
  // frame's `models` key, in the same shape provenance.models uses, so
  // this is the SAME join the recorded surface does.
  const frame = mapFrame({
    detections: [{ label: 'bird', score: 0.8, model: 'bird_classifier' }],
    models: {
      detector: { file: 'coco_ssd_mobilenet_v2_edgetpu.tflite', sha256: 'deadbeef0123' },
      bird_classifier: { file: 'inat_bird_quant_edgetpu.tflite', sha256: 'cafebabe4567' },
    },
  });
  assert.equal(frame.detections[0].model, 'bird_classifier', 'the stage survives the mapping');
  assert.equal(
    modelLabel(frame.detections[0].model, frame.models),
    `${MODEL_STAGE_DE.bird_classifier} · inat_bird_quant_edgetpu.tflite`,
  );
  // And a track row of that same frame resolves through the same table.
  assert.equal(
    trackRow({ id: 1, model: 'detector' }, frame.models).model,
    `${MODEL_STAGE_DE.detector} · coco_ssd_mobilenet_v2_edgetpu.tflite`,
  );
});

test('a payload from before the models table still names every stage', () => {
  // The back-compat half: an old event JSON, or any frame whose payload
  // carries no table, must keep rendering. The stage alone, never a
  // blank and never an invented file name.
  const frame = mapFrame({ detections: [{ label: 'bird', score: 0.8, model: 'bird_classifier' }] });
  assert.equal(frame.models, null);
  assert.equal(modelLabel(frame.detections[0].model, frame.models), MODEL_STAGE_DE.bird_classifier);
  assert.equal(trackRow({ id: 1, model: 'detector' }, null).model, MODEL_STAGE_DE.detector);
});

test('modelLabel degrades rather than inventing a model name', () => {
  // A row with no stage at all — a legacy sidecar, or a detection built
  // outside the cascade — must not be given one.
  assert.equal(modelLabel(null), PLACEHOLDER);
  assert.equal(modelLabel(undefined), PLACEHOLDER);
  // An unknown stage token is shown raw rather than swallowed.
  assert.equal(modelLabel('future_stage'), 'future_stage');
  // A table that does not cover this stage falls back to the stage.
  assert.equal(modelLabel('detector', { bird_classifier: { file: 'x' } }), MODEL_STAGE_DE.detector);
  assert.equal(modelLabel('detector', { detector: {} }), MODEL_STAGE_DE.detector);
});

test('the TPU busy ratio renders as a percent of a 0..1 fraction', () => {
  assert.equal(tpuBusyLabel({ busy: 0.42 }), '42 %');
  assert.equal(tpuBusyLabel({ busy: 0 }), '0 %');
  assert.equal(tpuBusyLabel({ busy: 1 }), '100 %');
});

test('a camera with no TPU stage is not the same as an idle one', () => {
  // The backend reports null for "no stage on the TPU" and 0.0 for
  // "on the TPU and idle". Rendering both as "0 %" would hide a
  // camera that is silently running on the CPU.
  assert.equal(tpuBusyLabel(null), PLACEHOLDER);
  assert.equal(tpuBusyLabel({}), PLACEHOLDER);
  assert.equal(tpuBusyLabel({ busy: null }), PLACEHOLDER);
  assert.equal(tpuBusyLabel({ busy: 0 }), '0 %');
});

test('tpuFor prefers the camera own utilisation over the fleet total', () => {
  const status = {
    tpu: { total: { busy: 0.9 }, cameras: { 'cam-1': { busy: 0.1 } } },
  };
  assert.equal(tpuFor(status, 'cam-1').busy, 0.1);
  assert.equal(tpuFor(status, 'cam-unknown').busy, 0.9, 'falls back to the fleet');
  assert.equal(tpuFor({}, 'cam-1'), null);
  assert.equal(tpuFor(null, 'cam-1'), null);
});

test('the compute chip reads the inference device', () => {
  assert.equal(computeChip({ inference: { device: 'tpu' } }), 'TPU');
  assert.equal(computeChip({ inference: { device: 'cpu' } }), 'CPU');
  assert.equal(computeChip({ inference: { device: 'off' } }), 'Erkennung aus');
  assert.equal(computeChip({}), PLACEHOLDER);
  assert.equal(computeChip(null), PLACEHOLDER);
});

test('a track row formats every field it has', () => {
  const r = trackRow({
    id: 3,
    label: 'person',
    state: 'active',
    age_s: 4.23,
    idle_s: 0.4,
    misses: 2,
    last_iou: 0.81,
    score: 0.9,
    model: 'detector',
  });
  assert.equal(r.num, 3);
  assert.equal(r.age, '4,2 s');
  assert.equal(r.misses, '2');
  assert.equal(r.iou, '81 %');
  assert.equal(r.score, '90 %');
  assert.equal(r.model, MODEL_STAGE_DE.detector);
});

test('a null IoU is not zero overlap and must not read as 0 %', () => {
  // null means the newborn DISTANCE gate matched — rendering "0 %"
  // would say the boxes failed to overlap, which is the opposite.
  const r = trackRow({ id: 1, last_iou: null });
  assert.equal(r.iou, PLACEHOLDER);
  assert.equal(trackRow({ id: 1, last_iou: 0 }).iou, '0 %');
});

test('a bare track row degrades every field independently', () => {
  const r = trackRow({});
  for (const key of ['state', 'age', 'idle', 'misses', 'iou', 'score', 'model']) {
    assert.equal(typeof r[key], 'string', key);
    assert.ok(!r[key].includes('undefined'), `${key}: ${r[key]}`);
    assert.ok(!r[key].includes('NaN'), `${key}: ${r[key]}`);
  }
  assert.equal(r.num, null);
  assert.doesNotThrow(() => trackRow(null));
});

test('zero misses is a real value, not a missing one', () => {
  assert.equal(trackRow({ misses: 0 }).misses, '0');
});

// ── the shared row markup ──────────────────────────────────────────────
// Both row producers in _helpers.js render through kvRowsHtml, so the
// provenance list and the replay summary cannot drift into looking like
// two different kinds of thing inside one fold.

test('a row renders its key and value into the kv markup', () => {
  const html = kvRowsHtml([{ key: 'Profil', value: 'hard', tone: null }]);
  assert.match(html, /class="vp-pnl-kv"/);
  assert.match(html, /class="vp-pnl-k">Profil</);
  assert.match(html, /class="vp-pnl-v">hard</);
});

test('a tone becomes an is- class, and no tone adds no class', () => {
  assert.match(kvRowsHtml([{ key: 'k', value: 'v', tone: 'warn' }]), /vp-pnl-v is-warn/);
  assert.match(kvRowsHtml([{ key: 'k', value: 'v', tone: null }]), /class="vp-pnl-v">/);
});

test('both halves of a row are escaped', () => {
  // A label can reach these rows from an event JSON, so neither half is
  // trusted markup.
  const html = kvRowsHtml([{ key: '<b>k</b>', value: '<img onerror=x>', tone: null }]);
  assert.ok(!html.includes('<b>'), html);
  assert.ok(!html.includes('<img'), html);
});

test('several rows concatenate, and nothing renders as nothing', () => {
  const html = kvRowsHtml([
    { key: 'a', value: '1', tone: null },
    { key: 'b', value: '2', tone: null },
  ]);
  assert.equal(html.match(/vp-pnl-kv/g).length, 2);
  assert.equal(kvRowsHtml([]), '');
  assert.equal(kvRowsHtml(null), '');
});

// ── Aufnahme-Details: keine Spalte aus Strichen ────────────────────────

test('leere Zeilen werden weggelassen statt als Strich gedruckt', () => {
  // „Was bringen unten die ganzen Aufnahmedetails, wenn da überall nur
  // 'n Strich ist, null oder null Sekunden?" — auf einem Clip von vor
  // dem Schnappschuss waren zwölf von fünfzehn Zeilen genau das.
  const alt = {
    recording_settings: { conf_thresh_general: 0.0, pre_motion_seconds: 0, post_motion_seconds: 0 },
  };
  const view = provenanceView(alt);
  assert.ok(view.rows.length > 0, 'was bekannt ist, bleibt stehen');
  assert.ok(view.rows.length < provenanceRows(alt).length, 'der Rest faellt weg');
  for (const r of view.rows) assert.notEqual(r.value, PLACEHOLDER);
});

test('die Luecke wird EINMAL erklaert, statt vielfach angedeutet', () => {
  const alt = { recording_settings: { conf_thresh_general: 0.0 } };
  assert.match(provenanceView(alt).note, /Schnappschuss/);
});

test('ein vollstaendiger Schnappschuss bekommt keinen Hinweis', () => {
  const view = provenanceView(FULL_EVENT);
  assert.equal(view.note, '', 'nichts fehlt, also gibt es nichts zu erklaeren');
  assert.equal(view.rows.length, provenanceRows(FULL_EVENT).length);
});

test('bei einem neuen Clip mit Luecken zaehlt der Hinweis sie', () => {
  // Hier ist die Luecke feldweise und NICHT das Alter des Clips — die
  // Erklaerung „aeltere Aufnahme" waere dann schlicht falsch.
  const teil = { provenance: { ...FULL_EVENT.provenance, models: {}, timing: {} } };
  const view = provenanceView(teil);
  assert.match(view.note, /weitere Angaben/);
  assert.equal(/ltere Aufnahme/.test(view.note), false);
});
