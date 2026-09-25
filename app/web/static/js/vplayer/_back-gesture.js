// ─── vplayer/_back-gesture.js ──────────────────────────────────────────────
// „Zurück" the way the phone already means it.
//
// „Zudem will ich aus dem player mit der iphone typischen am bildschirm
// seitlich zurück-wisch-bewegung raus gehen können."
//
// That gesture is not a swipe handler on iOS — it is the system's
// back-navigation, and in a browser it means one step back in history.
// The app had never pushed a history entry for anything, so the swipe
// left the app entirely instead of closing the player. So the honest
// implementation is the one the platform is already asking for: the open
// player IS a history entry, and going back from it closes it.
//
// TWO PATHS, because the gesture only exists on one of them:
//
//   Safari       the edge swipe is the system gesture. Nothing to
//                listen for — `popstate` is what arrives, and that is
//                handled below.
//   standalone   a page added to the home screen has no browser chrome
//                and no edge gesture at all. There the drag has to be
//                read directly, and only from the very edge — the same
//                20-odd pixels iOS reserves — because anywhere else on
//                the picture a horizontal drag already means prev/next.
//
// The two cannot double-fire: the drag path closes through the same
// history step, so whichever fires first consumes the entry.
//
// ONE ENTRY PER PLAYER ON SCREEN, NOT PER CLIP. Blättern (prev/next)
// ersetzt den Player durch einen neuen. Bis 2026-09-25 räumte der alte
// dabei seinen Verlaufseintrag mit `history.back()` ab, und der neue
// legte sofort einen eigenen an. `history.back()` ist aber asynchron: das
// `popstate` des alten Schritts kam erst an, als der NEUE Player schon
// lauschte — und der verstand es als „zurück" und schloss sich. Jeder
// Tipp auf den Weiter-Pfeil landete so wieder in der Übersicht. Beim
// Ersetzen wird der Eintrag deshalb ÜBERGEBEN statt ab- und neu angelegt
// (`keepEntry` beim Abbau, `adopt` beim Aufbau).

const _EDGE_PX = 24;
const _TRIGGER_PX = 64;
const _SLOPE = 1.4;

/** PURE: does this drag read as "back"?
 *
 * Only from the left edge, only clearly rightward, and only when it is
 * more horizontal than vertical — a diagonal is someone scrolling the
 * panel underneath, and a drag that starts in the middle of the picture
 * belongs to prev/next. */
export function isBackSwipe(startX, dx, dy) {
  if (startX > _EDGE_PX) return false;
  if (dx < _TRIGGER_PX) return false;
  return Math.abs(dx) > Math.abs(dy) * _SLOPE;
}

/**
 * Make `root` closable by the platform's back gesture.
 *
 * `onBack` is called at most once per open. Returns a teardown that must
 * run on close — including the close that came from the ✕ or Escape, in
 * which case it also pops the history entry so the stack does not grow
 * one step per clip the operator looks at.
 */
export function installBackGesture(root, onBack, { adopt = false } = {}) {
  let done = false;
  let startX = 0;
  let startY = 0;
  let tracking = false;

  const finish = () => {
    if (done) return;
    done = true;
    onBack?.();
  };

  // THE HISTORY ENTRY. Same URL — a player is not a page, and rewriting
  // the hash here would wake router.js's own hashchange handler and
  // switch sections behind the player.
  const marker = { sqPlayer: Date.now() };
  let pushed = false;
  if (adopt) {
    // Der Vorgänger hat seinen Eintrag liegen lassen — er gehört jetzt uns.
    pushed = true;
  } else {
    try {
      globalThis.history?.pushState?.(marker, '', globalThis.location?.href);
      pushed = true;
    } catch {
      pushed = false;
    }
  }

  const onPop = () => {
    // The entry is already gone by the time this fires — closing must
    // not try to pop it a second time.
    pushed = false;
    finish();
  };
  globalThis.addEventListener?.('popstate', onPop);

  const onDown = (e) => {
    tracking = false;
    if (e.pointerType === 'mouse') return;
    startX = e.clientX;
    startY = e.clientY;
    tracking = startX <= _EDGE_PX;
  };
  const onMove = (e) => {
    if (!tracking || done) return;
    if (!isBackSwipe(startX, e.clientX - startX, e.clientY - startY)) return;
    tracking = false;
    // Through history, not straight to onBack: the entry has to come off
    // the stack either way, and going back is also what makes the visual
    // transition match what the gesture promised.
    if (pushed) globalThis.history?.back?.();
    else finish();
  };
  const stop = () => {
    tracking = false;
  };

  root?.addEventListener?.('pointerdown', onDown, { passive: true });
  root?.addEventListener?.('pointermove', onMove, { passive: true });
  for (const ev of ['pointerup', 'pointercancel']) {
    root?.addEventListener?.(ev, stop, { passive: true });
  }

  /** Abbau. `keepEntry` lässt den Verlaufseintrag stehen, damit der
   *  nachfolgende Player ihn übernehmen kann; zurückgegeben wird, ob es
   *  einen zu übernehmen gibt. */
  return function teardownBackGesture({ keepEntry = false } = {}) {
    done = true;
    globalThis.removeEventListener?.('popstate', onPop);
    root?.removeEventListener?.('pointerdown', onDown);
    root?.removeEventListener?.('pointermove', onMove);
    for (const ev of ['pointerup', 'pointercancel']) {
      root?.removeEventListener?.(ev, stop);
    }
    if (keepEntry) {
      const handover = pushed;
      pushed = false;
      return handover;
    }
    // Closed by the ✕ or Escape while our entry is still on the stack:
    // drop it, or every clip viewed would leave a step behind and the
    // phone's back gesture would then walk backwards through them.
    if (pushed) {
      pushed = false;
      try {
        globalThis.history?.back?.();
      } catch {
        /* a stack we may not touch is not worth an error */
      }
    }
    return false;
  };
}
