// ─── vplayer/panels/_revision-chip.js ──────────────────────────────────────
// Which PROFILE the simulation is running — and the means to change it.
//
// The panel header promised three answers ("aktuelles Profil",
// "Werkseinstellung", "ein Stand aus dem Verlauf") and could only ever
// give the first: the Erkennungsnetz kept an archive of every net the
// operator ever had, and the simulation had no way to reach it.
//
// Two rules this file exists to keep:
//
//   · IT NEVER WRITES A SETTING. Choosing a revision sets one field on
//     the poll session, which becomes one query parameter, which the
//     backend resolves into a throwaway config for that tick. The
//     camera keeps running its own profile throughout. Restoring a net
//     onto a camera stays where it belongs, in the Erkennungsnetz.
//   · IT IS MOUNTED BY THE SIMULATION ONLY, on cfg.flags.canPickRevision.
//     The live view is the same panel code with the panel hidden, so a
//     chip that rendered on mode alone would eventually reach it.
//
// The chip states the ACTIVE revision rather than offering a verb: a
// diagnostic that does not say which profile produced the boxes on
// screen is the misreading this whole panel was built to end.

import { esc } from '../../core/dom.js';
import { S } from '../../mediaview/live-detect-state.js';
import { PLACEHOLDER } from '../_helpers.js';

/** The two revisions every camera has, whatever its archive holds. */
const CURRENT = 'current';

/** German for a revision's kind, for the ones the archive names. */
const KIND_DE = {
  current: 'Aktuelles Profil',
  factory: 'Werkseinstellung',
  frage: 'Frage',
  alarm: 'Alarm',
  netz_aenderung: 'Netz-Änderung',
};

/**
 * PURE: a revision's label for the picker.
 *
 * German labels are long and the chip is narrow, so the timestamp is
 * rendered short (day + time) and the class carries the rest. Both
 * halves wrap rather than clip — see the CSS note on .vp-pnl-revopt.
 *
 * @param {object} rev  one row of /api/camera/<id>/profile-revisions
 * @returns {string}
 */
export function revisionLabel(rev) {
  const r = rev || {};
  if (!r.ts) return KIND_DE[r.kind] || r.label || PLACEHOLDER;
  const kind = KIND_DE[r.kind] || r.kind || '';
  const when = _shortTs(r.ts);
  const what = r.label ? ` · ${r.label}` : '';
  return `${when} · ${kind}${what}`;
}

/** "30.08. 12:00" — enough to tell two revisions apart, no more. */
function _shortTs(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}. ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * PURE: which revision is active, given the list and the session value.
 *
 * An id the list no longer offers (the archive evicted it under
 * retention while the panel was open) resolves to null rather than to
 * "current" — the chip must not claim the live profile is running when
 * the backend is about to refuse the id.
 */
export function activeRevision(revisions, id) {
  const list = Array.isArray(revisions) ? revisions : [];
  const want = id || CURRENT;
  return list.find((r) => r && r.id === want) || null;
}

async function _fetchRevisions(camId) {
  if (!camId) return [];
  try {
    const r = await fetch(`/api/camera/${encodeURIComponent(camId)}/profile-revisions`, {
      cache: 'no-store',
    });
    if (!r.ok) return [];
    const data = await r.json();
    return Array.isArray(data?.revisions) ? data.revisions : [];
  } catch {
    return [];
  }
}

function _optionsHtml(revisions, activeId) {
  return revisions
    .map(
      (r) =>
        `<option value="${esc(r.id)}"${r.id === activeId ? ' selected' : ''}>` +
        `${esc(revisionLabel(r))}</option>`,
    )
    .join('');
}

/**
 * Render the revision picker into the panel head.
 *
 * A native <select> on purpose: it is the one control that is already a
 * 44 px target on iOS, already scrolls a long list inside the viewport,
 * and already reads the active value out to VoiceOver. A hand-rolled
 * popover would have to re-earn all three.
 *
 * @param {HTMLElement} host
 * @param {object} cfg   normalised config from _config.js
 * @returns {{teardown: () => void}|null}
 */
export function renderRevisionChip(host, cfg) {
  if (!host || !cfg?.flags?.canPickRevision) return null;
  const camId = cfg.item?.camera_id || null;
  let revisions = [];
  let alive = true;

  host.innerHTML =
    `<label class="vp-pnl-rev">` +
    `<span class="vp-pnl-rev-k">Profil</span>` +
    `<select class="vp-pnl-rev-sel" aria-label="Profil-Stand für die Simulation">` +
    `<option value="${CURRENT}">${esc(KIND_DE.current)}</option>` +
    `</select></label>`;
  const sel = host.querySelector('.vp-pnl-rev-sel');

  const onChange = () => {
    const id = sel.value || CURRENT;
    // The ONLY write this feature performs anywhere: one field on the
    // poll session. The next tick carries it as a query parameter.
    if (S.session) S.session.revision = id === CURRENT ? null : id;
  };
  sel.addEventListener('change', onChange);

  _fetchRevisions(camId).then((list) => {
    if (!alive) return;
    revisions = list;
    if (!revisions.length) return;
    const activeId = (S.session && S.session.revision) || CURRENT;
    sel.innerHTML = _optionsHtml(revisions, activeId);
  });

  return {
    teardown: () => {
      alive = false;
      sel.removeEventListener('change', onChange);
      // A revision must not outlive the panel that chose it: leaving it
      // on the session would keep every later simulation — and the
      // operator's mental model of "this is my camera" — on a profile
      // nothing on screen still names.
      if (S.session) S.session.revision = null;
      host.innerHTML = '';
    },
  };
}
