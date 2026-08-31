// ─── player/_tests/loop.test.js ────────────────────────────────────────
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { toggleLoop } from '../_loop.js';

function _stubVideo(loop = false) {
  const events = [];
  return {
    loop,
    dispatchEvent(ev) {
      events.push(ev.type);
    },
    _events: events,
  };
}

test('toggleLoop flips video.loop off -> on and returns the new value', () => {
  const video = _stubVideo(false);
  const result = toggleLoop(video);
  assert.equal(result, true);
  assert.equal(video.loop, true);
});

test('toggleLoop flips video.loop on -> off', () => {
  const video = _stubVideo(true);
  const result = toggleLoop(video);
  assert.equal(result, false);
  assert.equal(video.loop, false);
});

test('toggleLoop dispatches mv:loopchange so any other mounted button can resync', () => {
  const video = _stubVideo(false);
  toggleLoop(video);
  assert.deepEqual(video._events, ['mv:loopchange']);
});

test('toggleLoop on a null video is a no-op, not a throw', () => {
  assert.equal(toggleLoop(null), false);
});

test('toggleLoop on a video without dispatchEvent still flips loop without throwing', () => {
  const video = { loop: false };
  assert.equal(toggleLoop(video), true);
  assert.equal(video.loop, true);
});
