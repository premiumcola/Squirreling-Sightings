// ─── vplayer/timeline/_preview.js ──────────────────────────────────────────
// The thumbnail that follows the finger while you drag the playhead.
//
// „gut wäre noch ein thumb vorschau wenn ich den play button halte und
// hin und her ziehe" — and later, after a first attempt: „hin und her
// schieben soll auch flüssig gehen! bitte thumb größer im verhältnis!"
//
// WHY A SPRITE SHEET AND NOT THE VIDEO. Seeking a second <video> per
// drag position decodes an inter-coded stream from the nearest keyframe
// every time; on a phone that is a slideshow with a fan. The sheet is a
// single <img> the browser has already decoded, and moving the window
// over it is a background-position change — which is why this works on
// iOS at all, where video decoding during a drag is hopeless.
//
// The sheet is built at record time (app/app/scrub_sprite.py) and its
// geometry rides on the event as `scrub`. No sheet, no preview: the drag
// itself is unaffected, which is the point of keeping this a separate
// module that the scrubber merely calls.
//
// SMOOTHNESS IS A FRAME-BUDGET PROBLEM, not a CSS one. A pointermove
// fires far more often than the screen refreshes, so every handler that
// writes style on each event does the work several times per painted
// frame and the drag stutters under its own weight. Positions are
// therefore stored and applied ONCE per animation frame, on the same
// clock the playhead already runs on.

/** How long a finger has to rest before the bubble is meant.
 *
 * A tap on the grip is a play/pause press, and it went through `show()`
 * on its way — so the thumbnail flashed up and vanished inside the same
 * gesture: "wenn ich nur kurz drauf drücke, darf das Thumbnail noch
 * nicht angezeigt werden. Es gibt 'n komischen Flackereffekt."
 *
 * Long enough that a press never triggers it, short enough that a
 * deliberate hold does not feel like waiting.
 */
const HOLD_MS = 260;

/** …or this much movement, whichever comes first. Someone who starts
 *  dragging immediately has already said what they want, and making them
 *  wait out the timer would be its own kind of lag. Above the 4 px slop
 *  _scrub.js uses to tell a tap from a drag. */
const REVEAL_DRAG_PX = 8;

/** Must match the opacity transition in 36b-vplayer-timeline.css — the
 *  element is only hidden once the fade has actually finished. */
const FADE_MS = 140;

/** Geometry we cannot draw without. */
function _usable(geo) {
  return !!(
    geo &&
    geo.url &&
    geo.cols > 0 &&
    geo.rows > 0 &&
    geo.count > 0 &&
    geo.tile_w > 0 &&
    geo.tile_h > 0
  );
}

/**
 * PURE: which tile of the sheet covers this moment.
 *
 * Clamped at both ends: a drag to the very end lands one tile past the
 * last one by arithmetic, and a sheet whose stride was widened for a
 * long clip (see `_plan` in scrub_sprite.py) covers slightly more than
 * the clip's own duration.
 *
 * @param {number} t        seconds into the clip
 * @param {object} geo      { count, interval_s }
 * @param {number} duration clip length, used when interval_s is absent
 * @returns {number} 0-based tile index
 */
export function tileIndexAt(t, geo, duration) {
  if (!geo || !(geo.count > 0)) return 0;
  const time = Number.isFinite(t) && t > 0 ? t : 0;
  // interval_s is what the builder recorded; falling back to
  // duration/count keeps a sheet written before that field usable.
  const step = geo.interval_s > 0 ? geo.interval_s : duration > 0 ? duration / geo.count : 0;
  if (!(step > 0)) return 0;
  return Math.min(geo.count - 1, Math.max(0, Math.floor(time / step)));
}

/**
 * PURE: the CSS that shows tile `idx` of the sheet at width `w`.
 *
 * The sheet is scaled as a whole and then offset, so one tile fills the
 * window exactly. Returned as values rather than applied here so the
 * arithmetic is testable without a DOM.
 *
 * @returns {{width, height, backgroundSize, backgroundPosition}}
 */
export function tileStyle(idx, geo, w) {
  const scale = w / geo.tile_w;
  const col = idx % geo.cols;
  const row = Math.floor(idx / geo.cols);
  return {
    width: `${Math.round(w)}px`,
    height: `${Math.round(geo.tile_h * scale)}px`,
    backgroundSize: `${Math.round(geo.cols * geo.tile_w * scale)}px ${Math.round(
      geo.rows * geo.tile_h * scale,
    )}px`,
    backgroundPosition: `-${Math.round(col * w)}px -${Math.round(row * geo.tile_h * scale)}px`,
  };
}

/**
 * PURE: where the bubble sits so it never leaves the rail's box.
 *
 * @param {number} x      pointer position, relative to the rail's left
 * @param {number} railW  rail width
 * @param {number} bubbleW
 * @returns {number} left offset for the bubble
 */
export function clampLeft(x, railW, bubbleW) {
  return Math.min(Math.max(0, railW - bubbleW), Math.max(0, x - bubbleW / 2));
}

/** Bubble width: „thumb größer im verhältnis" — but never wider than
 *  the rail it belongs to, which on a 375 px phone it otherwise is. */
export function bubbleWidth(railW) {
  return Math.max(120, Math.min(200, railW - 16));
}

/**
 * Mount the drag preview onto a rail.
 *
 * @param {HTMLElement} rail  the element the drag is measured against
 * @param {object} opts
 * @param {() => object|null} opts.getGeometry  the clip's `scrub` block
 * @param {() => number} opts.getDuration
 * @param {() => boolean} [opts.isTouch]  lift the bubble clear of the finger
 * @returns {{show, moveTo, hide, teardown}|null}
 */
export function mountScrubPreview(rail, opts = {}) {
  if (!rail) return null;

  const el = document.createElement('div');
  el.className = 'vp-scrub-preview';
  el.hidden = true;
  const img = document.createElement('div');
  img.className = 'vp-scrub-preview-img';
  const cap = document.createElement('span');
  cap.className = 'vp-scrub-preview-time';
  el.appendChild(img);
  el.appendChild(cap);
  rail.appendChild(el);

  // One pending position, applied on the next frame. See the header:
  // writing style per pointermove is what makes a drag feel heavy.
  let pending = null;
  let raf = 0;
  let shown = false;
  // `armed` = a gesture is running and positions are being tracked.
  // `shown` = the bubble is actually visible. The gap between them is
  // the hold, and it is what stops a press from flashing it.
  let armed = false;
  let holdTimer = 0;
  let startX = 0;

  const flush = () => {
    raf = 0;
    if (!pending || !shown) return;
    const { x, t } = pending;
    pending = null;
    const geo = opts.getGeometry?.();
    if (!_usable(geo)) return;

    const railW = rail.getBoundingClientRect().width;
    const w = bubbleWidth(railW);
    const st = tileStyle(tileIndexAt(t, geo, opts.getDuration?.() || 0), geo, w);
    img.style.width = st.width;
    img.style.height = st.height;
    img.style.backgroundSize = st.backgroundSize;
    img.style.backgroundPosition = st.backgroundPosition;
    el.style.width = st.width;
    el.style.left = `${Math.round(clampLeft(x, railW, w))}px`;
    cap.textContent = _clock(t);
  };

  const schedule = () => {
    if (!raf) raf = requestAnimationFrame(flush);
  };

  const reveal = () => {
    if (!armed || shown) return;
    shown = true;
    el.hidden = false;
    // Next frame, so the browser has the element laid out at opacity 0
    // before the class flips it — otherwise the transition is skipped
    // and it snaps in, which is the flicker by another route.
    requestAnimationFrame(() => {
      if (shown) el.classList.add('is-on');
    });
    schedule();
  };

  const disarm = () => {
    if (holdTimer) clearTimeout(holdTimer);
    holdTimer = 0;
    armed = false;
  };

  return {
    /** Arm the bubble — it appears only after a hold or a real drag.
     *  No sheet → nothing happens and the drag is normal. */
    show: (x, t) => {
      const geo = opts.getGeometry?.();
      if (!_usable(geo)) return;
      img.style.backgroundImage = `url("${geo.url}")`;
      // On a touch screen the finger covers the rail, so the bubble
      // rides higher than it does under a mouse pointer.
      el.classList.toggle('vp-scrub-preview--touch', opts.isTouch?.() === true);
      armed = true;
      startX = x;
      pending = { x, t };
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = setTimeout(reveal, HOLD_MS);
    },
    moveTo: (x, t) => {
      if (!armed) return;
      pending = { x, t };
      // A real drag says what a hold would have said, sooner.
      if (!shown && Math.abs(x - startX) > REVEAL_DRAG_PX) reveal();
      else if (shown) schedule();
    },
    hide: () => {
      disarm();
      pending = null;
      if (!shown) return;
      shown = false;
      // Fade out, then take it out of the layout — removing it in the
      // same frame would cut the transition off at its first pixel.
      el.classList.remove('is-on');
      setTimeout(() => {
        if (!shown) el.hidden = true;
      }, FADE_MS);
    },
    teardown: () => {
      disarm();
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      el.remove();
    },
  };
}

/** m:ss — the same shape the transport prints, kept local because this
 *  module must stay importable by a test with no DOM. */
function _clock(t) {
  const s = Math.max(0, Math.round(t || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
