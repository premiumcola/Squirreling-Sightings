// ─── mediaview/_tests/_dom-stub.js ─────────────────────────────────────────
// The smallest DOM that can answer ONE question: which host did the
// verdict band choose, and did the text land in it.
//
// That question is the whole regression. Every failure message the poll
// loop produced was correct German and went into `#lightboxMediaWrap` —
// the legacy modal the unified player replaced and does not render — so
// nothing was on screen during an outage. A pure test can pin the strings
// (live-detect-outage.test.js does) and still not notice that they are
// being written into a node nobody can see.
//
// DELIBERATELY NOT A DOM. There is no jsdom in this repo (see
// library/_tests/_setup.js's header for why `node:test` alone was chosen)
// and no selector engine here: `querySelector` answers from a registry of
// the exact strings the module under test asks for. It cannot tell you
// that a real browser would match them — the screenshot harness
// (`node scripts/uishot/run.mjs vplayer-sim-tpu-taken`) is what proves
// that, and it is where a selector typo would show up as an empty shot.
// What it CAN tell you is which of two candidate hosts won, which is
// exactly the bug.

class StubEl {
  constructor(tag) {
    this.tagName = String(tag || 'div').toUpperCase();
    this.children = [];
    this.parent = null;
    this.dataset = {};
    this.attributes = {};
    this.id = '';
    this.className = '';
    this.innerHTML = '';
  }

  get firstChild() {
    return this.children[0] || null;
  }

  insertBefore(node, ref) {
    const at = ref ? this.children.indexOf(ref) : -1;
    if (at < 0) this.children.push(node);
    else this.children.splice(at, 0, node);
    node.parent = this;
    return node;
  }

  appendChild(node) {
    return this.insertBefore(node, null);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }

  addEventListener() {
    /* the band's button is never clicked in these tests */
  }

  remove() {
    if (!this.parent) return;
    this.parent.children = this.parent.children.filter((c) => c !== this);
    this.parent = null;
  }

  /** `#id` only — the one form live-detect-verdict.js uses on a host. */
  querySelector(sel) {
    const want = sel.startsWith('#') ? sel.slice(1) : null;
    if (!want) return null;
    for (const child of this.children) {
      if (child.id === want) return child;
      const deeper = child.querySelector(sel);
      if (deeper) return deeper;
    }
    return null;
  }

  /** Everything this node and its descendants would render as text. */
  get renderedText() {
    const own = String(this.innerHTML).replaceAll(/<[^>]*>/g, ' ');
    return [own, ...this.children.map((c) => c.renderedText)].join(' ');
  }
}

/**
 * Install a stub `document` and return the handle that seeds it.
 *
 * @returns {{el: (tag?: string) => StubEl,
 *   selector: (sel: string, node: StubEl|null) => void,
 *   byId: (id: string, node: StubEl|null) => void,
 *   reset: () => void}}
 */
export function installStubDom() {
  const bySelector = new Map();
  const byId = new Map();
  globalThis.window = globalThis.window || {};
  globalThis.document = {
    createElement: (tag) => new StubEl(tag),
    getElementById: (id) => byId.get(id) || null,
    querySelector: (sel) => bySelector.get(sel) || null,
    querySelectorAll: () => [],
  };
  return {
    el: (tag) => new StubEl(tag),
    selector: (sel, node) => bySelector.set(sel, node),
    byId: (id, node) => byId.set(id, node),
    reset: () => {
      bySelector.clear();
      byId.clear();
    },
  };
}
