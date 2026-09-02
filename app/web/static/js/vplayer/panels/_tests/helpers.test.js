// ─── vplayer/panels/_tests/helpers.test.js ─────────────────────────────────
// These panels read a backend that is still being written. The contract
// this file pins is therefore not "the rows are right" but "the rows
// SURVIVE": a complete payload maps to every named row, and a payload
// missing model versions, thresholds or provenance entirely still
// renders every row, throws nothing, and never prints "undefined".
//
// Two fields are known-missing on purpose and are asserted as such, so
// that when the backend grows them this file fails and someone updates
// the mapping instead of quietly rendering a placeholder forever.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PLACEHOLDER } from '../../_helpers.js';
import {
  MODEL_STAGE_DE,
  computeChip,
  modelLabel,
  provenanceRows,
  tpuBusyLabel,
  tpuFor,
  trackRow,
} from '../_helpers.js';

/** A complete event, as the backend writes one today. */
const FULL_EVENT = {
  provenance: {
    schema: 1,
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

test('KNOWN MISSING: nothing records the profile REVISION an event used', () => {
  // The alarm profile NAME is all the backend stores; there is no
  // profile_version / factory-vs-history marker anywhere. When one
  // lands, this assertion should fail and the row should grow.
  const keys = provenanceRows(FULL_EVENT).map((r) => r.key);
  assert.equal(keys.includes('Profil-Version'), false);
});

test('modelLabel names the cascade stage, and the file when it can', () => {
  const models = FULL_EVENT.provenance.models;
  assert.equal(modelLabel('detector', models), `${MODEL_STAGE_DE.detector} · ${models.detector.file}`);
  // No provenance to join against — the live rows' case.
  assert.equal(modelLabel('bird_classifier'), MODEL_STAGE_DE.bird_classifier);
});

test('modelLabel degrades rather than inventing a model name', () => {
  // KNOWN MISSING: the live endpoint's normal detection rows carry no
  // stage at all, so they cannot say which model produced the label.
  assert.equal(modelLabel(null), PLACEHOLDER);
  assert.equal(modelLabel(undefined), PLACEHOLDER);
  // An unknown stage token is shown raw rather than swallowed.
  assert.equal(modelLabel('future_stage'), 'future_stage');
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
