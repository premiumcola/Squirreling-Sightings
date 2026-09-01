// ─── core/_tests/scroll-anchor.test.js ──────────────────────────────────
// withScrollAnchor is the fix for the Wetterdaten-chart scroll-jump: a
// sibling re-rendering at a very different height must not silently move
// the anchor element (and whatever the operator was looking at) on
// screen. These are real before/after position measurements against a
// controllable fake element — not just "doesn't throw" — because that is
// exactly the mechanism the bug report hinges on.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withScrollAnchor } from '../scroll-anchor.js';

function fakeAnchor(initialTop) {
  return {
    _top: initialTop,
    getBoundingClientRect() {
      return { top: this._top };
    },
  };
}

function fakeScrollTarget() {
  const calls = [];
  return { calls, scrollBy: (x, y) => calls.push([x, y]) };
}

test('a sibling shrinking above the anchor scrolls up by the exact delta', async () => {
  const anchor = fakeAnchor(800);
  const target = fakeScrollTarget();
  await withScrollAnchor(
    anchor,
    () => {
      anchor._top = 200; // content above shrank — anchor now sits higher
    },
    target,
  );
  assert.deepEqual(target.calls, [[0, -600]]);
});

test('a sibling growing above the anchor scrolls down by the exact delta', async () => {
  const anchor = fakeAnchor(200);
  const target = fakeScrollTarget();
  await withScrollAnchor(
    anchor,
    () => {
      anchor._top = 900; // content above grew — anchor pushed lower
    },
    target,
  );
  assert.deepEqual(target.calls, [[0, 700]]);
});

test('no position change means no scroll correction at all', async () => {
  const anchor = fakeAnchor(500);
  const target = fakeScrollTarget();
  await withScrollAnchor(anchor, () => {}, target);
  assert.equal(target.calls.length, 0);
});

test('an async mutate is awaited before the second measurement', async () => {
  const anchor = fakeAnchor(1000);
  const target = fakeScrollTarget();
  await withScrollAnchor(
    anchor,
    async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      anchor._top = 100;
    },
    target,
  );
  assert.deepEqual(target.calls, [[0, -900]]);
});

test('a missing anchor element still runs the mutation without throwing', async () => {
  let ran = false;
  await withScrollAnchor(null, () => {
    ran = true;
  });
  assert.equal(ran, true);
});

test('an anchor without getBoundingClientRect is treated as missing', async () => {
  let ran = false;
  await withScrollAnchor({}, () => {
    ran = true;
  });
  assert.equal(ran, true);
});

test('defaults to window as the scroll target when none is passed', async () => {
  const calls = [];
  globalThis.window = { scrollBy: (x, y) => calls.push([x, y]) };
  try {
    const anchor = fakeAnchor(300);
    await withScrollAnchor(anchor, () => {
      anchor._top = 50;
    });
    assert.deepEqual(calls, [[0, -250]]);
  } finally {
    delete globalThis.window;
  }
});
