// ─── sichtungen/_dossier-placement.js ──────────────────────────────────────
// Wo der Art-Steckbrief im Kachelraster einrastet — und wie er eine
// Neuzeichnung des Rasters überlebt.
//
// Eigenes Modul, weil es eine eigene Sorge ist: `_achievements.js` malt
// Kacheln, das hier verschiebt EIN fremdes Element zwischen ihnen. Die
// beiden Fehler, die den Steckbrief am Handy unbrauchbar gemacht haben,
// standen genau an dieser Naht:
//
//   1. `#achievementsGrid.innerHTML = …` löscht jeden Nachfahren — und
//      nach dem ersten Öffnen IST das Panel einer. Der zweite Tipp auf
//      einen Vogel löschte damit den Knoten, jeder weitere Tipp fand
//      `byId('speciesDossierPanel')` leer und tat schlicht gar nichts:
//      „die anderen erkannten, da schiebt sich gar nix auf."
//
//   2. Die Zeile wurde aus einer SPALTENZAHL gerechnet. Unter 768 px ist
//      das Raster `repeat(12, 1fr)` und jede Kachel `grid-column: span 3`
//      (12-sichtungen.css) — gemessen werden also 12 Spuren, während vier
//      Kacheln in eine Zeile passen. Ein Vogel in Zeile fünf landete bei
//      `ceil(18/12)*12 = 24`, und der Steckbrief schob sich anderthalb
//      Zeilen zu tief auf.
//
// Die Lehre aus (2) ist dieselbe, die die Mediathek schon gezogen hat:
// das Layout fragen, nicht vorhersagen. Zwei Kacheln stehen genau dann in
// einer Zeile, wenn sie dasselbe `offsetTop` haben — unabhängig von
// Spurenzahl, Span und `grid-auto-flow: dense`.
import { byId } from '../core/dom.js';

const PANEL_ID = 'speciesDossierPanel';
const INROW_CLASS = 'sd-panel--inrow';

/** Wo das Panel steht, solange nichts offen ist. Beim ersten Verschieben
 *  festgehalten, damit es immer zurückkann. */
let _home = null;

/** PURE: die Kachel, die die Zeile NACH der aktiven beginnt.
 *
 *  `null` = die aktive Kachel steht in der letzten Zeile (ans Ende
 *  einfügen). `undefined` = die aktive Kachel ist gar nicht in der Liste,
 *  also nichts anfassen. Die beiden Fälle sind verschieden und dürfen
 *  nicht zusammenfallen: der eine heißt „ans Ende", der andere „Finger
 *  weg". */
export function cardAfterRowOf(cards, active) {
  const i = (cards || []).indexOf(active);
  if (i < 0) return undefined;
  const top = active.offsetTop;
  let last = i;
  for (let k = i + 1; k < cards.length; k++) {
    if (Math.abs(cards[k].offsetTop - top) > 1) break;
    last = k;
  }
  return cards[last + 1] || null;
}

function _remember(panel) {
  if (_home === null) {
    _home = { parent: panel.parentElement, next: panel.nextElementSibling };
  }
  return _home;
}

/** Das Panel dorthin zurücklegen, wo es hingehört, wenn nichts offen ist. */
export function sendDossierHome(panel) {
  const home = _remember(panel);
  panel.classList.remove(INROW_CLASS);
  if (home.parent && panel.parentElement !== home.parent) {
    home.parent.insertBefore(panel, home.next);
  }
}

/** VOR jeder Neuzeichnung des Rasters aufrufen: holt das Panel aus dem
 *  Raster heraus, damit `innerHTML = …` es nicht mitlöscht. */
export function liftDossierOutOfGrid() {
  const panel = byId(PANEL_ID);
  if (panel) sendDossierHome(panel);
}

/** NACH der Neuzeichnung aufrufen: schiebt das Panel unter die Zeile der
 *  aktiven Kachel — oder nach Hause, wenn keine aktiv ist. */
export function placeDossierUnderRow() {
  const panel = byId(PANEL_ID);
  if (!panel) return;
  _remember(panel);
  const grid = byId('achievementsGrid')?.querySelector('.ach-cards-grid');
  const active = grid?.querySelector('.ach-card--active');
  if (!grid || !active || panel.hidden) {
    sendDossierHome(panel);
    return;
  }
  const cards = [...grid.children].filter((el) => el.classList.contains('ach-card'));
  const before = cardAfterRowOf(cards, active);
  if (before === undefined) return;
  grid.insertBefore(panel, before);
  panel.classList.add(INROW_CLASS);
}

/** Nur für Tests: den gemerkten Heimatplatz vergessen. */
export function _forgetDossierHome() {
  _home = null;
}
