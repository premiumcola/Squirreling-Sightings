// ─── chrome/settings-collapse.js ───────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — the
// "Einstellungen" sub-section accordion. Each .set-section[data-accent]
// stamps its accent RGB triplet on a local --sa CSS var so the
// accent-tinted border + header rules pick it up; the same trick on
// .panel.section[data-accent] feeds --acc for top-level panels.
import { byId } from '../core/dom.js';

window.toggleSetSection = function (id) {
  const el = byId(id);
  if (!el) return;
  if (el.dataset.accent) el.style.setProperty('--sa', el.dataset.accent);
  const opening = !el.classList.contains('open');
  el.classList.toggle('open', opening);
};

// Seed --sa / --acc on first load so even closed sections render with
// the correct accent the moment they open (no first-click flash).
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.set-section[data-accent]').forEach((el) => {
    el.style.setProperty('--sa', el.dataset.accent);
  });
  document.querySelectorAll('.panel.section[data-accent]').forEach((el) => {
    el.style.setProperty('--acc', el.dataset.accent);
  });
});
