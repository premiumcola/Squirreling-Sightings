// ─── vplayer/_stage-chrome.js ──────────────────────────────────────────────
// The controls that belong ON the picture rather than in a bar around it.
//
// Today that is prev/next. They lived in the title row, where they read
// as menu items beside a camera name — „das links, rechts vielleicht
// eher links, rechts am Video, oben ist son bisschen verwirrend in der
// Zettelleiste. Und die drei Punkte und das x, das passt da oben." At
// the picture's own edges they are unmistakably "the clip before / the
// clip after", and they cost the title row nothing.
//
// EVERYTHING HERE IS GLASS. Translucent, blurred, never a solid slab —
// the same language the transport discs use, so the picture stays the
// subject and the chrome reads as one set rather than as three families
// of button that happen to share a screen.
//
// It also inherits the auto-hide for free: the group is a child of the
// stage, and 30h fades every `[data-chrome='0']` child of it. So the
// chevrons disappear with the transport while the clip runs and come
// back on the same gesture — „wenn ich drüber hover einblenden, wenn ich
// weghover schnell wieder ausblenden, damit ich das Video ordentlich
// sehen kann".

const _CHEVRON_LEFT =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M15 5l-7 7 7 7"/></svg>';
const _CHEVRON_RIGHT =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M9 5l7 7-7 7"/></svg>';

/**
 * Mount the on-picture chrome.
 *
 * @param {HTMLElement} stageEl  the shell's [data-slot="stage"]
 * @param {object} cfg           normalised config from _config.js
 * @param {object} handlers      { onPrev, onNext }
 * @returns {{teardown: () => void}|null}
 */
export function mountStageChrome(stageEl, cfg, handlers = {}) {
  if (!stageEl) return null;
  const { onPrev, onNext } = handlers;
  // A chevron only exists when there is somewhere to go. A permanently
  // dead arrow on the picture is worse than no arrow — it invites the
  // tap it will not answer.
  const canNav = cfg.flags.canNavigate;
  const wants = [];
  if (canNav && typeof onPrev === 'function') {
    wants.push(['prev', 'Vorherige Aufnahme', _CHEVRON_LEFT, onPrev]);
  }
  if (canNav && typeof onNext === 'function') {
    wants.push(['next', 'Nächste Aufnahme', _CHEVRON_RIGHT, onNext]);
  }
  if (!wants.length) return null;

  const host = document.createElement('div');
  host.className = 'vp-glass';
  host.innerHTML = wants
    .map(
      ([side, label, svg]) =>
        `<button type="button" class="vp-glass-nav vp-glass-nav--${side}" ` +
        `aria-label="${label}">${svg}</button>`,
    )
    .join('');
  stageEl.appendChild(host);

  const wired = [];
  for (const [side, , , fn] of wants) {
    const el = host.querySelector(`.vp-glass-nav--${side}`);
    if (!el) continue;
    el.addEventListener('click', fn);
    wired.push([el, fn]);
  }

  return {
    teardown: () => {
      for (const [el, fn] of wired) el.removeEventListener('click', fn);
      host.remove();
    },
  };
}
