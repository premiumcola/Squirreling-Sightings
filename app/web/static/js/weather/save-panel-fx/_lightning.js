// ─── weather/save-panel-fx/_lightning.js ───────────────────────────────
// The irregular strike. Everything visible is one CSS keyframe
// (ws-fx-strike in css/23c-weather-fx.css) with a SINGLE luminance
// peak; this module only decides WHEN, using one setTimeout that
// re-arms itself from nextFlashDelay. No rAF, no interval — a stopped
// scheduler has no timer left behind at all.
//
// Why a self-re-arming timeout rather than setInterval: the whole point
// is that the gaps are unequal ("hin und wieder, so unregelmäßig"), and
// an interval is by definition a metronome.
import { FLASH_FIRST_MS, nextFlashDelay } from './_helpers.js';

const STRIKE_CLASS = 'is-strike';

export function createLightning(el) {
  let timer = 0;
  let distant = false;

  function _strike() {
    // Restart the keyframe: the class is left on between strikes (the
    // animation ends back at opacity 0, so it is invisible), and only a
    // remove → forced reflow → add sequence makes the browser replay it.
    el.classList.remove(STRIKE_CLASS);
    void el.offsetWidth;
    el.classList.add(STRIKE_CLASS);
    timer = setTimeout(_strike, nextFlashDelay(Math.random(), distant));
  }

  return {
    setDistant(next) {
      distant = !!next;
    },
    start() {
      if (timer) return;
      timer = setTimeout(_strike, FLASH_FIRST_MS);
    },
    stop() {
      if (timer) clearTimeout(timer);
      timer = 0;
      el.classList.remove(STRIKE_CLASS);
    },
  };
}
