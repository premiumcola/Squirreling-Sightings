// ─── core/dom.js ───────────────────────────────────────────────────────────
// Minimal DOM helpers used everywhere. Kept tiny: byId is the most-
// hit function in the codebase (>2000 references) and esc is the
// HTML-escape used in every innerHTML template string.
// getElementById, NOT querySelector('#id'): some callers pass IDs
// containing CSS special chars (`:` in cam-ids, `.` in build hashes)
// which break a `#`-prefixed selector but are valid arguments to
// getElementById. eslint-disable for the unicorn rule on this one
// line is intentional.
// eslint-disable-next-line unicorn/prefer-query-selector
export const byId = (id) => document.getElementById(id);

// Escape a string for safe insertion into an innerHTML template.
// Handles the OWASP-recommended five characters; the `??` falls back
// to '' on null/undefined so we never write the literal "null" into
// markup.
export const esc = (s) =>
  String(s ?? '').replaceAll(
    /[&<>"']/g,
    (m) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      })[m],
  );

// Convenience query helpers — used sparingly today but normalised
// here so any future migration off byId-everywhere can land without
// every callsite chasing document.querySelector boilerplate.
export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// Validate a hex colour string so it can be safely interpolated into
// inline `style="color:..."` or inline JS attribute strings. Rejects
// anything that isn't a `#RGB`, `#RRGGBB`, or `#RRGGBBAA` literal —
// in particular, blocks the camera-color XSS vector where a user-
// chosen colour like `'); evil(); //` would break out of an inline
// `style.color='...'` JS string in a placeholder onerror handler.
// Returns the input on success or a neutral fallback (#a8a8a8) on
// failure so callsites never have to null-check.
export const safeHexColor = (raw, fallback = '#a8a8a8') => {
  if (typeof raw !== 'string') return fallback;
  return /^#[0-9a-f]{3,8}$/i.test(raw) ? raw : fallback;
};
