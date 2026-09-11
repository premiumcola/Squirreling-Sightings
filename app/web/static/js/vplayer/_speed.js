// ─── vplayer/_speed.js ─────────────────────────────────────────────────────
// Playback speed, as ONE button that cycles a ladder.
//
// „bitte integriere ein 1,5 2x 3x geschwindikgiet button! den will ich
// auch während dem videolauf anpassen können!" — so the rungs are the
// operator's own, and the control does its work by writing
// `video.playbackRate`. That is the one way to change speed that neither
// pauses nor reseeks: the element keeps playing, from exactly where it
// is, at the new rate. Nothing here touches `currentTime` or `play()`.
//
// ONE BUTTON, NOT A MENU. „den will ich auch während dem videolauf
// anpassen können" means the change has to cost a single tap on a
// control that is already on screen — a popover would be tap, read,
// tap, and it would cover the picture while it was open. The button
// shows where it IS and its label names where the next tap goes, which
// is the whole of the interface.
//
// WHY NOT mediaview/player/_speed.js. That module exists, is tested, and
// this is deliberately not a second copy of it — it is a different
// ladder. Its SPEED_STEPS are [0.5, 1, 1.5, 2]: it starts BELOW normal
// and stops at 2×, and those steps are a module constant its own tests
// pin, with no way to pass others in. The rungs asked for here start at
// 1× and reach 3×, so they cannot be expressed through that function at
// all. What is not duplicated is everything else about it — no keyboard
// binding, no direction argument, no cross-control sync protocol,
// because here the one button owns the whole control.
//
// THE CHOICE OUTLIVES THE CLIP. Every open builds a FRESH <video>
// (_stage.js), so a rate set on one clip would be gone the moment the
// operator paged to the next — and „während dem videolauf" describes a
// viewing session, not a single recording. Module scope is exactly that
// session: the choice survives prev/next and a close-and-reopen, and a
// page reload starts at 1× again. That is also why this is NOT the
// mediaview reset rule (which clears to 1× on every mount): there the
// video element is REUSED across opens, so a leftover rate had no
// control on screen to explain it. Here the button is on the picture
// and shows the rate it is running at.

/** The rungs, in cycle order. The operator's own list, plus the 1× the
 *  ladder has to be able to come back to. */
export const VP_SPEEDS = [1, 1.5, 2, 3];

/**
 * PURE: the rung one tap past `current`.
 *
 * Strictly-greater rather than an index lookup, so a rate that is not on
 * the ladder at all — a stale 2.4 from a system-player handoff, or a
 * browser that clamped one — still ADVANCES instead of sticking on a
 * rung it never matched. Past the top it wraps to 1×, which is the only
 * way back to normal speed from a single button.
 *
 * @param {number} current  video.playbackRate
 * @returns {number} a value from VP_SPEEDS, always
 */
export function nextSpeed(current) {
  const v = Number.isFinite(current) && current > 0 ? current : 1;
  // A hair of slack: 1.5 does not always come back out of a media
  // element as exactly 1.5, and an equality test would then hand back
  // the rung it is already on.
  for (const step of VP_SPEEDS) {
    if (step > v + 0.001) return step;
  }
  return VP_SPEEDS[0];
}

/**
 * PURE: what the button prints for a rate.
 *
 * German decimal comma — „1,5×", never „1.5×". The rest of this player
 * writes its numbers that way (timeline/_rail.js's pre-roll captions),
 * and a dot in a German UI reads as a thousands separator.
 */
export function speedLabel(rate) {
  const v = Number.isFinite(rate) && rate > 0 ? rate : 1;
  const n = Math.round(v * 100) / 100;
  return `${String(n).replace('.', ',')}×`;
}

/** The session's chosen rate. See the header: module scope IS the
 *  session, which is what carries the choice into the next clip. */
let _sessionRate = 1;

/**
 * Mount the speed button into the top strip's action group.
 *
 * @param {HTMLElement} host   the strip's `.vp-top-speed` slot
 * @param {object} cfg         normalised config from _config.js
 * @param {object} stage       handle from _stage.js
 * @returns {{teardown: () => void}|null}
 */
export function mountSpeed(host, cfg, stage) {
  // A live surface has no rate to change: its picture is a snapshot
  // <img> fed by the detection loop, and a control that cannot answer a
  // press is worse on a 375 px screen than an absent one.
  if (!host || cfg.flags.live || !stage?.video) return null;
  const video = stage.video;

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'vp-top-rate';
  host.appendChild(btn);

  const paint = () => {
    const rate = video.playbackRate || 1;
    btn.textContent = speedLabel(rate);
    // Not 1× is a state the picture itself cannot show — a clip at 3×
    // just looks like a fast animal. The tint is what says why.
    btn.dataset.on = rate === 1 ? '0' : '1';
    const words =
      `Wiedergabegeschwindigkeit ${speedLabel(rate)} — ` +
      `tippen für ${speedLabel(nextSpeed(rate))}`;
    btn.setAttribute('aria-label', words);
    btn.setAttribute('title', words);
  };

  const onClick = (ev) => {
    // The strip sits ON the picture, and the stage below it toggles the
    // chrome on a tap. Without this, changing speed would also start
    // fading away the button that did it.
    ev.stopPropagation();
    _sessionRate = nextSpeed(video.playbackRate || 1);
    video.playbackRate = _sessionRate;
    paint();
  };

  // `ratechange` is native and fires on ANY write, so the label is
  // correct even when something else moved the rate — a system-player
  // handoff comes back at 1× and the button must not keep claiming 3×.
  const reapply = () => {
    if (video.playbackRate !== _sessionRate) video.playbackRate = _sessionRate;
  };
  btn.addEventListener('click', onClick);
  video.addEventListener('ratechange', paint);
  // The source arrives after this mount, and some engines reset the rate
  // with it. Re-asserting on metadata is what makes „next clip, same
  // speed" hold rather than nearly hold.
  video.addEventListener('loadedmetadata', reapply);

  video.playbackRate = _sessionRate;
  paint();

  return {
    teardown: () => {
      btn.removeEventListener('click', onClick);
      video.removeEventListener('ratechange', paint);
      video.removeEventListener('loadedmetadata', reapply);
      btn.remove();
    },
  };
}
