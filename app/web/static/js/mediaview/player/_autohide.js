// ─── mediaview/player/_autohide.js ─────────────────────────────────────────
// The native player's single most characteristic behaviour: chrome fades
// away a couple of seconds into playback and comes back on a tap. Ours
// does the same, with one rule that is not negotiable — a PAUSED clip
// always keeps its controls. Hiding the transport on a still frame leaves
// the operator tapping a black rectangle to find out where the buttons
// went.
//
// The whole mechanism is one attribute on the stage
// (``data-chrome="0|1"``); 30h-mediaview-player.css does the fading, so
// which elements participate is a CSS decision, not a JS one. Reduced
// motion drops the transition there — the hide itself stays, it is a
// visibility behaviour, not an animation.

const _IDLE_MS = 2600;

/**
 * Should the chrome be allowed to disappear right now?
 * Only while the clip is actually running: no video, paused, or ended
 * all keep it on screen.
 */
export function shouldHideChrome(video) {
  return !!video && !video.paused && !video.ended;
}

/**
 * Wire auto-hide onto a stage element.
 *
 * @param {HTMLElement} stage      the .mv-shell-stage node
 * @param {Function} getVideo      () => HTMLVideoElement|null
 * @returns {{ reveal(): void, teardown(): void }|null}
 */
export function installChromeAutoHide(stage, getVideo) {
  if (!stage || typeof getVideo !== 'function') return null;
  let timer = 0;
  const setVisible = (on) => {
    stage.dataset.chrome = on ? '1' : '0';
  };
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (shouldHideChrome(getVideo())) setVisible(false);
    }, _IDLE_MS);
  };
  const reveal = () => {
    setVisible(true);
    arm();
  };
  // A tap on the picture itself toggles, exactly like the native player.
  // A tap that lands on a control must NOT toggle — it just re-arms the
  // idle timer, or the button would vanish under the finger that pressed
  // it.
  const onPointerDown = (ev) => {
    if (ev.target && ev.target.closest && ev.target.closest('button, a, input, [data-slot]')) {
      reveal();
      return;
    }
    if (stage.dataset.chrome === '0') reveal();
    else if (shouldHideChrome(getVideo())) setVisible(false);
    else arm();
  };
  // Desktop: any mouse movement over the stage brings the chrome back;
  // leaving the stage hides it immediately while playing. Pointer events
  // would double-fire with the tap handler above, so this is mouse-only.
  const onMouseMove = () => reveal();
  const onMouseLeave = () => {
    clearTimeout(timer);
    if (shouldHideChrome(getVideo())) setVisible(false);
  };
  stage.addEventListener('pointerdown', onPointerDown);
  stage.addEventListener('mousemove', onMouseMove);
  stage.addEventListener('mouseleave', onMouseLeave);
  reveal();
  return {
    reveal,
    teardown: () => {
      clearTimeout(timer);
      stage.removeEventListener('pointerdown', onPointerDown);
      stage.removeEventListener('mousemove', onMouseMove);
      stage.removeEventListener('mouseleave', onMouseLeave);
      delete stage.dataset.chrome;
    },
  };
}
