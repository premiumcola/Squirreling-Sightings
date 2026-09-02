// ─── camedit/_profile-lists.js ──────────────────────────────────────────
// The three read-only side panels on the camera-settings tab — the cat
// list, the person list and the Telegram audit log — as pure string
// builders plus the one fetch helper they share.
//
// Split out of camedit/index.js so this half is importable under the
// repo's plain-node test harness: index.js binds listeners at MODULE
// LOAD time (`byId('reloadConfigBtn').onclick = ...`, which throws
// outright when that element is absent), so nothing in it can be
// imported by a test. Every import here (core/dom.js, core/api.js) is
// leaf-clean — no window writes, no listeners — the same property
// library/_filter-chips.js was split out for.
import { esc } from '../core/dom.js';
import { j } from '../core/api.js';

/**
 * GET one side-panel list off `url`, reading `key` out of the response,
 * and degrade to `[]` on ANY failure instead of propagating.
 *
 * The propagation is the whole point. `live-update.js::loadAll` awaits
 * these three panels in the middle of its boot sequence and `main.js`
 * kicks it off as a bare `loadAll().then(...)` — no `.catch`. A throw
 * here therefore skips every remaining boot step (hydrateSettings, the
 * Telegram panel, the push UI, the weather panels, initLibraryPage,
 * startPreviewRefresh) and the `.then` that starts the 3 s live poll.
 * Three read-only name lists must never hold that power, so the failure
 * stops here, at the panel that owns it: the panel goes empty, the
 * dashboard boots. The console line is what keeps this from being a
 * silent swallow — a missing panel stays diagnosable.
 */
export async function optionalList(url, key) {
  try {
    const r = await j(url);
    const list = r?.[key];
    if (Array.isArray(list)) return list;
    console.warn('[camedit] %s carried no %s array', url, key);
  } catch (err) {
    console.warn('[camedit] %s unavailable: %s', url, err?.message || err);
  }
  return [];
}

/** The cat-identity profile list — names only. */
export function catListHTML(profiles) {
  return (
    (profiles || [])
      .map((p) => `<div style="padding:3px 0;font-size:13px">${esc(p.name)}</div>`)
      .join('') || '<span class="muted small">—</span>'
  );
}

/** The person-identity profile list — names plus a whitelist marker. */
export function personListHTML(profiles) {
  return (
    (profiles || [])
      .map(
        (p) =>
          `<div style="padding:3px 0;font-size:13px">${esc(p.name)}${p.whitelisted ? ' <span class="muted small">(Whitelist)</span>' : ''}</div>`,
      )
      .join('') || '<span class="muted small">—</span>'
  );
}

/** The Telegram action audit log — most recent first, as the route
 * already orders them. */
export function auditListHTML(items) {
  return (
    (items || [])
      .map(
        (a) =>
          `<div class="audit-item"><strong>${esc(a.action)}</strong><div class="small">${esc(a.time)}${a.camera_id ? ` · ${esc(a.camera_id)}` : ''}</div></div>`,
      )
      .join('') || '<div class="audit-item">Noch keine Telegram-Aktionen.</div>'
  );
}
