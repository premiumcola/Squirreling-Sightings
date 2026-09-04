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

// A URL safe to drop inside a CSS `url("…")` that itself sits in an
// HTML style attribute — two nested contexts, so an allowlist rather
// than an escape table. `esc` alone is not enough here: it leaves
// backslashes and parentheses untouched, and both are meaningful to the
// CSS tokenizer, which would let a remote-supplied string close the
// url() and start a declaration of its own.
//
// Only absolute http(s) and root-relative paths pass, and only when
// they contain nothing that can terminate a CSS string or function.
// Anything else returns '' — a missing background, never an injection.
// The survivor still goes through `esc` for the attribute layer.
export const cssUrl = (raw) => {
  const s = String(raw ?? '');
  if (!/^(?:https?:\/\/|\/)[^\s'"();\\<>]*$/i.test(s)) return '';
  return esc(s);
};

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

// `#rrggbb` → `rgba(r,g,b,alpha)` for tinted chip / badge backgrounds.
// Lives next to safeHexColor because it is the same family of helper
// and now has two consumers in different modules (mediathek chips and
// the media-card chrome) — keeping it in one of them would have meant
// an import cycle or a second copy.
export const hexToRgba = (hex, alpha) => {
  const h = (hex || '').replace('#', '');
  if (h.length !== 6) return `rgba(147,197,253,${alpha})`;
  const r = Number.parseInt(h.slice(0, 2), 16);
  const g = Number.parseInt(h.slice(2, 4), 16);
  const b = Number.parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
};
