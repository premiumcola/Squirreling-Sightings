// ─── mediaview/live-chrome-budget.js ───────────────────────────────────────
// Measures the live shell's FIXED chrome — title bar + control row +
// legend band + playbar, plus the column gaps between every row — and
// publishes it on the shell root as `--mv-live-chrome`.
//
// Two rules consume it, and both used to subtract a hard-coded 230 px:
//
//   * the desktop grid sizes its left column so a 16:9 stage still fits
//     the height that is left after the chrome. Under-count the chrome
//     and the left column over-subscribes the 100dvh row track — and
//     #lightboxInner is `overflow: hidden !important` in this mode, so
//     what falls off the bottom (the playbar) is simply gone.
//   * the stacked column caps the stage against the same number so the
//     panels below it cannot be squeezed to nothing.
//
// 230 px was already wrong the day it was written: the control row had
// just grown the telemetry cost line and the legend band had just been
// mounted inline, together about 70 px. And no constant can be right for
// the playbar, which is content-sized — the swimlane is 44 px per lane,
// so it grows and shrinks with the number of tracks on screen. Measure.

// First-paint value, before the observer has run once. Deliberately on
// the generous side: over-stating the chrome shrinks the picture a
// little, under-stating it clips a control off the bottom of the window.
export const MV_CHROME_FALLBACK_PX = 300;

// The rows that are fixed chrome. The stage is the elastic one (it is
// what the budget is being computed FOR) and the panels take the rest.
const _CHROME_SLOTS = ['titlebar', 'controls', 'legendband', 'playbar'];

/**
 * Chrome height for a set of measured row heights.
 *
 * Pure so the arithmetic can be reasoned about without a layout engine.
 * Rows that measured 0 are dropped (`display: none` in compact mode, or
 * an `:empty` band) and stop paying for a gap; the gap count is one more
 * than the number of chrome rows because the stage sits between two of
 * them and the panels follow the last.
 *
 * @param {number[]} rowHeights  measured heights in px
 * @param {number} gapPx         the shell's row-gap
 * @returns {number} chrome height in px
 */
export function mvChromeBudgetPx(rowHeights, gapPx) {
  const rows = (rowHeights || []).filter((h) => Number.isFinite(h) && h > 0);
  if (!rows.length) return MV_CHROME_FALLBACK_PX;
  const gap = Math.max(0, Number(gapPx) || 0);
  const sum = rows.reduce((a, b) => a + b, 0);
  return Math.round(sum + gap * (rows.length + 1));
}

/**
 * Keep `--mv-live-chrome` on ``root`` in step with what the chrome rows
 * actually measure. Returns a teardown.
 */
export function observeLiveChromeBudget(root) {
  if (!root) return () => {};
  const els = _CHROME_SLOTS.map((n) => root.querySelector(`[data-slot="${n}"]`)).filter(Boolean);
  const apply = () => {
    const gap = parseFloat(window.getComputedStyle(root).rowGap) || 0;
    const px = mvChromeBudgetPx(
      els.map((el) => el.getBoundingClientRect().height),
      gap,
    );
    root.style.setProperty('--mv-live-chrome', `${px}px`);
  };
  apply();
  if (typeof ResizeObserver === 'undefined') return () => {};
  const ro = new ResizeObserver(apply);
  for (const el of els) ro.observe(el);
  return () => ro.disconnect();
}
