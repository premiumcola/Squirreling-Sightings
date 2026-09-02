// ─── core/label-patch.js ───────────────────────────────────────────────────
// PURE. The server's answer to a label change → an event object that
// agrees with it.
//
// WHY IT LIVES IN core/. Two surfaces POST the same endpoint —
// mediaview/panels/labels.js (the bubble row) and vplayer/ (the
// correction sheet) — and both then have to make their copy of the event
// agree with the reply. That fan-out was written out inline in labels.js;
// a second copy in the player is exactly the parallel implementation
// CLAUDE.md forbids, so the rule moved here and both call it.
//
// WHY IT IS A PATCH AND NOT A RELOAD. `POST …/events/<id>/labels`
// (app/app/routes/events.py::api_event_labels) answers with
// `{ok, labels, top_label, cat_name, bird_species}` — four fields, not
// the event. That response exists FOR this: its own comment says the
// frontend needs cat_name and bird_species "to drop a stale identity
// chip without a full reload", because apply_label_change() clears them
// when their label leaves the set. So the authoritative values are
// already in hand and a re-fetch would only be a slower way to learn
// what the reply just said.
//
// THE FOUR FIELDS ARE NOT INTERCHANGEABLE. `labels` is the set the
// operator chose; `top_label` is the backend's own derivation from it
// (event_relabel.py::sync_top_label) and must never be recomputed on
// this side; `cat_name` / `bird_species` are identities the backend may
// just have CLEARED, which is why they are copied even when null — a
// missing-key test would keep a name the server no longer stands behind.

/**
 * PURE-ish: fold a label-save response into one cached event copy.
 *
 * Mutates `target` in place and returns it, because every caller holds
 * the object by reference — the open player's item, `lbState.item` and
 * the two grid caches are the same event seen from four places, and
 * replacing them would leave three of the four stale.
 *
 * Each field is copied only when the response actually carries it, so a
 * reply that predates one of them cannot blank a value it never spoke
 * about. `null` IS carrying it: a cleared identity is an answer.
 *
 * @param {object} target  a cached event object
 * @param {object} res     the endpoint's reply
 * @returns {object} the same `target`
 */
export function applyLabelPatch(target, res) {
  if (!target || !res || typeof res !== 'object') return target;
  // A fresh array per target: the same reply patches several caches, and
  // sharing one array between them would make a later edit to one of
  // them silently rewrite the others.
  if (Array.isArray(res.labels)) target.labels = [...res.labels];
  if ('top_label' in res) target.top_label = res.top_label;
  if ('cat_name' in res) target.cat_name = res.cat_name;
  if ('bird_species' in res) target.bird_species = res.bird_species;
  return target;
}
