import { test } from 'node:test';
import assert from 'node:assert/strict';

import { mapFrame } from '../../_data/_map.js';
import { rawSummary } from '../_raw-detections.js';

// ── „1 übernommen" und trotzdem kein Kasten ───────────────────────────
//
// Der Betreiber sah „1 übernommen · 5 verworfen" und keine Box auf der
// Person und schloss daraus, sie werde nicht erkannt. Sie wurde erkannt:
// unter der Spawn-Schwelle. Ein solcher Treffer erzeugt KEINE Spur, und
// ein Kasten auf diesem Bild kommt aus einer Spur — also zählte die
// Anzeige etwas als übernommen, das nichts wurde.
//
// Die Unstimmigkeit stand schon in _map.js: DISCARD_REASON_DE führt
// `tentative` seit jeher („Unter der Spawn-Schwelle · hält nur die
// Spur"), die Menge daneben nicht.

test('ein tentativer Treffer zählt nicht als übernommen', () => {
  const frame = mapFrame({
    detections: [
      { label: 'person', score: 0.42, verdict: 'tentative', bbox: [0, 0, 10, 10] },
      { label: 'person', score: 0.71, verdict: 'pass', bbox: [0, 0, 10, 10] },
    ],
  });
  assert.equal(frame.kept.length, 1, 'nur der Treffer, der wirklich eine Spur wurde');
  assert.equal(frame.tentative.length, 1);
  assert.equal(frame.discarded.length, 0, 'verworfen ist er auch nicht — er hält die Spur');
});

test('die Zusammenfassung benennt den mittleren Zustand', () => {
  const frame = mapFrame({
    detections: [
      { label: 'person', score: 0.42, verdict: 'tentative' },
      { label: 'book', score: 0.21, verdict: 'filtered' },
    ],
  });
  const s = rawSummary(frame);
  assert.match(s, /0 übernommen/);
  assert.match(s, /1 unter der Spawn-Schwelle/);
  assert.match(s, /1 verworfen/);
});

test('ohne tentative Treffer liest sie sich wie immer', () => {
  const frame = mapFrame({
    detections: [{ label: 'person', score: 0.9, verdict: 'pass' }],
  });
  assert.equal(rawSummary(frame), '1 übernommen · 0 verworfen');
});
