// ─── mediathek/_qa-cause.js ────────────────────────────────────────────────
// PURE. Ein QA-Sidecar → der Satz, der sagt, WARUM.
//
// „bitte stell auch da, wieso Lossy wenn ich draufgeh … und wo das
// Problem ist, beziehungsweise müssen wir das Problem auch lösen?"
//
// Das Modal zeigte bisher `declared fps`, `effective fps`, `unique fps`
// und `dup ratio` — englische Fachbegriffe, die das SYMPTOM beschreiben.
// Die Duplikate sind aber nie die Ursache; sie sind das, was der Encoder
// tut, wenn ihm Material fehlt. An zwei Kameras derselben Anlage
// gemessen, beide rot, mit vollkommen verschiedenen Ursachen:
//
//   Nut Bar  1350 erwartet · 111 aufgenommen ·  11 verworfen → 58 % dup
//   Garten   1350 erwartet ·  40 aufgenommen · 121 verworfen → 77 % dup
//
// Bei der einen läuft die Aufnahme kaum, bei der anderen wirft der
// Bildprüfer drei Viertel wieder weg. Beide bekamen dasselbe rote
// „lossy" und dieselben vier fps-Zahlen — aus denen keiner der beiden
// Fälle herauszulesen war.
//
// Die Reihenfolge unten ist die Kausalkette rückwärts: erst gar nicht
// aufgenommen, dann aufgenommen und verworfen, dann genug Material und
// trotzdem gestreckt. Der erste Treffer gewinnt, weil das der Schritt
// ist, an dem die Kette zuerst reißt.

/** Die Prüfgründe des Bildprüfers, in Worten. */
export const REJECT_REASON_DE = {
  split_left_dead: 'linke Bildhälfte tot (Stream-Abriss)',
  bottom_strip_bright: 'heller Streifen am unteren Rand',
  horizontal_anomaly_band: 'waagerechtes Störband',
  macroblock_anomaly: 'Blockartefakte',
  grey_toned: 'grauer Schleier',
  too_dark: 'zu dunkel',
  duplicate: 'Bild doppelt',
};

/** Der auffälligste Grund als Wortpaar, oder null. */
function _topReason(reasons) {
  const list = Object.entries(reasons || {}).sort((a, b) => b[1] - a[1]);
  if (!list.length) return null;
  const [key, n] = list[0];
  return { key, n, text: REJECT_REASON_DE[key] || key };
}

/** Prozent als ganze Zahl, ohne NaN. */
function _pct(part, whole) {
  if (!(whole > 0)) return 0;
  return Math.round((part / whole) * 100);
}

/**
 * PURE: warum dieser Zeitraffer die Note hat, die er hat.
 *
 * @param {object|null} qa  das Sidecar, wie /api/timelapse/…/qa es liefert
 * @returns {{kind: string, headline: string, detail: string,
 *            lever: string, numbers: Array<{value: string, label: string}>}|null}
 *   `null`, wenn es nichts zu erklären gibt (kein Sidecar, oder sauber).
 */
export function qaCause(qa) {
  if (!qa) return null;
  const grade = qa.quality_grade;
  if (!grade || grade === 'green' || grade === 'n/a' || grade === 'unknown') return null;

  const cap = qa.capture || {};
  const pb = qa.playback || {};
  const expected = Number(cap.expected_frames) || 0;
  const captured = Number(cap.captured_frames) || 0;
  const rejected = Number(cap.rejected_frames) || 0;
  const dup = Number(pb.duplicate_ratio) || 0;
  const top = _topReason(cap.reject_reasons);

  // Alles, was den Bildprüfer überhaupt erreicht hat.
  const reached = captured + rejected;

  const numbers = [
    { value: String(captured), label: 'Bilder im Video' },
    { value: String(expected || '—'), label: 'erwartet' },
    { value: String(rejected), label: 'verworfen' },
    { value: `${Math.round(dup * 100)} %`, label: 'Duplikate' },
  ];

  // 1 · Der Prüfer wirft das meiste weg. Zuerst geprüft, wenn er die
  //     Mehrheit dessen kassiert, was ankam — dann ist das Bildmaterial
  //     das Problem, nicht die Menge.
  if (rejected > 0 && reached > 0 && rejected / reached >= 0.5) {
    return {
      kind: 'rejected',
      headline: `${_pct(rejected, reached)} % der Bilder wurden als unbrauchbar verworfen.`,
      detail: top
        ? `Häufigster Grund: ${top.text} (${top.n}×). Die Kamera liefert Bilder, ` +
          `aber der Bildprüfer erkennt sie als gestört und lässt sie nicht in den Zeitraffer.`
        : 'Die Kamera liefert Bilder, aber der Bildprüfer lässt sie nicht durch.',
      lever:
        'Hier hilft kein Neubau des Videos — die Bilder waren schon beim Aufnehmen gestört. ' +
        'Der Stream selbst ist die Baustelle.',
      numbers,
    };
  }

  // 2 · Es kam fast nichts an. Wenig Verworfenes, aber auch wenig
  //     Aufgenommenes: die Aufnahme läuft nicht oft genug.
  if (expected > 0 && reached < expected * 0.5) {
    return {
      kind: 'starved',
      headline: `Nur ${_pct(reached, expected)} % der geplanten Bilder wurden überhaupt aufgenommen.`,
      detail:
        `Geplant waren ${expected}, angekommen sind ${reached}. ` +
        'Der Encoder füllt die fehlende Zeit mit Wiederholungen — daher die Duplikate.',
      lever:
        'Das Video neu zu bauen ändert nichts: die Bilder von damals fehlen. ' +
        'Zu prüfen ist, warum die Zeitraffer-Aufnahme so selten auslöst.',
      numbers,
    };
  }

  // 3 · Material genug, trotzdem gestreckt: die Ziel-Länge ist länger,
  //     als das Material hergibt.
  if (dup >= 0.2) {
    return {
      kind: 'stretched',
      headline: `${Math.round(dup * 100)} % der Bilder im Video sind Wiederholungen.`,
      detail:
        `Aus ${captured} Bildern soll ein Video von ${Math.round(pb.duration_s || 0)} s werden. ` +
        'Dafür reicht das Material nicht, also wird jedes Bild mehrfach gezeigt.',
      lever:
        'Entweder häufiger aufnehmen (kürzeres Intervall) oder die Ziel-Länge des ' +
        'Profils verkürzen. Beides steht in den Timelapse-Einstellungen der Kamera.',
      numbers,
    };
  }

  return {
    kind: 'other',
    headline: 'Die Qualitätsprüfung hat etwas beanstandet.',
    detail: 'Die Kennzahlen unten sagen, was — ein einzelner klarer Grund war nicht dabei.',
    lever: '',
    numbers,
  };
}

/**
 * PURE: die Kurzfassung für eine ganze Liste — „3 von 10 verlustbehaftet".
 *
 * „bitte stell da irgendwie mit nicht so viel Text da, ob bestimmte
 * Timelapses Lossys sind und wie viel." Eine Zeile, drei Zahlen, und der
 * Grund, der am häufigsten vorkommt — mehr trägt eine Übersicht nicht.
 *
 * @param {Array<object|null>} sidecars
 * @returns {{total, red, yellow, green, kinds: object}|null}
 */
export function qaSummary(sidecars) {
  const list = (sidecars || []).filter(Boolean);
  if (!list.length) return null;
  const out = { total: list.length, red: 0, yellow: 0, green: 0, kinds: {} };
  for (const qa of list) {
    const g = qa.quality_grade;
    if (g === 'red') out.red += 1;
    else if (g === 'yellow') out.yellow += 1;
    else if (g === 'green') out.green += 1;
    const cause = qaCause(qa);
    if (cause) out.kinds[cause.kind] = (out.kinds[cause.kind] || 0) + 1;
  }
  return out;
}
