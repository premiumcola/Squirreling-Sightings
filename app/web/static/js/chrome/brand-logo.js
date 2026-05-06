// ─── chrome/brand-logo.js ──────────────────────────────────────────
// Header brand-logo loader. On the very first paint of the page,
// randomly pick ONE of two logo families with 50/50 probability:
//   * Spy Scout — the squirrel-with-magnifier silhouette.
//   * Acorn Cam — the acorn-bodied surveillance camera.
// The pick is module-scoped so any re-render of the hero (future
// hero refresh) keeps the same family until the next full page
// load. Always uses the `-dark.svg` variant — the homepage palette
// is permanently dark.
//
// The PWA / home-screen icon is NOT random — that's a separate
// asset generated from the Acorn Cam dark master in _build_icons.py
// and pinned via manifest.json + apple-touch-icon links. Random
// only applies to the header.

const FAMILIES = ['spy-scout', 'acorn-cam'];
const HERO_ID = 'heroBrandLogo';

function _pickFamily(){
  // Math.random() not crypto — we just want roughly 50/50 over many
  // page loads, no security property attached.
  return FAMILIES[Math.floor(Math.random() * FAMILIES.length)];
}

function _applyLogoAsset(){
  const img = document.getElementById(HERO_ID);
  if (!img) return;
  const family = _pickFamily();
  img.dataset.brandFamily = family;
  img.src = `/static/img/logos/logo-${family}-dark.svg`;
}

_applyLogoAsset();
