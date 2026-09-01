// ─── netz/_class_rows.js ───────────────────────────────────────────────────
// The per-class Meldeschwelle — one axis per detection class, ON THE SAME
// NET as the camera-wide settings.
//
// Three shapes in three days, and the reasons matter more than the code:
//
//   1. its own SECOND radar. Rejected — "ich will nicht zwei Netze". Two
//      charts with different geometries on one page read as a bug.
//   2. a read-only text line. That went one step too far: it deleted the
//      only control in the whole GUI able to move a class's alert
//      threshold, leaving `patchAxes` with zero callers while
//      `PATCH /api/netz/<cam>/axes` stayed live. The operator found it the
//      way anyone would — they went looking for the person threshold on a
//      camera that never alerted, and it wasn't there.
//   3. editable rows under the radar. Reachable, but a second control
//      surface for a value that belongs to the net.
//
// Now: spokes on the ONE net, in their own colour group ("Meldung", see
// TUNE_GROUPS). The radial scale is E, exactly as _mapping.js defines it
// — outward = larger E = more sensitive = reports earlier — and the label
// prints the resulting Meldeschwelle in percent, so the operator never
// has to think in E. The percentage goes through pushFor(), the
// bit-for-bit mirror of app/app/thresholds/_apply.py, never through a
// second formula.
//
// The filename is unchanged on purpose. Renaming it (and
// test_netz_class_rows.py with it) would be a wide, purely cosmetic diff
// for zero behavioural gain — internal `netz*` identifiers stay `netz*`
// throughout this package even where the user-visible text says
// "Erkennungsprofil".
//
// THE SAVE PATH IS THE OTHER HALF OF THIS FILE, and it is NOT the radar's.
// Camera-wide axes stage and commit through `patchTuning`; these commit on
// release through `patchAxes`, which also writes the net-archive record.
// One drag, one write, one history entry.

import { showToast } from '../core/toast.js';
import { patchAxes, resetAxis } from './_api.js';
import { E_FACTORY, E_MAX, E_MIN, clampE, pushFor } from './_mapping.js';
import { TUNE_GROUPS } from './_settings_axes.js';
import { applyNetState } from './_state.js';
import { labelDe, pct } from './_helpers.js';

/** Namespace for a class axis key, so `person` can never collide with a
 *  camera-tuning field name in `netzState.tuneAxes` or in a drag lookup. */
export const CLASS_AXIS_PREFIX = 'cls:';

/** Colour for a class whose Meldung is switched off entirely. */
const OFF_COLOR = '#64748b';

const OFF_HINT =
  'Meldung für diese Klasse ist aus (Klassen-Matrix der Kamera oder globaler Schalter). ' +
  'Die Schwelle wird nicht abgefragt — erst einschalten, dann ziehen.';

const HINT =
  'Ab welcher Sicherheit diese Klasse eine Meldung auslöst · innen = streng, meldet nur ' +
  'Sicheres, außen = empfindlich, meldet früher. Wird sofort gespeichert und im Verlauf ' +
  'festgehalten.';

export function isClassAxisKey(key) {
  return String(key || '').startsWith(CLASS_AXIS_PREFIX);
}

export function classLabelOf(key) {
  return String(key || '').slice(CLASS_AXIS_PREFIX.length);
}

/** A TUNE_SPECS-shaped spec for a class axis.
 *
 *  Shaped that way deliberately: the drag layer, the pill and the hint
 *  toast then need one branch (`TUNE_SPECS[key] || classAxisSpec(key)`)
 *  instead of a parallel pointer implementation. `raw` IS E here — min 0,
 *  max 100, not inverted — so tuneRawFromE returns the dragged E
 *  unchanged and only `fmt` differs from a settings axis. */
export function classAxisSpec(key) {
  if (!isClassAxisKey(key)) return null;
  const label = classLabelOf(key);
  return {
    key,
    group: 'meldung',
    label: labelDe(label),
    min: E_MIN,
    max: E_MAX,
    default: E_FACTORY,
    invert: false,
    fmt: (v) => pct(pushFor(label, clampE(v))),
    hint: HINT,
    // Shown in the drag pill: these axes do not join the staging bar.
    note: 'speichert sofort',
  };
}

/** The hint for an axis, lock-aware. A greyed control that cannot say why
 *  it is greyed is worse than no control. */
export function classAxisHint(axis) {
  return axis && axis.locked ? OFF_HINT : HINT;
}

/** One radar row per class this camera has an axis for, appended after
 *  the camera-wide axes so each colour group stays a contiguous arc. */
export function buildClassAxes(st) {
  return ((st && st.axes) || []).map((a) => {
    const label = String(a.label || '');
    const e = clampE(Number(a.E));
    // push_enabled=false means the class never alerts at all. The spoke
    // stays — a missing spoke would hide the fact that the camera is mute
    // for that class — but it is drawn grey and cannot be dragged, and it
    // reads "aus" instead of a threshold nothing consults.
    const off = a.push_enabled === false;
    return {
      key: CLASS_AXIS_PREFIX + label,
      label: labelDe(label),
      raw: e,
      E: e,
      defaultE: E_FACTORY,
      group: 'meldung',
      color: off ? OFF_COLOR : TUNE_GROUPS.meldung.color,
      locked: off,
      provenance: a.provenance || 'werk',
      display: off ? 'aus' : pct(Number.isFinite(Number(a.push)) ? a.push : pushFor(label, e)),
    };
  });
}

/**
 * Commit ONE class axis. Called on pointerup, not on every move, so a
 * drag is one request and one archive entry.
 *
 * `camId` comes from the card the pointer went down on — with every
 * camera's net on screen at once, a module-level "current camera" is how
 * a drag on one camera writes to another.
 */
export async function saveClassAxis(camId, key, e, onRepaint) {
  const label = classLabelOf(key);
  if (!camId || !label) return false;
  const wanted = clampE(e);
  const res = await patchAxes(camId, { [label]: wanted });
  if (!res || !res.ok) {
    showToast('Konnte nicht gespeichert werden: ' + ((res && res.error) || '—'), 'error');
    if (typeof onRepaint === 'function') onRepaint();
    return false;
  }
  // The server clamps `person` on a security camera up to the safety
  // floor unless the blocking dialog was shown. Report the value that
  // ACTUALLY landed, never the one that was dragged — and take the whole
  // returned state, which has already re-resolved the ladder.
  applyNetState(camId, res.state);
  const written = (res.written || {})[label] || {};
  const landedE = Number.isFinite(Number(written.E)) ? Number(written.E) : wanted;
  const landedPush = Number.isFinite(Number(written.push))
    ? Number(written.push)
    : pushFor(label, landedE);
  const de = labelDe(label);
  if (written.clamped) {
    showToast(
      `${de}: auf ${pct(landedPush)} begrenzt — unter dieser Schwelle würde die Kamera ` +
        `Personen übersehen.`,
      'warn',
      { lifetime: 7000 },
    );
  } else {
    showToast(`${de} meldet jetzt ab ${pct(landedPush)}.`, 'success');
  }
  if (typeof onRepaint === 'function') onRepaint();
  return true;
}

/** Long-press on a class vertex: E = 50 and unpinned, through the route
 *  that already does exactly that. `patchAxes(…, 50)` would look the same
 *  and leave the axis pinned, which is not the same thing at all. */
export async function resetClassAxis(camId, key) {
  const label = classLabelOf(key);
  const res = await resetAxis(camId, label);
  if (!res || !res.ok) {
    showToast('Zurücksetzen fehlgeschlagen.', 'error');
    return false;
  }
  applyNetState(camId, res.state);
  showToast(`${labelDe(label)} steht wieder auf Werk.`, 'success');
  return true;
}
