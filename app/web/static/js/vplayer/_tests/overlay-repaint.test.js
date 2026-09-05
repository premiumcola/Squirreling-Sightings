// Ein Repaint muss aus der Quelle malen, die DIESE Flaeche hat.
//
// „die Person im Video ist nicht mit BBox umkreist, wieso das?"
//
// DER FEHLER: `repaintAt` rief immer `_paintRecorded`, auch auf der
// Live- und Simulations-Flaeche. Dort ist `st.tracks` null und die
// Bereitschaft CLIP_PENDING, also kommt eine leere Sample-Liste heraus —
// und `renderBoxLayer` UEBERSPRINGT die nicht, es setzt
// `svg.innerHTML = ''`. Es loescht.
//
// Und es lief staendig: jeder Simulations-Tick weist dem <img> einen
// frischen base64-Schnappschuss zu, dessen `load` den Refit der Buehne
// ausloest, der wiederum `repaintAt` rief. Reihenfolge pro Tick:
// paintLive malt die Kaesten → der Schnappschuss dekodiert → Refit →
// der Aufnahme-Maler radiert sie weg. Die Kaesten existierten je Tick
// ein paar Millisekunden und waren nie zu sehen.
//
// Der Screenshot-Pruefstand konnte das nicht sehen: seine Sim-Fixture
// schickte `snapshot: null`, also wurde `img.src` nie neu gesetzt, es
// feuerte kein `load`, es gab keinen Refit. Produktion und Pruefstand
// unterschieden sich in genau der einen Variablen, die den Fehler
// ausloest — die Fixture traegt jetzt ein echtes Bild.

import { test } from 'node:test';
import assert from 'node:assert/strict';

/** Gerade so viel DOM, wie der Maler anfasst. */
function installDom() {
  const mkSvg = () => ({
    _html: '',
    setAttribute() {},
    get innerHTML() {
      return this._html;
    },
    set innerHTML(v) {
      this._html = v;
    },
  });
  globalThis.document = {
    createElementNS: () => mkSvg(),
    createElement: () => ({ getContext: () => null }),
  };
  globalThis.window = { devicePixelRatio: 1 };
}

/** Eine Ebene, die sich merkt, was zuletzt hineingeschrieben wurde. */
function layer() {
  return {
    _html: '',
    firstElementChild: null,
    get innerHTML() {
      return this._html;
    },
    set innerHTML(v) {
      this._html = v;
    },
    // Breite 0 → _paintZones kehrt sofort zurueck und braucht kein Canvas.
    getBoundingClientRect: () => ({ width: 0, height: 0 }),
    // Muss den Kindknoten WIRKLICH behalten: renderBoxLayer legt das
    // <svg> genau einmal an und schreibt danach nur noch in dessen
    // innerHTML. Ein appendChild, das nichts tut, wirft jeden Malvorgang
    // weg — und der Test misst dann den Stub, nicht den Code.
    appendChild(child) {
      this.firstElementChild = child;
    },
  };
}

function stubStage() {
  let refit = null;
  return {
    layers: { boxes: layer(), trails: layer(), zones: layer() },
    video: null,
    media: { naturalWidth: 960, naturalHeight: 540 },
    rect: () => ({ x: 0, y: 0, w: 800, h: 450, scale: 1 }),
    chrome: () => [],
    onRefit: (fn) => {
      refit = fn;
      return () => {};
    },
    /** Was `_stage.js` beim `load` des <img> tut. */
    fireRefit: () => refit && refit(),
  };
}

const FRAME = {
  frameSize: { w: 960, h: 540 },
  detections: [
    {
      raw: { label: 'person', score: 0.84, verdict: 'pass', bbox: [672, 46, 98, 262] },
      colour: null,
    },
  ],
};

const LIVE_CFG = {
  flags: { showOverlays: true, live: true },
  overlays: { bboxes: true, trails: false, zones: false, masks: false },
  item: { camera_id: 'cam_a' },
};

test('ein Refit auf der Live-Flaeche loescht die Kaesten NICHT', async () => {
  installDom();
  const { mountOverlayPainter } = await import('../_overlay-paint.js');
  const stage = stubStage();
  const painter = mountOverlayPainter(stage, LIVE_CFG);
  assert.ok(painter, 'der Maler muss auf einer Live-Flaeche montiert werden');

  painter.paintLive(FRAME);
  const gemalt = stage.layers.boxes.firstElementChild || stage.layers.boxes;
  const nachPaint = gemalt.innerHTML;
  assert.notEqual(nachPaint, '', 'paintLive muss ueberhaupt etwas malen');

  // GENAU DER MOMENT: der Schnappschuss ist dekodiert, die Buehne passt
  // die Ebenen neu an. Vorher radierte das hier alles weg.
  stage.fireRefit();
  assert.equal(gemalt.innerHTML, nachPaint, 'der Refit hat die Kaesten geloescht');
});

test('ein Schalterdruck auf der Live-Flaeche malt neu statt zu leeren', async () => {
  installDom();
  const { mountOverlayPainter } = await import('../_overlay-paint.js');
  const stage = stubStage();
  const painter = mountOverlayPainter(stage, LIVE_CFG);

  painter.paintLive(FRAME);
  const gemalt = stage.layers.boxes.firstElementChild || stage.layers.boxes;
  const nachPaint = gemalt.innerHTML;

  painter.setLayers({ bboxes: false });
  assert.equal(gemalt.innerHTML, '', 'aus heisst aus');
  painter.setLayers({ bboxes: true });
  assert.equal(gemalt.innerHTML, nachPaint, 'und wieder ein heisst wieder da');
});

test('ohne je einen Rahmen gesehen zu haben, malt ein Refit nichts Falsches', async () => {
  // Der Refit kann vor dem ersten Tick feuern. Dann gibt es nichts zu
  // malen — und erst recht nichts zu loeschen.
  installDom();
  const { mountOverlayPainter } = await import('../_overlay-paint.js');
  const stage = stubStage();
  const painter = mountOverlayPainter(stage, LIVE_CFG);
  assert.doesNotThrow(() => stage.fireRefit());
  assert.ok(painter);
});

test('die Aufnahme-Flaeche laeuft weiter ueber den Aufnahme-Maler', async () => {
  // Die Verzweigung darf nur die Live-Flaeche betreffen. Ohne Feinspur
  // und ohne zeichenbaren Auslöse-Kasten bleibt die Ebene leer — das ist
  // der bisherige, richtige Zustand.
  installDom();
  const { mountOverlayPainter } = await import('../_overlay-paint.js');
  const stage = stubStage();
  const painter = mountOverlayPainter(stage, {
    ...LIVE_CFG,
    flags: { showOverlays: true, live: false },
  });
  assert.doesNotThrow(() => stage.fireRefit());
  assert.equal(stage.layers.boxes.innerHTML, '');
  assert.ok(painter);
});
