// ─── identities/_api.js ────────────────────────────────────────────────────
// Jeder Netzaufruf der Identitäten-Karte, einmal benannt. Die Karte selbst
// soll von Endpunkten nichts wissen — sie kennt nur Vorgänge: laden,
// zuordnen, umbenennen, vergessen.
import { j, apiPost, apiDelete } from '../core/api.js';

/** Personen, Katzen und die Zahl der noch unsortierten Gesichter. */
export const loadIdentities = () => j('/api/identities');

/** Die unbenannten Ausschnitte einer Seite, mit Namensvorschlag. */
export const loadUnnamedFaces = (limit = 60) =>
  j(`/api/person-crops?only_unnamed=1&suggest=1&limit=${limit}`);

/** Einen Schwung Ausschnitte unter einem Namen ablegen.
 *  `anonymous` ohne Namen heißt „bekannt, aber ohne Namensnennung" — den
 *  neutralen Schlüssel vergibt der Server. */
export const assignFaces = (name, items, { anonymous = false } = {}) =>
  apiPost('/api/person-crops/assign', { name, items, anonymous });

/** Einen Schwung Ausschnitte als „keine Person" ablegen. */
export const rejectFaces = (items, bucket) =>
  apiPost('/api/person-crops/reject', { items, bucket });

/** Die sicheren Vorschläge in einem Zug übernehmen. */
export const autoAssignFaces = () => apiPost('/api/person-crops/auto-assign', {});

/** Den Nachlauf anstoßen, der die Ausschnitte aus den Clips schneidet. */
export const sweepFaces = () => apiPost('/api/person-crops/sweep', {});

/** Den Namen von einem Ereignis nehmen. */
export const clearFace = (item) => apiPost('/api/person-crops/clear', item);

export const renamePerson = (name, to) =>
  apiPost(`/api/persons/${encodeURIComponent(name)}/rename`, { to });

export const setPersonFlags = (name, flags) =>
  apiPost(`/api/persons/${encodeURIComponent(name)}/flags`, flags);

export const deletePerson = (name) => apiDelete(`/api/persons/${encodeURIComponent(name)}`);
