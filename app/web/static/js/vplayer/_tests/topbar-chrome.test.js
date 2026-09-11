// ─── vplayer/_tests/topbar-chrome.test.js ──────────────────────────────────
// What the top strip actually renders, now that it is chrome ON the
// picture rather than a row above it („systemplayer oben weg").
//
// Three things here are structural rather than cosmetic, and each has a
// failure mode that looks like nothing at all in a screenshot:
//
//   · the ⋮ must not render when the menu behind it would be empty.
//     mountOverflowMenu refuses to mount an empty menu and returns null,
//     so the trigger would sit on the picture and answer no press —
//     the same shape as the green round-arrow button removed in this
//     pass.
//   · the speed button needs a host to mount into, and _speed.js mounts
//     by appendChild. A renamed or dropped slot means the control is
//     simply absent, with no error anywhere.
//   · the close has to be WIRED. It is the only pointer route out of
//     the player on a desktop with no back gesture.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { mountTopbar } from '../_topbar.js';

/** Just enough DOM for `innerHTML` plus class-based lookups. */
function host() {
  const wired = [];
  return {
    innerHTML: '',
    wired,
    querySelector(sel) {
      const cls = sel.replace('.', '');
      if (!this.innerHTML.includes(`class="${cls}"`) && !this.innerHTML.includes(`${cls}"`)) {
        return null;
      }
      // One stand-in per lookup is enough: the assertions below are
      // about whether an element exists and whether it took a listener.
      return {
        cls,
        addEventListener: (type, fn) => wired.push([cls, type, fn]),
        removeEventListener: () => {},
      };
    },
  };
}

const cfg = (over = {}) => ({
  mode: 'recorded',
  item: { time: '2026-09-07T10:36:24', duration_s: 27 },
  flags: { live: false },
  ...over,
});

test('the strip renders the title, the camera glyph and the close', () => {
  const h = host();
  mountTopbar(h, cfg(), { onClose: () => {} });
  assert.match(h.innerHTML, /vp-top-cam/);
  assert.match(h.innerHTML, /vp-top-title/);
  assert.match(h.innerHTML, /vp-top-close/);
  assert.match(h.innerHTML, /07\.09\.2026/, 'the title still says WHEN the clip is');
});

test('the ⋮ appears only when there is a menu behind it', () => {
  const without = host();
  mountTopbar(without, cfg(), { onClose: () => {}, hasMenu: false });
  assert.doesNotMatch(without.innerHTML, /vp-top-more/);

  const with_ = host();
  mountTopbar(with_, cfg(), { onClose: () => {}, hasMenu: true });
  assert.match(with_.innerHTML, /vp-top-more/);
});

test('the speed button always gets its slot, whatever the mode', () => {
  for (const live of [false, true]) {
    const h = host();
    const bar = mountTopbar(h, cfg({ flags: { live } }), { onClose: () => {} });
    assert.match(h.innerHTML, /vp-top-speed/, `live=${live}`);
    assert.ok(bar.speedHost, 'the handle must expose it — _speed.js appends into it');
  }
});

test('the close is wired to the handler it was given', () => {
  const h = host();
  let closed = 0;
  mountTopbar(h, cfg(), { onClose: () => (closed += 1) });
  const hit = h.wired.find(([cls, type]) => cls === 'vp-top-close' && type === 'click');
  assert.ok(hit, 'the ✕ took no click listener');
  hit[2]();
  assert.equal(closed, 1);
});

test('the actions are pushed right by a spacer, never by an auto margin', () => {
  // CLAUDE.md names `margin-left: auto` against an inline-flex box as the
  // recurring root cause of this project's iOS chrome-layout bugs. The
  // spacer element is how that is avoided, so its presence is the pin.
  const h = host();
  mountTopbar(h, cfg(), { onClose: () => {} });
  assert.match(h.innerHTML, /vp-top-gap/);
  assert.ok(
    h.innerHTML.indexOf('vp-top-gap') < h.innerHTML.indexOf('vp-top-actions'),
    'the spacer has to come BEFORE the group it pushes',
  );
});

test('a missing host is survivable rather than a throw', () => {
  assert.equal(mountTopbar(null, cfg(), {}), null);
});
