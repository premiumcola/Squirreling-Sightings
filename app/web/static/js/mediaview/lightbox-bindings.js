// ─── mediaview/lightbox-bindings.js ────────────────────────────────────────
// Pure descriptor table for the '?' shortcut-help overlay (keyboard.js).
// This is deliberately the ONLY place that lists "what a key does" as
// text — the ACTIVE/inactive predicates below read the exact same `ctx`
// fields (`videoActive`, `suppressed`) that keyboard.js's own dispatcher
// (_openLightboxShortcut / _arrowSeekOrNav / _spaceOrFullscreen /
// _transportV2Shortcut) branches on, built by the same _buildLightboxCtx()
// there. So a binding can never show as "active" here while doing nothing
// in the real dispatcher, or vice versa — same ctx, same conditions, two
// call sites instead of two independent lists that could drift apart.
//
// No DOM here (mirrors device-tier.js's pure/impure split) — keyboard.js
// builds ctx from the live DOM and passes the plain object in, so this
// file is trivially unit-testable without a browser.
import { TIER_FULL } from './device-tier.js';

// keys: the literal characters/labels shown in the overlay. label: short
// German description matching the rest of the lightbox UI's language.
// active(ctx): same boolean the dispatcher gates the real key on.
const _LIGHTBOX_BINDINGS = [
  { keys: ['Esc'], label: 'Schließen', active: () => true },
  {
    keys: ['←', '→'],
    label: 'Video: 5 s zurück / vor',
    active: (ctx) => !ctx.suppressed && ctx.videoActive,
  },
  {
    keys: ['←', '→'],
    label: 'Vorheriges / nächstes Element',
    active: (ctx) => !ctx.suppressed && !ctx.videoActive,
  },
  { keys: ['↑'], label: 'Behalten (bestätigen)', active: (ctx) => !ctx.suppressed },
  { keys: ['↓'], label: 'Löschen', active: (ctx) => !ctx.suppressed },
  { keys: ['Space'], label: 'Play / Pause', active: (ctx) => ctx.videoActive },
  { keys: ['F'], label: 'Vollbild', active: (ctx) => ctx.videoActive },
  { keys: [',', '.'], label: 'Frame zurück / vor', active: (ctx) => ctx.videoActive },
  { keys: ['<', '>'], label: 'Geschwindigkeit', active: (ctx) => ctx.videoActive },
  { keys: ['L'], label: 'Loop an/aus', active: (ctx) => ctx.videoActive },
  { keys: ['[', ']'], label: 'Vorherige / nächste Erkennung', active: (ctx) => ctx.videoActive },
  { keys: ['S'], label: 'Snapshot speichern', active: (ctx) => ctx.videoActive },
  { keys: ['?'], label: 'Diese Hilfe ein-/ausblenden', active: () => true },
];

/**
 * Filter the full table down to what actually does something in `ctx`.
 * @param {{videoActive: boolean, suppressed: boolean}} ctx
 * @returns {Array<{keys: string[], label: string}>}
 */
export function getActiveLightboxBindings(ctx) {
  return _LIGHTBOX_BINDINGS
    .filter((b) => b.active(ctx))
    .map(({ keys, label }) => ({
      keys,
      label,
    }));
}

/**
 * The help overlay is PC-only — gated on the device/pointer tier
 * (mediaview/device-tier.js), same axis Transport v2 and PiP already
 * read. 'compact' (touch / narrow) gets no '?' affordance at all.
 * @param {string|undefined} tier
 */
export function isShortcutHelpAvailable(tier) {
  return tier === TIER_FULL;
}
