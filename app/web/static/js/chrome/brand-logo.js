// ─── chrome/brand-logo.js ──────────────────────────────────────────
// Header brand-logo loader. Two design states:
//
//   1. On the very first paint of the page, randomly pick ONE of two
//      logo families with 50/50 probability:
//        * Spy Scout — the squirrel-with-magnifier silhouette.
//        * Acorn Cam — the acorn-bodied surveillance camera.
//      Saved into a module-scoped variable so any re-render of the
//      hero (theme toggle, future hero refresh) keeps the same family
//      until the next full page load.
//
//   2. On theme change, swap the asset's src between the `-dark.svg`
//      and `-light.svg` variant of the chosen family — DON'T re-roll
//      the random pick. The theme system fires a `tamspy:theme`
//      CustomEvent whenever the resolved theme actually changes;
//      this module subscribes to it.
//
// The PWA / home-screen icon is NOT random — that's a separate asset
// generated from the Acorn Cam dark master in _build_icons.py and
// pinned via manifest.json + apple-touch-icon links. Random only
// applies to the header.

const FAMILIES = ['spy-scout', 'acorn-cam'];
const HERO_ID = 'heroBrandLogo';

// Module-scoped pick — mutating this from any other code path is a
// design-violation; brand identity should be stable across the
// session.
let _chosenFamily = null;

function _pickFamily(){
  // Math.random() not crypto — we just want roughly 50/50 over many
  // page loads, no security property attached.
  return FAMILIES[Math.floor(Math.random() * FAMILIES.length)];
}

function _resolvedThemeMode(){
  // The theme module sets `data-theme` on <html> to either "light"
  // or "dark" (the resolved value, never "auto"). If the attribute
  // is missing we fall back to dark — the original design palette.
  const v = document.documentElement.getAttribute('data-theme');
  return v === 'light' ? 'light' : 'dark';
}

function _logoSrc(family, themeMode){
  return `/static/img/logos/logo-${family}-${themeMode}.svg`;
}

function _applyLogoAsset(){
  const img = document.getElementById(HERO_ID);
  if (!img) return;
  if (!_chosenFamily) {
    _chosenFamily = _pickFamily();
    img.dataset.brandFamily = _chosenFamily;
  }
  const themeMode = _resolvedThemeMode();
  img.src = _logoSrc(_chosenFamily, themeMode);
  img.dataset.brandThemeMode = themeMode;
}

// Run as soon as the DOM has the hero element in place. main.js
// imports this module after settings-collapse / sidebar / dock so
// by then the partials have already been rendered server-side and
// the <img id="heroBrandLogo"> is in the DOM.
_applyLogoAsset();

// Subscribe to theme changes — swap the src in place without
// rerolling the family. Listener stays passive; no cleanup needed
// because the module instance is tied to the page lifetime.
window.addEventListener('tamspy:theme', _applyLogoAsset);

// MutationObserver on <html data-theme> as a defensive backup in
// case some legacy code path flips data-theme without firing the
// event (e.g. a future bookmarklet). Cheap — one observer, one attr.
new MutationObserver((muts) => {
  for (const m of muts) {
    if (m.attributeName === 'data-theme') {
      _applyLogoAsset();
      return;
    }
  }
}).observe(document.documentElement, { attributes: true });
