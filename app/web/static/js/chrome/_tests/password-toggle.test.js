// ─── chrome/_tests/password-toggle.test.js ─────────────────────────────────
// Welches Auge zu welchem Zustand gehört.
//
// Das ist genau die Zuordnung, die einmal falsch war: das Symbol zeigte,
// was ein Klick TUN würde („durchgestrichen = klick mich zum Verbergen"),
// nicht, was gerade zu sehen IST. Der Betreiber las es als Zustand — was
// die naheliegende Lesart ist, wenn ein Auge über einem Feld sitzt — und
// bekam die Aussage verdreht: „Augen auf, PW sichtbar; Auge zu, dann
// Passwort nur Punkte."
//
// Deshalb gepinnt, in beide Richtungen: das offene Auge gehört zum
// sichtbaren Passwort, das durchgestrichene zum maskierten. Und die
// Beschriftung nennt weiter die AKTION, weil das die Aufgabe eines
// Knopfnamens ist — den Zustand trägt `aria-pressed`.

import { test } from 'node:test';
import assert from 'node:assert/strict';

// Das Modul hängt beim Laden zwei Brücken an `window` (die Inline-
// onclicks der Formulare rufen sie so auf), also gibt es ohne Stub schon
// beim Import ein `window is not defined`. Gleiches Muster wie in
// weather/_tests/chart-annotations.test.js, wo `document` gestubbt wird —
// und dieselbe Wand, die library/_tests/bind.test.js dokumentiert.
// Ein dynamischer Import, damit der Stub sicher VOR dem Modulrumpf steht.
globalThis.window = globalThis.window || {};
const { EYE_SVG, EYE_OFF_SVG, _setEyeState, setSecretResolver } =
  await import('../password-toggle.js');

function fakeButton() {
  const attrs = {};
  return {
    innerHTML: '',
    classList: {
      _on: new Set(),
      toggle(name, on) {
        if (on) this._on.add(name);
        else this._on.delete(name);
      },
      contains(name) {
        return this._on.has(name);
      },
    },
    setAttribute(k, v) {
      attrs[k] = v;
    },
    getAttribute(k) {
      return attrs[k];
    },
  };
}

test('ein sichtbares Passwort zeigt das OFFENE Auge', () => {
  const btn = fakeButton();
  _setEyeState(btn, true);
  assert.equal(btn.innerHTML, EYE_SVG);
  assert.ok(btn.classList.contains('revealed'));
});

test('ein maskiertes Passwort zeigt das DURCHGESTRICHENE Auge', () => {
  const btn = fakeButton();
  _setEyeState(btn, false);
  assert.equal(btn.innerHTML, EYE_OFF_SVG);
  assert.ok(!btn.classList.contains('revealed'));
});

test('die Zustände sind nicht dasselbe Symbol', () => {
  // Klingt trivial, ist aber die Zusicherung, an der ein späterer
  // Copy-Paste-Fehler auffällt.
  assert.notEqual(EYE_SVG, EYE_OFF_SVG);
});

test('aria-pressed trägt den Zustand', () => {
  const btn = fakeButton();
  _setEyeState(btn, true);
  assert.equal(btn.getAttribute('aria-pressed'), 'true');
  _setEyeState(btn, false);
  assert.equal(btn.getAttribute('aria-pressed'), 'false');
});

test('die Beschriftung nennt die Aktion, nicht den Zustand', () => {
  // Ein Knopfname sagt, was passiert, wenn man drückt. Zusammen mit
  // aria-pressed bekommt eine Vorlesehilfe beides, ohne dass sich
  // Symbol und Name widersprechen.
  const btn = fakeButton();
  _setEyeState(btn, true);
  assert.equal(btn.getAttribute('aria-label'), 'Passwort verbergen');
  _setEyeState(btn, false);
  assert.equal(btn.getAttribute('aria-label'), 'Passwort anzeigen');
});

test('ein fehlender Knopf ist kein Absturz', () => {
  assert.doesNotThrow(() => _setEyeState(null, true));
});

// ── Enthüllen und wieder zuklappen ────────────────────────────────────────
//
// Der eigentliche Fehler war nie das Symbol: das Passwort steht gar nicht
// im Feld. `redact_camera` schickt es bewusst nie mit `/api/cameras`, also
// war das Eingabefeld immer leer und ein Umschalten von `type` zeigte —
// ein leeres Feld. „Auge offen, soll das Passwort anzeigen, zeigt aber nix
// an." Es wird jetzt beim Öffnen geholt.
//
// Und die Kehrseite, die dabei leicht kaputtgeht: chrome/secret-field.js
// verspricht „nichts getippt = Schlüssel bleibt aus der Payload". Ein
// geholtes Geheimnis, das im Feld liegen bleibt, meldet sich beim nächsten
// Speichern als getippt und schreibt dasselbe Passwort über sich selbst.
// Nur ANSCHAUEN muss also spurlos bleiben, BEARBEITEN nicht.

function fakeInput(type = 'password') {
  return { type, value: '', dataset: {} };
}

/** The pieces window.togglePwField reaches for, minimally. */
function fakeForm(input, btn) {
  const form = { elements: { rtsp_pass: input } };
  btn.closest = () => form;
  return form;
}

/** One reveal, awaited past the resolver's microtask. */
async function reveal(btn) {
  globalThis.window.togglePwField(btn, 'rtsp_pass');
  await new Promise((r) => setTimeout(r, 0));
}

test('das Auge holt das Geheimnis, wenn das Feld leer ist', async () => {
  setSecretResolver(async () => 'hunter2-real');
  const input = fakeInput();
  const btn = fakeButton();
  fakeForm(input, btn);
  await reveal(btn);
  assert.equal(input.value, 'hunter2-real');
  assert.equal(input.type, 'text');
});

test('nur angeschaut heißt: das Feld ist danach wieder leer', async () => {
  setSecretResolver(async () => 'hunter2-real');
  const input = fakeInput();
  const btn = fakeButton();
  fakeForm(input, btn);
  await reveal(btn);
  globalThis.window.togglePwField(btn, 'rtsp_pass');
  assert.equal(input.value, '', 'sonst schreibt der nächste Speichern-Klick es über sich selbst');
  assert.equal(input.type, 'password');
});

test('bearbeitet heißt: die Änderung bleibt', async () => {
  setSecretResolver(async () => 'hunter2-real');
  const input = fakeInput();
  const btn = fakeButton();
  fakeForm(input, btn);
  await reveal(btn);
  input.value = 'neues-passwort';
  globalThis.window.togglePwField(btn, 'rtsp_pass');
  assert.equal(input.value, 'neues-passwort');
});

test('ohne Resolver verhält sich das Auge wie vorher', async () => {
  // Die Telegram- und MQTT-Felder hängen an demselben Schalter und haben
  // keinen Enthüllungspfad — die dürfen sich nicht mit ändern.
  setSecretResolver(null);
  const input = fakeInput();
  input.value = 'schon-getippt';
  const btn = fakeButton();
  fakeForm(input, btn);
  await reveal(btn);
  assert.equal(input.type, 'text');
  assert.equal(input.value, 'schon-getippt');
});
