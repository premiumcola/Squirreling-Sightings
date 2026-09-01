// ─── core/scroll-anchor.js ──────────────────────────────────────────────────
// Keeps one element's on-screen (viewport) position stable across a DOM
// mutation that changes page layout elsewhere — typically a sibling
// re-rendering at a wildly different height. Without this, the browser's
// scroll position (an absolute pixel offset) doesn't move just because the
// content underneath it did: a section above the viewport shrinking by a
// few thousand pixels silently drags everything below it upward while
// scrollY stays put, and the operator can end up scrolled far past where
// they were looking — sometimes past the end of the (now much shorter)
// page, landing in a completely unrelated section further down.
//
// Root-caused against the Wetterdaten-chart's drag-zoom: dragging a
// selection on the chart and releasing (weather/stats.js's
// onWeatherChartRangeSelect) re-renders #libraryGrid to the narrowed time
// window, usually a small fraction of the default page's item count.
// #libraryBlock sits above #weatherStatsBlock in the DOM, so that shrink
// pulls the chart the operator is actively dragging on (and everything
// below it, including the unrelated #achievements/"Sichtungen" section
// next in the page) sharply upward — landing the viewport somewhere in
// that unrelated section. A general, reusable fix (rather than a one-off
// scrollIntoView bolted onto that single call site) so any future
// call site with the same shape — something above the viewport
// re-rendering while the operator's attention is below it — gets the same
// protection for free.
//
// `mutate` may be sync or async — anything awaitable works, since the
// second measurement only needs to run after the DOM update has landed.
// `scrollTarget` defaults to the global `window` — resolved lazily
// (rather than as a bare default-parameter value) so importing this leaf
// module never throws in a non-browser context (e.g. this repo's plain
// `node --test` harness, which has no `window` global at all).
export async function withScrollAnchor(anchorEl, mutate, scrollTarget) {
  const target = scrollTarget || (typeof window !== 'undefined' ? window : null);
  if (!anchorEl || typeof anchorEl.getBoundingClientRect !== 'function') {
    await mutate();
    return;
  }
  const before = anchorEl.getBoundingClientRect().top;
  await mutate();
  const after = anchorEl.getBoundingClientRect().top;
  const delta = after - before;
  if (delta && target) target.scrollBy(0, delta);
}
