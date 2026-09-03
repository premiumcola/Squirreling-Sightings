// ─── dashboard/_placeholders.js ─────────────────────────────────────────
// The two camera-tile placeholder states — red "KEIN SIGNAL" and blue
// "VERBINDE…" — plus the shell they share and the restore path
// `showCameraReloadAnimation` takes when its poll gives up.
//
// Split out of dashboard.js, which was 1082 lines against this repo's
// 400-line ceiling. Pure string builders with one DOM write
// (`_restorePlaceholder`) and no imports at all: nothing here reads
// `state`, fetches, or registers a listener.
function _placeholderShell(accent, centerHtml, bracketKeyframe) {
  return `<div class="cv-ph cv-ph--${accent}">
    <div class="cv-ph-grid"></div>
    <svg class="cv-ph-brackets" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <g fill="none" style="animation:${bracketKeyframe} 2s ease-in-out infinite">
        <polyline points="0,30 0,0 30,0"  stroke-width="2.5" class="cv-ph-br cv-ph-br--tl"/>
        <polyline points="70,0 100,0 100,30" stroke-width="2"   class="cv-ph-br cv-ph-br--tr" style="animation-delay:.5s"/>
        <polyline points="100,70 100,100 70,100" stroke-width="2.5" class="cv-ph-br cv-ph-br--br" style="animation-delay:1s"/>
        <polyline points="30,100 0,100 0,70"    stroke-width="2"   class="cv-ph-br cv-ph-br--bl" style="animation-delay:1.5s"/>
      </g>
    </svg>
    <div class="cv-ph-center">${centerHtml}</div>
  </div>`;
}

// Flat-design camera SVGs — filled silhouettes with tonal-shift depth.
// No hairline strokes (would alias under transform:scale at small
// tiles); each layer is a filled shape so the icon stays crisp at
// 52–72 px renders. Lens uses dark-mass + light-iris for "flat depth"
// instead of a stroked outline. The red slash is a 6 px-wide
// parallelogram, not a stroke, so it doesn't thin under animation.
const _CAM_OFF_SVG = `<svg viewBox="0 0 48 48" width="72" height="72" aria-hidden="true" style="display:block">
  <rect x="8" y="14" width="24" height="20" rx="3" fill="rgba(255,255,255,0.32)"/>
  <path d="M32 20 L40 14 V34 L32 28 Z" fill="rgba(255,255,255,0.22)"/>
  <circle cx="20" cy="24" r="5" fill="rgba(0,0,0,0.5)"/>
  <circle cx="20" cy="24" r="2" fill="rgba(255,255,255,0.55)"/>
  <polygon points="7,3 3,7 41,45 45,41" fill="rgba(239,68,68,0.95)"/>
</svg>`;
const _CAM_SM_SVG = `<svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true" style="display:block">
  <rect x="8" y="14" width="24" height="20" rx="3" fill="rgba(59,130,246,0.42)"/>
  <path d="M32 20 L40 14 V34 L32 28 Z" fill="rgba(59,130,246,0.28)"/>
  <circle cx="20" cy="24" r="5" fill="rgba(8,17,38,0.85)"/>
  <circle cx="20" cy="24" r="2" fill="rgba(147,197,253,0.95)"/>
</svg>`;

export function _makeOfflinePlaceholder() {
  // Red: four expanding rings + crosshair + struck-through camera icon.
  const rings = [0, 1, 2, 3]
    .map((i) => `<span class="cv-ph-ring" style="animation-delay:${i}s"></span>`)
    .join('');
  const center = `
    <div class="cv-ph-stage">
      <div class="cv-ph-crosshair"></div>
      ${rings}
      <div class="cv-ph-icon cv-ph-icon--glitch cv-ph-icon--red">${_CAM_OFF_SVG}</div>
    </div>
    <div class="cv-ph-label cv-ph-label--flicker cv-ph-label--red">KEIN SIGNAL</div>
  `;
  return _placeholderShell('red', center, 'bracketPulseRed');
}

export function _makeConnectingPlaceholder() {
  // Blue: rotating radar cone + orbiting dots + small camera icon, all
  // inside the same stage so they share one center.
  const center = `
    <div class="cv-ph-stage">
      <svg class="cv-ph-guides" viewBox="-100 -100 200 200" aria-hidden="true">
        <circle cx="0" cy="0" r="85" fill="rgba(59,130,246,0.05)"/>
        <circle cx="0" cy="0" r="45" fill="rgba(59,130,246,0.07)"/>
      </svg>
      <svg class="cv-ph-radar" viewBox="-100 -100 200 200" aria-hidden="true">
        <path d="M0,0 L85,-49 A98,98 0 0 1 85,49 Z" fill="rgba(59,130,246,0.2)"/>
        <circle class="cv-ph-radar-dot" cx="85" cy="49" r="5" fill="rgba(59,130,246,0.95)"/>
      </svg>
      <span class="cv-ph-orbit cv-ph-orbit--1"></span>
      <span class="cv-ph-orbit cv-ph-orbit--2"></span>
      <span class="cv-ph-orbit cv-ph-orbit--3"></span>
      <div class="cv-ph-icon">${_CAM_SM_SVG}</div>
    </div>
    <div class="cv-ph-label cv-ph-label--blue">VERBINDE…</div>
  `;
  return _placeholderShell('blue', center, 'bracketPulseBlue');
}

// Restore the offline placeholder + bump the snapshot src after a
// reload-animation give-up. Used by showCameraReloadAnimation when its
// poll hits the 15-attempt ceiling without seeing the camera return to
// active.
export function _restorePlaceholder(card) {
  const placeholder = card.querySelector('.cv-loading-placeholder');
  if (placeholder) placeholder.innerHTML = _makeOfflinePlaceholder();
  const img = card.querySelector('.cv-img');
  if (img) {
    const base = img.src.split('?')[0];
    img.src = base + '?t=' + Date.now();
  }
}
