// ─── identities/_faces.js ──────────────────────────────────────────────────
// Die noch unsortierten Gesichter als Raster, dazu die Leiste, mit der man
// eine Auswahl auf einen Namen legt.
//
// RASTER, NICHT EINS NACH DEM ANDEREN. Der Vorgänger dieser Ansicht war ein
// Blättern: ein Portrait groß, eine Reihe Namen, weiter. Das ist die
// richtige Form, wenn zu jedem Bild eine eigene Entscheidung gehört — hier
// gehört sie das gerade nicht. Dieselbe Person läuft an einem Nachmittag
// fünfmal durchs Bild, und die fünf Kacheln nebeneinander zu sehen und in
// einem Griff zu benennen ist der ganze Punkt („Gruppierung").
//
// DER VORSCHLAG IST EIN VORSCHLAG. Er kommt aus einem Bildähnlichkeits-
// Vergleich, nicht aus einer Gesichtserkennung — er trifft gut, solange
// Kleidung, Ort und Tageszeit ähnlich sind, und daneben, wenn nicht.
// Deshalb steht er als Frage auf der Kachel und nicht als Tatsache.
import { esc } from '../core/dom.js';

/** PURE: die Beschriftung des Vorschlags-Abzeichens, oder ''. */
export function suggestLabel(row) {
  const hint = row && row.suggest;
  if (!hint || !hint.name) return '';
  return hint.confident ? `${hint.name}?` : `${hint.name} ?`;
}

/** PURE: die ausgewählten Zeilen, in der Reihenfolge des Rasters. */
export function selectionItems(items, selected) {
  return (items || []).filter((it) => selected.has(it.relpath));
}

/** PURE: der Name, den alle ausgewählten Kacheln vorschlagen — sonst ''.
 *  Sind sich die Vorschläge einig, gehört dieser Name vorn in die Leiste. */
export function agreedSuggestion(rows) {
  const names = new Set((rows || []).map((r) => (r.suggest && r.suggest.name) || ''));
  return names.size === 1 && !names.has('') ? [...names][0] : '';
}

/** PURE: wie viele Kacheln ein sicherer Vorschlag trägt. */
export function confidentCount(items) {
  return (items || []).filter((it) => it.suggest && it.suggest.confident).length;
}

function _tile(row, selected) {
  const hint = suggestLabel(row);
  const when = String(row.time || '')
    .replace('T', ' ')
    .slice(0, 16);
  return (
    `<button type="button" class="idy-face" data-relpath="${esc(row.relpath || '')}" ` +
    `aria-pressed="${selected.has(row.relpath) ? 'true' : 'false'}" title="${esc(when)}">` +
    `<img src="${esc(row.url || '')}" alt="Personen-Ausschnitt" loading="lazy">` +
    (hint ? `<span class="idy-hint">${esc(hint)}</span>` : '') +
    `<span class="idy-check" aria-hidden="true"></span>` +
    `</button>`
  );
}

/** Das Raster der unbenannten Gesichter. */
export function facesHtml(items, selected) {
  if (!items || !items.length) {
    return (
      `<div class="idy-empty">Keine unsortierten Gesichter. „Gesichter suchen" geht die ` +
      `Aufnahmen durch und legt neue hier ab.</div>`
    );
  }
  return `<div class="idy-grid">${items.map((it) => _tile(it, selected)).join('')}</div>`;
}

/** Die Zuordnungs-Leiste. Erscheint erst, wenn etwas ausgewählt ist —
 *  vorher gibt es nichts zu entscheiden und sie nähme nur Platz weg. */
export function assignBarHtml(count, names, agreed) {
  if (!count) return '';
  const ordered = agreed ? [agreed, ...names.filter((n) => n !== agreed)] : names;
  return (
    `<div class="idy-bar">` +
    `<div class="idy-bar-hd"><span class="idy-bar-n">${count} ausgewählt</span>` +
    `<button type="button" class="idy-bar-clear" data-idy="unselect">Auswahl aufheben</button>` +
    `</div>` +
    `<div class="idy-chips">` +
    ordered
      .map(
        (n, i) =>
          `<button type="button" class="idy-chip${i === 0 && agreed ? ' is-hint' : ''}" ` +
          `data-idy="assign" data-name="${esc(n)}">${esc(n)}</button>`,
      )
      .join('') +
    `</div>` +
    `<form class="idy-new"><input type="text" class="idy-input" placeholder="Neue Person…" ` +
    `aria-label="Neue Person" autocomplete="off">` +
    `<button type="submit" class="idy-add">Zuordnen</button></form>` +
    // „Bekannt, aber ohne Namensnennung." Eine eigene Zeile, weil es
    // kein weiterer Namensvorschlag ist, sondern die Entscheidung, KEINEN
    // Namen zu vergeben. Der Schlüssel („Bekannt 3") kommt vom Server;
    // er dient nur dazu, zwei unbenannte Personen auseinanderzuhalten.
    `<button type="button" class="idy-anon" data-idy="assign-anon">` +
    `+ Bekannt, ohne Namen</button>` +
    `</div>`
  );
}
