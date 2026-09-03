// ─── chrome/sidebar.js ─────────────────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — desktop sidebar
// behaviour: collapse-with-localStorage on tablet sizes, hidden below
// 768 px (mobile dock takes over), the Einstellungen accordion +
// scroll-link split, and the active-nav scrollspy.
import { byId } from '../core/dom.js';

const _NAV_OPEN_KEY = 'nav_settings_open';

function _setSettingsNavOpen(isOpen) {
  const group = byId('navSettingsGroup');
  const chev = group?.querySelector('.nav-settings-chev');
  const sub = byId('navSettingsSub');
  if (!group || !chev || !sub) return;
  group.classList.toggle('nav--open', isOpen);
  chev.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  sub.classList.toggle('open', isOpen);
  // Drive max-height in pixels so the transition is smooth without
  // committing to a hardcoded ceiling. Measured from scrollHeight at
  // toggle time so adding / removing sub-items keeps animating cleanly.
  sub.style.maxHeight = isOpen ? sub.scrollHeight + 'px' : '0px';
  try {
    localStorage.setItem(_NAV_OPEN_KEY, isOpen ? '1' : '0');
  } catch {}
}

// O11 · sidenav handlers registered via data-action delegation.
// window.* bridges retired — every callsite now triggers via the
// matching <a data-action="..."> / <button data-action="..."> markup.
import { registerAction } from '../core/action-registry.js';

// Chevron click → toggle sub-list, never scroll.
registerAction('toggleSettingsNav', (_el, ev) => {
  ev.stopPropagation?.();
  const isOpen = !byId('navSettingsGroup')?.classList.contains('nav--open');
  _setSettingsNavOpen(isOpen);
  return false;
});

// Main link click → scroll to #settings, never toggle the accordion.
registerAction('navScrollToSettings', (_el, _ev) => {
  const sec = byId('settings');
  if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  _lockNavClickTo('settings');
  return false;
});

// Sub-item click → scroll AND open the matching set-section. Accordion
// stays open (we never close it from sub-item interactions). The
// target set-section id is carried via `data-setting`.
registerAction('navJumpToSetting', (el, _ev) => {
  const secId = el.dataset.setting;
  const sec = secId ? byId(secId) : null;
  if (!sec) return false;
  if (!sec.classList.contains('open') && typeof window.toggleSetSection === 'function') {
    window.toggleSetSection(secId);
  }
  sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  _lockNavClickTo('settings');
  return false;
});

document.addEventListener('DOMContentLoaded', () => {
  let open = false;
  try {
    open = localStorage.getItem(_NAV_OPEN_KEY) === '1';
  } catch {}
  _setSettingsNavOpen(open);
});

// ── Active-nav state ──────────────────────────────────────────────────────
// Tracks which top-level section is currently visible and applies the
// section's accent color via the --na CSS variable. Click sets it
// eagerly, scroll keeps it honest. Logs/Settings stay sticky once
// opened — neither has a useful "scrolled past" signal.
function _setActiveNav(targetId) {
  document.querySelectorAll('.nav [data-target]').forEach((el) => {
    const isActive = el.dataset.target === targetId;
    el.classList.toggle('nav-active', isActive);
    if (isActive && el.dataset.accent) {
      el.style.setProperty('--na', el.dataset.accent);
    }
  });
}
window._setActiveNav = _setActiveNav;

// Click-lock keeps the clicked target pinned for ~900 ms while the
// smooth-scroll settles — mirrors chrome/mobile-dock.js's own click-lock
// for the exact same race: every intermediate scroll tick during a
// smooth-scroll animation re-picks "whichever section the viewport is
// nearest RIGHT NOW", which is very often a section sitting between the
// click origin and the target — reported regression: Gewitter-Archiv
// sits mid-list and kept flashing active regardless of what was
// actually clicked, since each tick stomped the eager set below until
// the animation finally settled on the real target. Re-asserting the
// locked target on every tick (not just skipping the tick) matches the
// mobile-dock fix exactly, so a slower frame that lands mid-lock still
// shows the right thing instead of a brief gap.
let _navClickLockTarget = null;
let _navClickLockTimer = 0;
function _lockNavClickTo(targetId) {
  _setActiveNav(targetId);
  _navClickLockTarget = targetId;
  if (_navClickLockTimer) clearTimeout(_navClickLockTimer);
  _navClickLockTimer = setTimeout(() => {
    _navClickLockTarget = null;
  }, 900);
}

function _initSidebarNav() {
  // Click: lock the highlight to the clicked target immediately (see
  // _lockNavClickTo above) so the highlight tracks the user's intent
  // and the scrollspy below can't flicker it away mid-animation. Skip
  // the Einstellungen button — it doesn't represent a navigable
  // section, only the accordion toggle.
  document.querySelectorAll('.nav a[data-target]').forEach((a) => {
    a.addEventListener('click', () => _lockNavClickTo(a.dataset.target));
  });
  // Scrollspy: pick the section whose top is closest to the viewport
  // top without going past it. Cheap enough to run on every scroll tick.
  // 'weather' dropped — Wetter-Ereignisse merged into #media (Stage 6 of
  // the Mediathek + Wetter-Ereignisse merge); one nav entry, one anchor.
  // 'netz' dropped — Erkennungsprofil no longer has a section of its
  // own; its content lives inline per camera inside #dashboard now. In
  // DOM/scroll order to match the page flow after the reorg.
  const sectionIds = [
    'dashboard',
    'media',
    'achievements',
    'statistik',
    'storms',
    'cameras',
    'settings',
    'logs',
  ];
  let raf = 0;
  const tick = () => {
    raf = 0;
    if (_navClickLockTarget) {
      _setActiveNav(_navClickLockTarget);
      return;
    }
    const top = 80; // account for sticky header / hero offset
    let bestId = null,
      bestY = -Infinity;
    for (const id of sectionIds) {
      const el = byId(id);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.top <= top && r.top > bestY) {
        bestY = r.top;
        bestId = id;
      }
    }
    if (bestId) _setActiveNav(bestId);
  };
  window.addEventListener(
    'scroll',
    () => {
      if (!raf) raf = requestAnimationFrame(tick);
    },
    { passive: true },
  );
  tick();
}
document.addEventListener('DOMContentLoaded', _initSidebarNav);

// ── Sidebar collapse + nav-link smooth-scroll ─────────────────────────────
// IIFE runs on import; safe against missing #sidebar (early return).
(function initSidebar() {
  const sidebar = byId('sidebar');
  if (!sidebar) return;
  const STORAGE_KEY = 'tspy_sidebar_collapsed';

  function setCollapsed(yes) {
    sidebar.classList.toggle('collapsed', yes);
    try {
      localStorage.setItem(STORAGE_KEY, yes ? '1' : '0');
    } catch {}
  }

  // Desktop (>1024px): always collapsed; CSS hover expands.
  // Tablet  (768-1024px): collapsed by default, persisted via localStorage.
  // Mobile  (≤768px): hidden — navigation lives in the bottom dock now,
  // so the drawer + hamburger + edge-swipe machinery is gone.
  if (window.innerWidth > 1024) {
    sidebar.classList.add('collapsed');
  } else if (window.innerWidth > 768) {
    const saved = localStorage.getItem(STORAGE_KEY);
    setCollapsed(saved !== '0');
  }

  document.querySelectorAll('.nav a').forEach((a) =>
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const target = document.querySelector(a.getAttribute('href'));
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      // One-shot offset correction: if scroll-margin + padding still leaves
      // a gap, nudge to the top. Needed mainly for sections late in the flow.
      setTimeout(() => {
        const el = document.querySelector(a.getAttribute('href'));
        if (!el) return;
        const rect = el.getBoundingClientRect();
        if (rect.top > 12) {
          window.scrollBy({ top: rect.top - 8, behavior: 'smooth' });
        }
      }, 420);
    }),
  );
})();
