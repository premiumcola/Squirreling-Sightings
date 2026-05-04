// ─── core/gestures.js ──────────────────────────────────────────────────────
// Pointer-events-based gesture helpers. PointerEvents unify mouse, touch
// and stylus input — one codepath for every device, no parallel
// touchstart/mousedown branches. Each helper returns a teardown function
// so callers can detach when their host element goes away.
//
//   import { onSwipe, onPinch, onLongPress, onPullToRefresh }
//     from './core/gestures.js';
//
// Helpers do not call evt.preventDefault on pointermove unless the
// gesture genuinely conflicts with native scrolling — keeping the
// browser's scroll responsiveness intact unless the consumer opts in.

const _now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());


// ── onSwipe ─────────────────────────────────────────────────────────────
// Threshold = primary-axis travel; restraint = max perpendicular travel
// (separates a swipe from a diagonal scroll). allowedTime caps the
// gesture duration so a slow drag is treated as something else.
export function onSwipe(element, callbacks = {}, opts = {}) {
  if (!element) return () => {};
  const threshold = opts.threshold ?? 50;
  const restraint = opts.restraint ?? 100;
  const allowedTime = opts.allowedTime ?? 400;

  let _startX = 0, _startY = 0, _startT = 0, _active = false;

  const onDown = (evt) => {
    if (evt.pointerType === 'mouse' && evt.button !== 0) return;
    _startX = evt.clientX;
    _startY = evt.clientY;
    _startT = _now();
    _active = true;
  };
  const onUp = (evt) => {
    if (!_active) return;
    _active = false;
    const dx = evt.clientX - _startX;
    const dy = evt.clientY - _startY;
    const dt = _now() - _startT;
    if (dt > allowedTime) return;
    if (Math.abs(dx) >= threshold && Math.abs(dy) <= restraint) {
      (dx < 0 ? callbacks.onLeft : callbacks.onRight)?.(evt);
    } else if (Math.abs(dy) >= threshold && Math.abs(dx) <= restraint) {
      (dy < 0 ? callbacks.onUp : callbacks.onDown)?.(evt);
    }
  };
  const onCancel = () => { _active = false; };

  element.addEventListener('pointerdown', onDown);
  element.addEventListener('pointerup', onUp);
  element.addEventListener('pointercancel', onCancel);
  return () => {
    element.removeEventListener('pointerdown', onDown);
    element.removeEventListener('pointerup', onUp);
    element.removeEventListener('pointercancel', onCancel);
  };
}


// ── onPinch ─────────────────────────────────────────────────────────────
// Tracks two simultaneous pointers and fires `cb({scale, center, phase})`
// where phase is 'start' / 'move' / 'end'. Scale is the ratio of the
// current finger-distance to the initial finger-distance.
export function onPinch(element, cb) {
  if (!element || !cb) return () => {};
  const pointers = new Map();
  let _startDist = 0;

  const _dist = () => {
    const pts = [...pointers.values()];
    const dx = pts[0].x - pts[1].x;
    const dy = pts[0].y - pts[1].y;
    return Math.sqrt(dx * dx + dy * dy) || 1;
  };
  const _center = () => {
    const pts = [...pointers.values()];
    const r = element.getBoundingClientRect();
    return {
      x: ((pts[0].x + pts[1].x) / 2) - r.left,
      y: ((pts[0].y + pts[1].y) / 2) - r.top,
    };
  };

  const onDown = (evt) => {
    pointers.set(evt.pointerId, { x: evt.clientX, y: evt.clientY });
    if (pointers.size === 2) {
      _startDist = _dist();
      cb({ scale: 1, center: _center(), phase: 'start' });
    }
  };
  const onMove = (evt) => {
    if (!pointers.has(evt.pointerId)) return;
    pointers.set(evt.pointerId, { x: evt.clientX, y: evt.clientY });
    if (pointers.size === 2) {
      cb({ scale: _dist() / _startDist, center: _center(), phase: 'move' });
    }
  };
  const onUp = (evt) => {
    if (pointers.size === 2) cb({ scale: _dist() / _startDist, center: _center(), phase: 'end' });
    pointers.delete(evt.pointerId);
  };

  element.addEventListener('pointerdown', onDown);
  element.addEventListener('pointermove', onMove);
  element.addEventListener('pointerup', onUp);
  element.addEventListener('pointercancel', onUp);
  return () => {
    element.removeEventListener('pointerdown', onDown);
    element.removeEventListener('pointermove', onMove);
    element.removeEventListener('pointerup', onUp);
    element.removeEventListener('pointercancel', onUp);
  };
}


// ── onLongPress ─────────────────────────────────────────────────────────
// Fires `cb(evt)` when the pointer stays still on `element` for `ms`
// milliseconds. Movement of more than `tolerance` px cancels.
export function onLongPress(element, cb, ms = 500, tolerance = 8) {
  if (!element || !cb) return () => {};
  let _timer = null, _startX = 0, _startY = 0;

  const _clear = () => { if (_timer) { clearTimeout(_timer); _timer = null; } };
  const onDown = (evt) => {
    if (evt.pointerType === 'mouse' && evt.button !== 0) return;
    _startX = evt.clientX;
    _startY = evt.clientY;
    _clear();
    _timer = setTimeout(() => { _timer = null; cb(evt); }, ms);
  };
  const onMove = (evt) => {
    if (!_timer) return;
    if (Math.abs(evt.clientX - _startX) > tolerance
        || Math.abs(evt.clientY - _startY) > tolerance) _clear();
  };

  element.addEventListener('pointerdown', onDown);
  element.addEventListener('pointermove', onMove);
  element.addEventListener('pointerup', _clear);
  element.addEventListener('pointercancel', _clear);
  element.addEventListener('pointerleave', _clear);
  return () => {
    _clear();
    element.removeEventListener('pointerdown', onDown);
    element.removeEventListener('pointermove', onMove);
    element.removeEventListener('pointerup', _clear);
    element.removeEventListener('pointercancel', _clear);
    element.removeEventListener('pointerleave', _clear);
  };
}


// ── onPullToRefresh ─────────────────────────────────────────────────────
// Drag-down at the top of `scrollEl` (scrollTop === 0) past `threshold`
// fires `cb()`. While pulling, `indicatorEl` (optional) gets its
// `--pull-progress` CSS var set 0..1 so a CSS-driven indicator can move.
export function onPullToRefresh(scrollEl, cb, opts = {}) {
  if (!scrollEl || !cb) return () => {};
  const threshold = opts.threshold ?? 80;
  const indicatorEl = opts.indicatorEl || null;

  let _startY = 0, _pulling = false, _firing = false;

  const _setProgress = (progress) => {
    if (indicatorEl) {
      indicatorEl.style.setProperty('--pull-progress', String(progress));
      indicatorEl.classList.toggle('is-pulling', progress > 0);
      indicatorEl.classList.toggle('is-armed', progress >= 1);
    }
  };

  const onDown = (evt) => {
    if (_firing || scrollEl.scrollTop > 0) return;
    _startY = evt.clientY;
    _pulling = true;
  };
  const onMove = (evt) => {
    if (!_pulling) return;
    const dy = evt.clientY - _startY;
    if (dy <= 0) { _setProgress(0); return; }
    _setProgress(Math.min(1, dy / threshold));
  };
  const onUp = async (evt) => {
    if (!_pulling) return;
    _pulling = false;
    const dy = evt.clientY - _startY;
    if (dy >= threshold) {
      _firing = true;
      _setProgress(1);
      try { await cb(); } finally { _firing = false; _setProgress(0); }
    } else {
      _setProgress(0);
    }
  };

  scrollEl.addEventListener('pointerdown', onDown);
  scrollEl.addEventListener('pointermove', onMove);
  scrollEl.addEventListener('pointerup', onUp);
  scrollEl.addEventListener('pointercancel', onUp);
  return () => {
    scrollEl.removeEventListener('pointerdown', onDown);
    scrollEl.removeEventListener('pointermove', onMove);
    scrollEl.removeEventListener('pointerup', onUp);
    scrollEl.removeEventListener('pointercancel', onUp);
  };
}
