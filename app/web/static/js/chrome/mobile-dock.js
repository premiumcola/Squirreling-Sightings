// ─── chrome/mobile-dock.js ─────────────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — the 5-tab bottom
// nav that replaces the old mobile topbar. Click → smooth-scroll;
// scroll-spy auto-activates the tab whose section is centered.
// Sections without a matching dock entry (cameras, media, logs) ride
// along with a related tab via the data-dock-section attribute.
import { state } from '../core/state.js';

(function _initMobileDock() {
  const dock = document.getElementById('mobileDock');
  if (!dock) return;
  const btns = Array.from(dock.querySelectorAll('.m-dock-btn'));
  btns.forEach((btn) => {
    btn.style.setProperty('--m-acc', btn.dataset.accentRgb);
  });

  function setActiveByDockTarget(target) {
    btns.forEach((b) => b.classList.toggle('is-active', b.dataset.target === target));
  }

  // Section-id → dock-target. data-dock-section overrides the default
  // self-mapping so #cameras rides Live, #media rides Statistik, #logs
  // rides Setup. trackedSections is in DOM/scroll order so the spy
  // loop can early-break once it crosses the probe.
  const sectionIds = [
    'dashboard',
    'cameras',
    'statistik',
    'media',
    'achievements',
    'weather',
    'settings',
    'logs',
  ];
  const targetById = {};
  const trackedSections = [];
  for (const id of sectionIds) {
    const el = document.getElementById(id);
    if (!el) continue;
    targetById[id] = el.dataset.dockSection || id;
    trackedSections.push(el);
  }

  // Click-lock keeps the tapped tab pinned for ~900 ms while the
  // smooth-scroll settles, so scroll-spy can't flip-flop and force
  // the user to tap twice.
  let clickLockTarget = null;
  let clickLockTimer = 0;
  let scrollRaf = 0;

  btns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.target;
      const el = document.getElementById(targetId);
      if (!el) return;
      const wasActive = btn.classList.contains('is-active');
      clickLockTarget = targetId;
      if (clickLockTimer) clearTimeout(clickLockTimer);
      clickLockTimer = setTimeout(() => {
        clickLockTarget = null;
        updateActiveFromScroll();
      }, 900);
      setActiveByDockTarget(targetId);
      if (wasActive) {
        window.scrollTo({ top: el.offsetTop - 12, behavior: 'smooth' });
      } else {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      if (location.hash !== '#' + targetId) {
        try {
          history.replaceState(null, '', '#' + targetId);
        } catch {}
      }
    });
  });

  // Position-based scroll-spy. The previous IntersectionObserver band
  // (rootMargin -30%/-55%) was too narrow — short sections and the
  // last section on the page never reached it, so their tabs never
  // lit up. New rule: activate the last section whose top has crossed
  // a probe line at vh*0.30. Bottom-of-page snaps to the last section
  // regardless so settings/logs always lights Setup at the page foot.
  function updateActiveFromScroll() {
    scrollRaf = 0;
    if (clickLockTarget) {
      setActiveByDockTarget(clickLockTarget);
      return;
    }
    if (!trackedSections.length) return;
    const vh = window.innerHeight;
    const sy = window.scrollY;
    const docH = document.documentElement.scrollHeight;
    if (sy + vh >= docH - 4) {
      const last = trackedSections[trackedSections.length - 1];
      setActiveByDockTarget(targetById[last.id]);
      return;
    }
    const probe = sy + vh * 0.3;
    let bestId = null;
    for (const el of trackedSections) {
      const top = el.getBoundingClientRect().top + sy;
      if (top <= probe) bestId = targetById[el.id];
      else break;
    }
    if (bestId) setActiveByDockTarget(bestId);
  }
  function scheduleScrollUpdate() {
    if (scrollRaf) return;
    scrollRaf = requestAnimationFrame(updateActiveFromScroll);
  }
  window.addEventListener('scroll', scheduleScrollUpdate, { passive: true });
  window.addEventListener('resize', scheduleScrollUpdate);
  updateActiveFromScroll();

  // The dashboard pill needs a live-dot indicator when at least one
  // camera is enabled+armed. live-update.js calls this through window
  // every 3 s (not yet a direct import — armed-state lookup lives in
  // legacy state for now).
  window._updateMobileDockLiveDot = function () {
    const dot = dock.querySelector('.m-dock-btn[data-target="dashboard"] .m-dock-livedot');
    if (!dot) return;
    const anyLive = (state.cameras || []).some((c) => c.enabled && c.armed);
    dot.hidden = !anyLive;
  };
  window._updateMobileDockLiveDot();
})();
