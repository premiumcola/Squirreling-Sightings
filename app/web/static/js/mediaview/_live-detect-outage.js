// ─── mediaview/_live-detect-outage.js ──────────────────────────────────────
// PURE. What went wrong with the simulation, in the operator's words.
//
// WHY THIS EXISTS. Every failure the poll loop could reach was already
// classified — `_classifyTickFailure` produced "503 · Kamera liefert noch
// keine Frames" — and then delivered into `#lightboxMediaWrap`, the legacy
// modal the unified player replaced and no longer renders. During a real
// outage the operator saw NOTHING: no banner, no text, a panel that simply
// stopped changing. A code and a status are also not an answer; "429" does
// not tell anyone that the TPU has exactly one owner and the live instance
// is holding it.
//
// So: one verdict per failure mode, each saying which mode it is and what
// the operator can do about it. Kept free of DOM and of every sibling in
// this cluster (same rule as _live-detect-cadence.js and
// _live-detect-tick-status.js) so `node --test` can pin every string
// without a browser.
//
// THE BACKEND'S OWN WORDS WIN wherever it wrote a specific one. Three
// bodies carry arithmetic this file cannot reproduce — the mode refusal
// names the estimated cost and the ceiling, the revision error names the
// id, the 500 names the exception — and paraphrasing them would drop the
// only number worth screenshotting. Everything else is written here,
// because the backend's own text for it is a hypothesis in parentheses
// ("Coral nicht verfügbar (motion-only?)") rather than an instruction.
//
// THE MODES, and where each is produced — routes/coral_test_detection.py
// unless noted:
//   busy                429 · code=busy               _sim_guard.busy_payload
//   mode_too_expensive  429 · code=mode_too_expensive _sim_guard.refusal_payload
//   no_frame            503 · code=no_frame           _sim_frame.FramePick.failure
//   stale               503 · code=stale                     "
//   corrupt             503 · code=corrupt                   "
//   coral_unavailable   503 · every detector tier failed
//   runtime_inactive    503 · app_state.runtimes has no thread
//   unknown_revision    400 · replay/_settings.py raised ValueError
//   inference_failed    500 · _run_pass threw
//   camera_not_found    404 · unknown id, or the traversal guard
//   server              any other non-ok answer
//   neterr              the fetch itself rejected — browser → server
//   contact             nothing answered at all (the CONTACT watchdog)
//   pace                answers arrive, frames are slow (informational)

/** Tone ladder. `wait` is transient and self-healing, `bad` needs a hand. */
const OK = 'ok';
const WAIT = 'wait';
const WARN = 'warn';
const BAD = 'bad';

/** The one action a verdict may offer, by id. */
const RETRY = { id: 'retry', label: 'Erneut versuchen' };
const MODE_OFF = { id: 'mode-off', label: 'Auf „Aus“ zurückschalten' };

/**
 * One entry per failure mode: what it is, and what to do.
 *
 * `detail` answers "what is actually broken"; `hint` answers "and now".
 * Both are deliberately separate — a detail that also carries the
 * instruction reads as a wall and gets skipped, which is how the old
 * one-line banners were read.
 */
const _TEXTS = {
  busy: {
    tone: WAIT,
    title: 'Analyse läuft noch',
    detail:
      'Der Server rechnet den vorherigen Tick zu Ende. Die Simulation hat ' +
      'genau einen Slot je Kamera, und Flask kann eine laufende Anfrage nicht abbrechen.',
    hint: 'Kein Eingriff nötig — der nächste Tick geht raus, sobald der Slot frei ist.',
    action: null,
  },
  mode_too_expensive: {
    tone: WARN,
    // No `hint`. The backend's own body — quoted below — already names the
    // arithmetic AND the two ways out, and the button is the third. Adding
    // a line that repeats them is the duplication CLAUDE.md forbids, and
    // it pushed the button off a 375 px screen.
    title: 'Modus zu teuer für diese Hardware',
    detail:
      'Der gewählte Kachel-Modus kostet mehr Inferenzen je Bild, als in einen ' +
      'Tick passen. Die Kamera ist in Ordnung; abgelehnt wurde der Modus.',
    hint: '',
    action: MODE_OFF,
  },
  no_frame: {
    tone: BAD,
    title: 'Kamera liefert keine Bilder',
    detail:
      'In 2,5 s kam kein einziger Frame aus dem Stream. Das ist die Strecke ' +
      'Kamera → Server; die Erkennung war nie an der Reihe.',
    hint: 'Stream-URL und Zugangsdaten prüfen — die Kamera antwortet gerade nicht.',
    action: RETRY,
  },
  stale: {
    tone: WARN,
    title: 'Stream-Puffer hinkt zurück',
    detail:
      'Frames kommen an, aber keiner war innerhalb von 2,5 s frisch genug. Der ' +
      'Decoder läuft der Kamera hinterher, statt mit ihr mitzuhalten.',
    hint: 'Auf den Sub-Stream wechseln oder Bildrate/Auflösung der Kamera senken.',
    action: RETRY,
  },
  corrupt: {
    tone: WARN,
    title: 'Nur korrupte Frames',
    detail:
      'Jedes Bild trug den gestörten Farbstreifen des Decoders. Solche Frames ' +
      'werden verworfen, bevor Coral sie sieht — sonst erkennt er Müll.',
    hint: 'Meist ein überlasteter Stream: Bitrate oder Auflösung der Kamera reduzieren.',
    action: RETRY,
  },
  coral_unavailable: {
    tone: BAD,
    title: 'TPU belegt oder nicht eingebunden',
    detail:
      'Der Coral-Stick hat genau einen Besitzer. Hält ihn die Live-Instanz ' +
      'dieser Kamera, kommt die Simulation nicht dran — sie braucht ihn exklusiv. ' +
      'Auch der CPU-Rückfall ist hier gescheitert.',
    hint:
      'Läuft die Kamera bewusst nur auf Bewegung, gibt es nichts zu erkennen. ' +
      'Sonst: Live-Instanz stoppen, dann erneut versuchen.',
    action: RETRY,
  },
  runtime_inactive: {
    tone: BAD,
    title: 'Kamera-Runtime steht',
    detail:
      'Für diese Kamera läuft kein Runtime-Thread. Sie ist deaktiviert oder ' +
      'beim Start gescheitert — dann kann niemand ein Bild holen.',
    hint: 'Kamera in den Einstellungen aktivieren und neu laden.',
    action: RETRY,
  },
  unknown_revision: {
    tone: WARN,
    title: 'Profil-Stand nicht ladbar',
    detail:
      'Die Simulation sollte auf einem anderen Profil-Stand laufen, den der ' +
      'Server nicht auflösen kann.',
    hint: 'Oben im Profil-Wähler zurück auf „Aktuelles Profil“.',
    action: null,
  },
  inference_failed: {
    tone: BAD,
    title: 'Inferenz fehlgeschlagen',
    detail:
      'Das Bild war da, das Modell hat es abgelehnt. Der Fehler kommt aus dem ' +
      'Detektor selbst, nicht aus der Kamera und nicht aus dem Netz.',
    hint: 'Bleibt das stehen: im Container-Log nach Zeilen mit [det] sehen.',
    action: RETRY,
  },
  camera_not_found: {
    tone: BAD,
    title: 'Kamera unbekannt',
    detail:
      'Der Server kennt diese Kamera-ID nicht. Sie wurde umbenannt oder ' +
      'gelöscht, während die Ansicht offen stand.',
    hint: 'Ansicht schließen und die Kamera aus dem Dashboard neu öffnen.',
    action: null,
  },
  server: {
    tone: BAD,
    title: 'Server hat den Tick abgelehnt',
    detail:
      'Es kam eine Antwort, aber kein Tick. Der Server lebt — der Grund für ' +
      'die Ablehnung steht in seinem Log.',
    hint: 'docker logs squirreling-sightings --tail 50 zeigt ihn ausgeschrieben.',
    action: RETRY,
  },
  neterr: {
    tone: BAD,
    title: 'Keine Verbindung zum Server',
    detail:
      'Die Anfrage kam nicht einmal an. Das ist die Strecke Browser → Server ' +
      '— über die Kamera sagt es nichts aus.',
    hint: 'WLAN oder VPN prüfen; läuft der Container noch?',
    action: RETRY,
  },
  contact: {
    tone: BAD,
    title: 'Keine Antwort vom Server',
    detail:
      'Die letzte Anfrage ist rausgegangen und nie zurückgekommen. Sie läuft ' +
      'noch, oder sie ist unterwegs verloren gegangen.',
    hint: 'Es wird automatisch erneut versucht, mit wachsendem Abstand.',
    action: RETRY,
  },
  pace: {
    tone: WAIT,
    title: 'Analyse dauert',
    detail:
      'Der Tick ist noch unterwegs. Kein Fehler — dieser Modus kostet ' +
      'schlicht mehrere Inferenzen je Bild.',
    hint: 'Ein günstigerer Modus verkürzt den Takt sofort.',
    action: null,
  },
};

/** Ids the endpoint sends as `code`, mapped 1:1 onto a verdict. */
const _BY_CODE = new Set([
  'busy',
  'mode_too_expensive',
  'no_frame',
  'stale',
  'corrupt',
  'coral_unavailable',
  'runtime_inactive',
  'unknown_revision',
  'inference_failed',
  'camera_not_found',
]);

/** Status → verdict, for the bodies that carry no `code` at all. */
const _BY_STATUS = { 400: 'unknown_revision', 404: 'camera_not_found', 500: 'inference_failed' };

/**
 * A 503 with no `code` — which of the two bare ones is it?
 *
 * A fallback, not the contract: the endpoint labels both now. It stays
 * because the browser can outlive one container restart, and an
 * unlabelled 503 landing on the generic 'server' verdict would name the
 * log instead of naming the TPU.
 */
function _bare503(msg) {
  if (/coral/i.test(msg)) return 'coral_unavailable';
  if (/runtime/i.test(msg)) return 'runtime_inactive';
  return 'server';
}

/** Which verdict an ok=false response is. */
function _idForResponse(status, code, msg) {
  if (code && _BY_CODE.has(code)) return code;
  if (_BY_STATUS[status]) return _BY_STATUS[status];
  if (status === 503) return _bare503(msg);
  return 'server';
}

/**
 * The verdict text, with the backend's own message where it carries
 * arithmetic this file cannot reproduce. `server` takes it too — a
 * generic refusal is only useful if it quotes what was refused.
 */
const _QUOTE_BACKEND = new Set([
  'mode_too_expensive',
  'unknown_revision',
  'inference_failed',
  'server',
]);

/**
 * Classify one failure into the verdict the panel shows.
 *
 * @param {object} input one of
 *   {kind:'http', status:number, data:object|null}
 *   {kind:'neterr', message:string}
 *   {kind:'contact', gapMs:number}
 *   {kind:'pace', modeLabel:string, invokes:number}
 * @returns {{id,tone,title,detail,hint,action,code}|null} null for an
 *   input this function does not recognise — the caller then leaves
 *   whatever is on screen alone rather than painting a shrug.
 */
export function classifyOutage(input) {
  const kind = input && input.kind;
  if (kind === 'neterr') return _verdict('neterr', { code: 'neterr', why: input.message });
  if (kind === 'contact') return _verdict('contact', { code: 'timeout', gapMs: input.gapMs });
  if (kind === 'pace') return _verdict('pace', input);
  if (kind !== 'http') return null;
  const data = input.data || null;
  const code = data && data.code ? String(data.code) : '';
  const msg = String((data && (data.error || data.message)) || '');
  const id = _idForResponse(input.status, code, msg);
  return _verdict(id, { code: code || input.status || '?', msg });
}

/** Build one verdict record, applying the per-mode text adjustments. */
function _verdict(id, ctx) {
  const base = _TEXTS[id];
  const out = { id, code: ctx.code ?? null, ...base };
  if (ctx.msg && _QUOTE_BACKEND.has(id)) out.detail = ctx.msg;
  if (id === 'neterr' && ctx.why) out.detail = `${base.detail} (${ctx.why})`;
  if (id === 'contact' && Number.isFinite(ctx.gapMs)) {
    out.detail = `Seit ${_secs(ctx.gapMs)} s kein Tick. ${base.detail}`;
  }
  if (id === 'pace' && ctx.invokes) {
    const mode = ctx.modeLabel || 'Dieser Modus';
    out.detail = `${base.detail} ${mode} kostet ${ctx.invokes} Inferenzen je Bild.`;
  }
  return out;
}

/** One decimal, German comma — the way every other number here is set. */
function _secs(ms) {
  return (Math.max(0, Number(ms) || 0) / 1000).toFixed(1).replace('.', ',');
}

/**
 * A cadence, in the unit that carries information at its own magnitude.
 *
 * Seconds-with-one-decimal alone printed a 40 ms cycle as "~0,0 s", which
 * says the loop is instant and unmeasured in the same breath. Under a
 * second the milliseconds ARE the reading.
 */
function _takt(ms) {
  const n = Math.max(0, Number(ms) || 0);
  return n < 1000 ? `${Math.round(n)} ms` : `${_secs(n)} s`;
}

/**
 * The verdict when nothing is wrong — and the one when the tick SUCCEEDED
 * but on the wrong processor.
 *
 * The CPU fallback is the failure mode with no failure response. When
 * another process owns the Edge TPU, `CoralObjectDetector` walks down its
 * tiers and the CPU tier answers; the endpoint then returns a perfectly
 * ordinary 200 whose only trace of the problem is
 * `modes.inference.reason = "cpu_fallback (coral: …)"`. On screen that was
 * a chip reading "CPU" and nothing else — the operator sees a running
 * simulation whose numbers describe hardware the camera is not using.
 *
 * @param {object} info {modeLabel, invokes, cadenceMs, device, reason}
 * @returns {{id,tone,title,detail,hint,action,code}}
 */
export function describeHealth(info = {}) {
  if (info.device === 'cpu' && /fallback/i.test(String(info.reason || ''))) {
    return {
      id: 'cpu_fallback',
      code: 'cpu_fallback',
      tone: WARN,
      title: 'Läuft auf der CPU, nicht auf der TPU',
      detail:
        'Der Coral-Stick war beim Start des Detektors nicht zu bekommen — er ' +
        'hat genau einen Besitzer. Die Zeiten unten sind CPU-Zeiten und sagen ' +
        'nichts über den Takt der Produktion aus.',
      hint: 'Live-Instanz stoppen und die Ansicht neu öffnen, um die TPU zu bekommen.',
      action: null,
    };
  }
  return {
    id: 'running',
    code: 'ok',
    tone: OK,
    title: 'Simulation läuft',
    // The cadence and its price, and nothing the chips below already say.
    // The mode is one of those chips; naming it again here is the same
    // fact twice.
    detail: _healthLine(info),
    hint: '',
    action: null,
  };
}

/** "Takt ~250 ms · 5 Inferenzen je Bild", degrading a term at a time. */
function _healthLine(info) {
  const parts = [];
  if (Number.isFinite(info.cadenceMs)) parts.push(`Takt ~${_takt(info.cadenceMs)}`);
  if (info.invokes > 1) parts.push(`${info.invokes} Inferenzen je Bild`);
  return parts.length ? parts.join(' · ') : 'Der erste Tick ist unterwegs.';
}
