// ─── vplayer/_tests/config.test.js ─────────────────────────────────────────
// The per-mode flag table is the spine of the package: nothing branches
// on `mode`, everything branches on these flags. The case that earns
// this file is the live/sim pair — they must differ ONLY by what is
// hidden, because the moment they differ structurally someone will
// write the second controller this package exists to avoid.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildPlayerConfig, VPLAYER_MODES, LIVE_WINDOW_MS } from '../_config.js';

test('every advertised mode builds', () => {
  for (const mode of VPLAYER_MODES) {
    const cfg = buildPlayerConfig({ mode });
    assert.equal(cfg.mode, mode);
  }
});

test('live and sim differ only by the hidden panel and overlays', () => {
  const sim = buildPlayerConfig({ mode: 'sim' }).flags;
  const live = buildPlayerConfig({ mode: 'live' }).flags;

  assert.equal(sim.showPanel, true);
  assert.equal(live.showPanel, false);
  assert.equal(sim.showOverlays, true);
  assert.equal(live.showOverlays, false);
  assert.deepEqual(live.overlayToggles, []);

  // Everything else is identical — same transport, same window, same
  // panel family, same absence of recorded-item semantics.
  const rest = (f) => ({ ...f, showPanel: 0, showOverlays: 0, overlayToggles: 0 });
  assert.deepEqual(rest(live), rest(sim));
});

test('recorded scrubs a known duration; live and sim roll a window', () => {
  assert.equal(buildPlayerConfig({ mode: 'recorded' }).flags.timeline, 'scrub');
  assert.equal(buildPlayerConfig({ mode: 'sim' }).flags.timeline, 'rolling');
  assert.equal(buildPlayerConfig({ mode: 'live' }).flags.timeline, 'rolling');

  assert.equal(buildPlayerConfig({ mode: 'recorded' }).windowMs, 0);
  assert.equal(buildPlayerConfig({ mode: 'sim' }).windowMs, LIVE_WINDOW_MS);
  assert.equal(buildPlayerConfig({ mode: 'live' }).windowMs, LIVE_WINDOW_MS);
});

test('only recorded carries item semantics', () => {
  const rec = buildPlayerConfig({ mode: 'recorded' }).flags;
  assert.equal(rec.canDelete, true);
  assert.equal(rec.canConfirm, true);
  assert.equal(rec.canNavigate, true);
  assert.equal(rec.canRecordNow, false);
  for (const mode of ['live', 'sim']) {
    const f = buildPlayerConfig({ mode }).flags;
    assert.equal(f.canDelete, false);
    assert.equal(f.canConfirm, false);
    assert.equal(f.canNavigate, false);
    assert.equal(f.canRecordNow, true);
  }
});

test('a missing or unknown mode throws instead of rendering nothing', () => {
  assert.throws(() => buildPlayerConfig(), /config object required/);
  assert.throws(() => buildPlayerConfig(null), /config object required/);
  assert.throws(() => buildPlayerConfig({}), /unknown mode/);
  assert.throws(() => buildPlayerConfig({ mode: 'live-detect' }), /unknown mode 'live-detect'/);
});

test('overlays default per mode and are always all four booleans', () => {
  const sim = buildPlayerConfig({ mode: 'sim' }).overlays;
  assert.deepEqual(sim, { bboxes: true, trails: true, zones: true, masks: true });

  // Live hides them, so every layer defaults off — and off is `false`,
  // never `undefined`, which is how a layer sneaks back on.
  const live = buildPlayerConfig({ mode: 'live' }).overlays;
  assert.deepEqual(live, { bboxes: false, trails: false, zones: false, masks: false });
  for (const v of Object.values(live)) assert.equal(typeof v, 'boolean');
});

test('an explicit overlay choice from the caller wins over the default', () => {
  const cfg = buildPlayerConfig({ mode: 'sim', overlays: { trails: false, masks: false } });
  assert.deepEqual(cfg.overlays, { bboxes: true, trails: false, zones: true, masks: false });
});

test('unknown overlay keys are dropped rather than carried', () => {
  const cfg = buildPlayerConfig({ mode: 'sim', overlays: { heatmap: true } });
  assert.equal('heatmap' in cfg.overlays, false);
});

test('camId/cameraName and an item both normalise to one item', () => {
  const flat = buildPlayerConfig({ mode: 'sim', camId: 'cam-1', cameraName: 'Garten' });
  assert.equal(flat.item.camera_id, 'cam-1');
  assert.equal(flat.item.camera_name, 'Garten');

  const rich = buildPlayerConfig({ mode: 'recorded', item: { id: 'ev-9', camera_id: 'cam-2' } });
  assert.equal(rich.item.id, 'ev-9');
  assert.equal(rich.item.camera_id, 'cam-2');
});

test('the item is copied, not aliased to the caller object', () => {
  const item = { id: 'ev-9' };
  const cfg = buildPlayerConfig({ mode: 'recorded', item });
  cfg.item.id = 'mutated';
  assert.equal(item.id, 'ev-9');
});

test('an item camera_id is not overwritten by a stray camId', () => {
  const cfg = buildPlayerConfig({ mode: 'recorded', item: { camera_id: 'from-item' }, camId: 'x' });
  assert.equal(cfg.item.camera_id, 'from-item');
});

test('non-function actions become explicit nulls', () => {
  const onClose = () => {};
  const cfg = buildPlayerConfig({
    mode: 'recorded',
    actions: { onClose, onPrev: null, onNext: 'nope', onDelete: undefined },
  });
  assert.equal(cfg.actions.onClose, onClose);
  assert.equal(cfg.actions.onPrev, null);
  assert.equal(cfg.actions.onNext, null);
  assert.equal(cfg.actions.onDelete, null);
  assert.equal(cfg.actions.onConfirm, null);
  assert.equal(cfg.actions.onDownload, null);
});

test('the flag table cannot be mutated through a built config', () => {
  const a = buildPlayerConfig({ mode: 'sim' });
  a.flags.showPanel = false;
  a.flags.overlayToggles.push('heatmap');
  const b = buildPlayerConfig({ mode: 'sim' });
  assert.equal(b.flags.showPanel, true);
  assert.deepEqual(b.flags.overlayToggles, ['bboxes', 'trails', 'zones', 'masks']);
});

test('source is copied when given and null when absent', () => {
  assert.equal(buildPlayerConfig({ mode: 'sim' }).source, null);
  const src = { type: 'mjpeg', url: '/x.mjpg' };
  const cfg = buildPlayerConfig({ mode: 'sim', source: src });
  assert.deepEqual(cfg.source, src);
  assert.notEqual(cfg.source, src);
});
