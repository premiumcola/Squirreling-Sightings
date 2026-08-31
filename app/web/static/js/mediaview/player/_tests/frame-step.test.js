// ─── player/_tests/frame-step.test.js ────────────────────────────────────
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FRAME_STEP_SECONDS, applyFrameStep, stepFrameTime } from '../_frame-step.js';

test('stepFrameTime moves forward by exactly one fixed frame step', () => {
  assert.equal(stepFrameTime(1, 30, 1), 1 + FRAME_STEP_SECONDS);
});

test('stepFrameTime moves backward by one fixed frame step', () => {
  assert.equal(stepFrameTime(1, 30, -1), 1 - FRAME_STEP_SECONDS);
});

test('stepFrameTime clamps at 0 stepping back from the start', () => {
  assert.equal(stepFrameTime(0.02, 30, -1), 0);
});

test('stepFrameTime clamps at duration stepping forward from the end', () => {
  assert.equal(stepFrameTime(29.98, 30, 1), 30);
});

test('stepFrameTime with duration <= 0 (metadata not loaded) still clamps at 0', () => {
  assert.equal(stepFrameTime(0, 0, -1), 0);
  // No upper clamp possible without a known duration — just moves forward.
  assert.equal(stepFrameTime(0, 0, 1), FRAME_STEP_SECONDS);
});

test('applyFrameStep writes video.currentTime and returns the new value', () => {
  const video = { currentTime: 5, duration: 30 };
  const t = applyFrameStep(video, 1);
  assert.equal(t, 5 + FRAME_STEP_SECONDS);
  assert.equal(video.currentTime, 5 + FRAME_STEP_SECONDS);
});

test('applyFrameStep on a null video is a no-op, not a throw', () => {
  assert.equal(applyFrameStep(null, 1), null);
});
