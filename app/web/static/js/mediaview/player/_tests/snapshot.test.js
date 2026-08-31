// ─── player/_tests/snapshot.test.js ────────────────────────────────────
// No real <canvas>/2D context under plain node:test (no jsdom in this
// repo) — captureFrameCanvas/downloadSnapshot take a `doc` parameter for
// exactly this, so a minimal stub implementing only what the module
// calls stands in for `document`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { captureFrameCanvas, downloadSnapshot, snapshotFilename } from '../_snapshot.js';

test('captureFrameCanvas draws the video frame at its native dimensions', () => {
  const canvas = { width: 0, height: 0, drawCalls: [], getContext: null };
  canvas.getContext = (kind) =>
    kind === '2d' ? { drawImage: (...args) => canvas.drawCalls.push(args) } : null;
  const doc = { createElement: () => canvas };
  const video = { videoWidth: 640, videoHeight: 360 };

  const result = captureFrameCanvas(video, doc);
  assert.equal(result, canvas);
  assert.equal(canvas.width, 640);
  assert.equal(canvas.height, 360);
  assert.equal(canvas.drawCalls.length, 1);
  assert.deepEqual(canvas.drawCalls[0], [video, 0, 0, 640, 360]);
});

test('captureFrameCanvas on an unloaded video (0x0) returns null, not a throw', () => {
  const doc = { createElement: () => ({ getContext: () => ({ drawImage() {} }) }) };
  assert.equal(captureFrameCanvas({ videoWidth: 0, videoHeight: 0 }, doc), null);
  assert.equal(captureFrameCanvas(null, doc), null);
  assert.equal(captureFrameCanvas({ videoWidth: NaN, videoHeight: NaN }, doc), null);
});

test('snapshotFilename encodes the elapsed seconds', () => {
  assert.equal(snapshotFilename({ currentTime: 12.7 }), 'snapshot_12s.png');
  assert.equal(snapshotFilename({ currentTime: undefined }), 'snapshot_0s.png');
});

test('downloadSnapshot produces a blob and drives an anchor-click download', () => {
  let blobSeen = null;
  let downloadName = null;
  let clicked = false;
  const anchor = {
    set href(_v) {},
    set download(v) {
      downloadName = v;
    },
    click() {
      clicked = true;
    },
    remove() {},
  };
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({ drawImage() {} }),
    toBlob(cb, type) {
      blobSeen = { type };
      cb({ _fakeBlob: true });
    },
  };
  const doc = {
    createElement: (tag) => (tag === 'canvas' ? canvas : anchor),
    body: { appendChild() {} },
  };
  const origCreate = globalThis.URL && globalThis.URL.createObjectURL;
  const origRevoke = globalThis.URL && globalThis.URL.revokeObjectURL;
  globalThis.URL = globalThis.URL || {};
  globalThis.URL.createObjectURL = () => 'blob:fake';
  globalThis.URL.revokeObjectURL = () => {};

  const attempted = downloadSnapshot({ videoWidth: 100, videoHeight: 80, currentTime: 3 }, doc);

  globalThis.URL.createObjectURL = origCreate;
  globalThis.URL.revokeObjectURL = origRevoke;

  assert.equal(attempted, true);
  assert.equal(blobSeen.type, 'image/png');
  assert.equal(downloadName, 'snapshot_3s.png');
  assert.equal(clicked, true);
});

test('downloadSnapshot on a video with no usable frame returns false, not a throw', () => {
  const doc = { createElement: () => ({ getContext: () => ({ drawImage() {} }) }) };
  assert.equal(downloadSnapshot({ videoWidth: 0, videoHeight: 0 }, doc), false);
});
