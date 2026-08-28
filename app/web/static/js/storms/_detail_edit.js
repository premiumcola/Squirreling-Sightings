// ─── storms/_detail_edit.js ────────────────────────────────────────────────
// Benennen & Klassifizieren — the three editors in the detail header.
// Split out of _detail.js at the pre-declared seam so neither file
// drifts toward the 400-line ceiling.
//
// All three write through ONE PATCH endpoint and all three are
// optimistic: the UI updates immediately, and a failed write reverts the
// record and toasts. The record the route returns — inside its
// `{ok, episode}` envelope — is merged back in, so the UI reconciles
// against the server's own view (trimmed strings, rejected values)
// rather than assuming its write landed verbatim.

import { esc } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { STORM_CLASS_ORDER } from './_state.js';
import { classMeta, effectiveClass, episodeTitle, fmtIntensity } from './_helpers.js';
import { patchEpisode } from './_api.js';

// Mirrors USER_NAME_MAX in app/app/weather_episodes/_consts.py. A lower
// value here would silently cap what the server accepts; a higher one
// would let the operator type a name the PATCH then rejects.
const NAME_MAX = 120;

const PENCIL =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';

// Class strip. The detector's verdict is shown by the SAME control, not
// a second one: with user_class === null the chip matching auto_class
// renders in the "auto" state (tinted fill plus a small `auto` marker).
// Once the operator picks, that chip goes fully selected and the auto
// fact moves to a muted footnote. One control, two facts, zero
// duplication.
function _classHtml(ep) {
  const eff = effectiveClass(ep);
  const picked = ep.user_class || null;
  const chips = STORM_CLASS_ORDER.map((c) => {
    const m = classMeta(c);
    const isSel = picked === c;
    const isAuto = !picked && ep.auto_class === c;
    const state = isSel ? ' is-sel' : isAuto ? ' is-auto' : '';
    const mark = isAuto ? '<span class="st-chip-auto">auto</span>' : '';
    return `<button type="button" class="st-cchip${state}" data-class="${esc(c)}" style="--cc:${m.color}" aria-pressed="${isSel}" title="${esc(m.de)}">
        <span class="st-cchip-ic" aria-hidden="true">${m.icon}</span><span class="st-cchip-lbl">${esc(m.de)}</span>${mark}
      </button>`;
  }).join('');
  const foot = picked
    ? `<div class="st-auto-note">Automatisch erkannt: ${esc(classMeta(ep.auto_class).de)}</div>`
    : '';
  return `<div class="st-cstrip" role="group" aria-label="Klasse">${chips}</div>${foot}
    <div class="st-eff" hidden>${esc(eff || '')}</div>`;
}

function _noteHtml(ep) {
  const has = !!(ep.user_note && String(ep.user_note).trim());
  const label = has ? 'Notiz' : 'Notiz hinzufügen';
  const body = has ? `<div class="st-note-txt">${esc(ep.user_note)}</div>` : '';
  return `<div class="st-note" data-open="0">
      <button type="button" class="st-note-row" aria-expanded="false">
        <span class="st-note-lbl">${label}</span>
      </button>
      ${body}
      <textarea class="st-note-input" rows="3" maxlength="400" hidden placeholder="Notiz zu diesem Gewitter">${esc(ep.user_note || '')}</textarea>
    </div>`;
}

/** Header markup: name row, intensity, class strip, note. */
export function detailHeadHtml(ep) {
  const m = classMeta(effectiveClass(ep));
  return `<div class="st-dhead">
      <div class="st-name-row" role="button" tabindex="0" aria-label="Namen bearbeiten">
        <span class="st-name" style="--cc:${m.color}">${esc(episodeTitle(ep))}</span>
        <span class="st-name-pen" aria-hidden="true">${PENCIL}</span>
      </div>
      <input class="st-name-input" type="text" inputmode="text" enterkeyhint="done" maxlength="${NAME_MAX}" hidden placeholder="${esc(episodeTitle({ ...ep, user_name: null }))}" value="${esc(ep.user_name || '')}"/>
      <div class="st-dmeta">Intensität ${esc(fmtIntensity(ep.intensity))}</div>
      ${_classHtml(ep)}
      ${_noteHtml(ep)}
    </div>`;
}

/**
 * The record out of a PATCH response, or null.
 *
 * The route answers `{"ok": true, "episode": rec}` — reading `.id` off
 * the envelope finds nothing, so the reconcile step never ran and every
 * server-side normalisation was silently discarded. A bare record is
 * accepted too, so the merge survives an envelope change either way.
 */
export function patchedRecord(response) {
  if (!response || typeof response !== 'object') return null;
  const rec =
    response.episode && typeof response.episode === 'object' ? response.episode : response;
  return typeof rec.id === 'string' && rec.id ? rec : null;
}

// One write path for all three editors.
async function _save(ep, patch, rerender) {
  const before = { ...ep };
  Object.assign(ep, patch);
  rerender();
  try {
    const fresh = patchedRecord(await patchEpisode(ep.id, patch));
    if (fresh) {
      Object.assign(ep, fresh);
      rerender();
    }
  } catch {
    Object.assign(ep, before);
    rerender();
    showToast('Änderung konnte nicht gespeichert werden', 'error');
  }
}

function _bindName(host, ep, rerender) {
  const row = host.querySelector('.st-name-row');
  const input = host.querySelector('.st-name-input');
  if (!row || !input) return;
  const open = () => {
    row.hidden = true;
    input.hidden = false;
    input.focus();
    input.select();
  };
  // Commit on Enter AND on blur — no separate save button. A save button
  // next to a single field on a phone is a second 44 px target for
  // nothing. An empty value clears user_name back to the auto title.
  const commit = () => {
    if (input.hidden) return;
    input.hidden = true;
    row.hidden = false;
    const val = input.value.trim();
    const next = val || null;
    if (next === (ep.user_name || null)) {
      rerender();
      return;
    }
    _save(ep, { user_name: next }, rerender);
  };
  row.addEventListener('click', open);
  row.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      open();
    }
  });
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      input.blur();
    }
  });
}

function _bindClass(host, ep, rerender) {
  host.querySelectorAll('.st-cchip').forEach((chip) =>
    chip.addEventListener('click', () => {
      const c = chip.dataset.class;
      // Tapping the already-selected chip clears user_class back to null
      // and returns the strip to its auto state.
      _save(ep, { user_class: ep.user_class === c ? null : c }, rerender);
    }),
  );
}

function _bindNote(host, ep, rerender) {
  const wrap = host.querySelector('.st-note');
  const row = host.querySelector('.st-note-row');
  const ta = host.querySelector('.st-note-input');
  if (!wrap || !row || !ta) return;
  row.addEventListener('click', () => {
    const open = wrap.dataset.open === '1';
    wrap.dataset.open = open ? '0' : '1';
    ta.hidden = open;
    row.setAttribute('aria-expanded', open ? 'false' : 'true');
    if (!open) ta.focus();
  });
  // Autosave on blur.
  ta.addEventListener('blur', () => {
    const val = ta.value.trim();
    const next = val || null;
    if (next === (ep.user_note || null)) return;
    _save(ep, { user_note: next }, rerender);
  });
}

export function bindDetailHead(host, ep, rerender) {
  _bindName(host, ep, rerender);
  _bindClass(host, ep, rerender);
  _bindNote(host, ep, rerender);
}
