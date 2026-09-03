// ─── dashboard/_tests/tile-chrome.test.js ───────────────────────────────
// The schedule arithmetic behind a camera tile's notification-channel
// cluster. It sat in dashboard.js — 1082 lines, importable only with the
// whole netz/ + chrome/live-view graph behind it — and so had never been
// covered. The split made it reachable; this is what it actually does.
//
// The midnight-wrapping window is the part worth pinning: a "from 22:00
// to 06:00" schedule is not a simple `from <= now < to` range, and the
// three callers (state dot, cluster label, the tile's own arming
// display) all read the same answer.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  _isInScheduleWindow,
  _channelState,
  _channelClusterLabel,
  _channelCluster,
} from '../_tile-chrome.js';

/** Freeze the clock at a wall time for the duration of `body`. */
function atClock(hh, mm, body) {
  const RealDate = Date;
  const frozen = new RealDate(2026, 0, 15, hh, mm, 0);
  globalThis.Date = class extends RealDate {
    constructor(...args) {
      return args.length ? new RealDate(...args) : frozen;
    }
  };
  try {
    body();
  } finally {
    globalThis.Date = RealDate;
  }
}

// ── _isInScheduleWindow ───────────────────────────────────────────────

test('a missing bound is never inside a window', () => {
  assert.equal(_isInScheduleWindow('', '06:00'), false);
  assert.equal(_isInScheduleWindow('22:00', ''), false);
});

test('a same-day window contains a time inside it', () => {
  atClock(10, 30, () => assert.equal(_isInScheduleWindow('08:00', '18:00'), true));
});

test('a same-day window excludes a time before and after it', () => {
  atClock(7, 59, () => assert.equal(_isInScheduleWindow('08:00', '18:00'), false));
  atClock(18, 1, () => assert.equal(_isInScheduleWindow('08:00', '18:00'), false));
});

test('the window is closed at its end — 18:00 is already outside 08:00–18:00', () => {
  atClock(18, 0, () => assert.equal(_isInScheduleWindow('08:00', '18:00'), false));
  atClock(8, 0, () => assert.equal(_isInScheduleWindow('08:00', '18:00'), true));
});

test('a window that wraps past midnight contains times on BOTH sides of it', () => {
  atClock(23, 30, () => assert.equal(_isInScheduleWindow('22:00', '06:00'), true));
  atClock(2, 0, () => assert.equal(_isInScheduleWindow('22:00', '06:00'), true));
});

test('a window that wraps past midnight excludes the daytime gap', () => {
  atClock(12, 0, () => assert.equal(_isInScheduleWindow('22:00', '06:00'), false));
  atClock(6, 0, () => assert.equal(_isInScheduleWindow('22:00', '06:00'), false));
});

// ── _channelState ─────────────────────────────────────────────────────

test('a disarmed camera is muted no matter what its schedule says', () => {
  atClock(12, 0, () => {
    assert.equal(
      _channelState({ armed: false, schedule: { enabled: true, from: '0:00', to: '23:59' } }),
      'muted',
    );
  });
});

test('an armed camera with no schedule is always on', () => {
  atClock(3, 0, () => assert.equal(_channelState({ armed: true }), 'on'));
});

test('an armed camera inside its window is on, outside it is idle', () => {
  const cam = { armed: true, schedule: { enabled: true, from: '08:00', to: '18:00' } };
  atClock(10, 0, () => assert.equal(_channelState(cam), 'on'));
  atClock(20, 0, () => assert.equal(_channelState(cam), 'idle'));
});

test('schedule_notify takes precedence over the legacy plain schedule', () => {
  const cam = {
    armed: true,
    schedule_notify: { enabled: true, from: '20:00', to: '23:00' },
    schedule: { enabled: true, from: '08:00', to: '18:00' },
  };
  atClock(21, 0, () => assert.equal(_channelState(cam), 'on'));
  atClock(10, 0, () => assert.equal(_channelState(cam), 'idle'));
});

// ── _channelClusterLabel ──────────────────────────────────────────────

test('a muted channel says the camera is not armed', () => {
  assert.equal(_channelClusterLabel({ armed: false }, 'muted'), 'Kamera nicht scharf');
});

test('no schedule reads as a plain "aktiv"', () => {
  assert.equal(_channelClusterLabel({ armed: true }, 'on'), 'aktiv');
});

test('an always-on sentinel window (from === to) also reads as plain "aktiv"', () => {
  const cam = { armed: true, schedule: { enabled: true, from: '00:00', to: '00:00' } };
  assert.equal(_channelClusterLabel(cam, 'on'), 'aktiv');
});

test('inside a window the label names when it ends, outside it names when it starts', () => {
  const cam = { armed: true, schedule: { enabled: true, from: '08:00', to: '18:00' } };
  assert.equal(_channelClusterLabel(cam, 'on'), 'aktiv bis 18:00');
  assert.equal(_channelClusterLabel(cam, 'idle'), 'aktiv ab 08:00');
});

// ── _channelCluster ───────────────────────────────────────────────────

test('the cluster stamps its state and names the right channel', () => {
  const cam = { armed: true };
  const tg = _channelCluster(cam, 'tg', 'on');
  assert.match(tg, /data-state="on"/);
  assert.match(tg, /Telegram-Kanal/);
  const mqtt = _channelCluster(cam, 'mqtt', 'idle');
  assert.match(mqtt, /data-state="idle"/);
  assert.match(mqtt, /MQTT-Kanal/);
});

test('the cluster escapes its label rather than injecting it raw', () => {
  const cam = { armed: true, schedule: { enabled: true, from: '<img src=x>', to: '18:00' } };
  assert.doesNotMatch(_channelCluster(cam, 'tg', 'on'), /<img/);
});
