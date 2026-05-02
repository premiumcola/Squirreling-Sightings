// ─── chrome/sidebar.js ─────────────────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — desktop sidebar
// behaviour: collapse-with-localStorage on tablet sizes, hidden below
// 768 px (mobile dock takes over), the Einstellungen accordion +
// scroll-link split, and the active-nav scrollspy.
import { byId } from '../core/dom.js';

const _NAV_OPEN_KEY = 'nav_settings_open';

function _setSettingsNavOpen(isOpen){
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
  sub.style.maxHeight = isOpen ? (sub.scrollHeight + 'px') : '0px';
  try { localStorage.setItem(_NAV_OPEN_KEY, isOpen ? '1' : '0'); } catch {}
}

// Chevron click → toggle sub-list, never scroll.
window.toggleSettingsNav = function(ev){
  if (ev){ ev.preventDefault?.(); ev.stopPropagation?.(); }
  const isOpen = !byId('navSettingsGroup')?.classList.contains('nav--open');
  _setSettingsNavOpen(isOpen);
  return false;
};

// Main link click → scroll to #settings, never toggle the accordion.
window.navScrollToSettings = function(ev){
  ev?.preventDefault?.();
  const sec = byId('settings');
  if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  _setActiveNav('settings');
  return false;
};

// Sub-item click → scroll AND open the matching set-section. Accordion
// stays open (we never close it from sub-item interactions).
window.navJumpToSetting = function(ev, secId){
  ev?.preventDefault?.();
  const sec = byId(secId);
  if (!sec) return false;
  if (!sec.classList.contains('open') && typeof window.toggleSetSection === 'function'){
    window.toggleSetSection(secId);
    if (secId === 'set-timelapse' && typeof window.loadTlSettings === 'function') {
      window.loadTlSettings();
    }
  }
  sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  _setActiveNav('settings');
  return false;
};

document.addEventListener('DOMContentLoaded', () => {
  let open = false;
  try { open = localStorage.getItem(_NAV_OPEN_KEY) === '1'; } catch {}
  _setSettingsNavOpen(open);
});

// ── Active-nav state ──────────────────────────────────────────────────────
// Tracks which top-level section is currently visible and applies the
// section's accent color via the --na CSS variable. Click sets it
// eagerly, scroll keeps it honest. Logs/Settings stay sticky once
// opened — neither has a useful "scrolled past" signal.
function _setActiveNav(targetId){
  document.querySelectorAll('.nav [data-target]').forEach(el => {
    const isActive = el.dataset.target === targetId;
    el.classList.toggle('nav-active', isActive);
    if (isActive && el.dataset.accent){
      el.style.setProperty('--na', el.dataset.accent);
    }
  });
}
window._setActiveNav = _setActiveNav;

function _initSidebarNav(){
  // Click: set active immediately so the highlight tracks the user's
  // intent before the scroll animation finishes. Skip the
  // Einstellungen button — it doesn't represent a navigable section,
  // only the accordion toggle.
  document.querySelectorAll('.nav a[data-target]').forEach(a => {
    a.addEventListener('click', () => {
      _setActiveNav(a.dataset.target);
    });
  });
  // Scrollspy: pick the section whose top is closest to the viewport
  // top without going past it. Cheap enough to run on every scroll tick.
  const sectionIds = ['dashboard', 'statistik', 'media', 'achievements', 'weather', 'cameras', 'settings', 'logs'];
  let raf = 0;
  const tick = () => {
    raf = 0;
    const top = 80; // account for sticky header / hero offset
    let bestId = null, bestY = -Infinity;
    for (const id of sectionIds){
      const el = byId(id);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.top <= top && r.top > bestY){ bestY = r.top; bestId = id; }
    }
    if (bestId) _setActiveNav(bestId);
  };
  window.addEventListener('scroll', () => {
    if (!raf) raf = requestAnimationFrame(tick);
  }, { passive: true });
  tick();
}
document.addEventListener('DOMContentLoaded', _initSidebarNav);

// ── Sidebar collapse + nav-link smooth-scroll ─────────────────────────────
// IIFE runs on import; safe against missing #sidebar (early return).
(function initSidebar(){
  const sidebar = byId('sidebar');
  if (!sidebar) return;
  const STORAGE_KEY = 'tspy_sidebar_collapsed';

  function setCollapsed(yes){
    sidebar.classList.toggle('collapsed', yes);
    try { localStorage.setItem(STORAGE_KEY, yes ? '1' : '0'); } catch {}
  }

  // Desktop (>1024px): always collapsed; CSS hover expands.
  // Tablet  (768-1024px): collapsed by default, persisted via localStorage.
  // Mobile  (≤768px): hidden — navigation lives in the bottom dock now,
  // so the drawer + hamburger + edge-swipe machinery is gone.
  if (window.innerWidth > 1024){
    sidebar.classList.add('collapsed');
  } else if (window.innerWidth > 768){
    const saved = localStorage.getItem(STORAGE_KEY);
    setCollapsed(saved !== '0');
  }

  document.querySelectorAll('.nav a').forEach(a => a.addEventListener('click', e => {
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
      if (rect.top > 12){
        window.scrollBy({ top: rect.top - 8, behavior: 'smooth' });
      }
    }, 420);
  }));
})();
