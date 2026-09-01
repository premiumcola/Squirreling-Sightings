// ─── weather/_card-style.js ─────────────────────────────────────────────
// The two inline-style strings every Mediathek-style event card's
// bottom-left date/time stack uses, copied verbatim (once) from
// mediaCardHTML() in mediathek/orchestration.js so badge font / blur /
// radius match the Library cards 1:1 without re-exporting private
// mediathek constants. Split out of weather/_feed.js into its own leaf
// module (no imports of its own) so both `_feed.js` and
// `_episode-footage-card.js` can import it without the two forming a
// cycle — `_feed.js` dispatches to `_episode-footage-card.js` for the
// footage-primary shell, and that shell needs these same two strings
// for its own corner badges.
export const _WS_BADGE_STYLE =
  'font-size:10px;font-weight:700;color:#e2e8f0;background:rgba(0,0,0,.68);backdrop-filter:blur(3px);padding:2px 6px;border-radius:4px;line-height:1.45;white-space:nowrap';
export const _WS_SUB_BADGE_BASE =
  'font-size:10px;background:none;backdrop-filter:blur(3px);padding:0 6px;border-radius:4px;line-height:1.45;white-space:nowrap;margin-top:1px;opacity:0.85';
