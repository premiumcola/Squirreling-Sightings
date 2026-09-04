/* ─── scripts/uishot/_inpage-audit.js ──────────────────────────────────────
 * The checks that run INSIDE the page, against computed style and real
 * layout boxes. Injected with addScriptTag, so it is a plain script and
 * not a module — it only has to define window.__uiaudit.
 *
 * A screenshot only helps if somebody looks at it. These four rules are
 * the ones the DOM can answer without an opinion, and each maps to a
 * defect class this project has actually shipped:
 *
 *   overflow  — the phone-width horizontal scroll
 *   touch     — the iOS 44 px minimum from CLAUDE.md
 *   contrast  — the dark-on-dark button, twice
 *   overlap   — chrome sitting on top of chrome at 375 px
 */
(function () {
  'use strict';

  var MIN_TOUCH = 44;
  var MIN_CONTRAST = 4.5;
  var INTERACTIVE = 'button,a[href],input,select,textarea,[role="button"],[onclick],summary';

  /** A short, human-usable selector for one element. */
  function sel(el) {
    if (!el || !el.tagName) return '?';
    if (el.id) return '#' + el.id;
    var s = el.tagName.toLowerCase();
    var cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
    if (cls.length) return s + '.' + cls.join('.');
    // Anonymous node: name the nearest identifiable ancestor, otherwise
    // the finding reads "div ✕ div" and nobody can act on it.
    var p = el.parentElement;
    var depth = 0;
    while (p && depth < 4) {
      if (p.id) return '#' + p.id + ' ' + '>'.repeat(1) + ' … ' + s;
      var pc = (p.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean)[0];
      if (pc) return '.' + pc + ' … ' + s;
      p = p.parentElement;
      depth++;
    }
    return s;
  }

  /** Is this element actually painted? */
  function visible(el) {
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0)
      return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function parseRgb(v) {
    var m = /rgba?\(([^)]+)\)/.exec(v || '');
    if (!m) return null;
    var p = m[1].split(',').map(function (x) {
      return parseFloat(x);
    });
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }

  function lum(c) {
    var f = [c.r, c.g, c.b].map(function (v) {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  }

  function ratio(fg, bg) {
    var a = lum(fg) + 0.05;
    var b = lum(bg) + 0.05;
    return a > b ? a / b : b / a;
  }

  /** Composite a translucent colour over an opaque backdrop. */
  function over(top, base) {
    var a = top.a;
    return {
      r: top.r * a + base.r * (1 - a),
      g: top.g * a + base.g * (1 - a),
      b: top.b * a + base.b * (1 - a),
      a: 1,
    };
  }

  /**
   * The colour actually behind this element's text.
   * Returns null when an image or gradient is in the stack — guessing
   * there would manufacture false positives.
   */
  function effectiveBg(el) {
    var stack = [];
    var node = el;
    while (node && node.nodeType === 1) {
      var cs = getComputedStyle(node);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      var c = parseRgb(cs.backgroundColor);
      if (c && c.a > 0) {
        stack.push(c);
        if (c.a >= 1) break;
      }
      node = node.parentElement;
    }
    if (!stack.length) return { r: 255, g: 255, b: 255, a: 1 };
    var base = stack[stack.length - 1];
    if (base.a < 1) base = over(base, { r: 255, g: 255, b: 255, a: 1 });
    for (var i = stack.length - 2; i >= 0; i--) base = over(stack[i], base);
    return base;
  }

  /** Does the element hold text of its own (not just via children)? */
  function ownText(el) {
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3 && n.textContent.trim().length > 1) return n.textContent.trim();
    }
    return null;
  }

  function checkContrast(root, out) {
    var els = root.querySelectorAll('*');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var txt = ownText(el);
      if (!txt || !visible(el)) continue;
      var cs = getComputedStyle(el);
      var fg = parseRgb(cs.color);
      var bg = effectiveBg(el);
      if (!fg || !bg) continue;
      if (fg.a < 1) fg = over(fg, bg);
      var r = ratio(fg, bg);
      if (r < MIN_CONTRAST) {
        out.push({
          rule: 'contrast',
          selector: sel(el),
          detail:
            r.toFixed(2) +
            ':1 (min ' +
            MIN_CONTRAST +
            ') ' +
            cs.color +
            ' on rgb(' +
            Math.round(bg.r) +
            ',' +
            Math.round(bg.g) +
            ',' +
            Math.round(bg.b) +
            ')',
          text: txt.slice(0, 40),
        });
      }
    }
  }

  /**
   * Does a finger-sized area centred on this control actually hit it?
   *
   * The box is not the answer. A small control with a transparent
   * pseudo-element hit expander — `::before { inset: -5px 0 }` or an
   * absolutely-positioned 44×44 box — is fully compliant while its own
   * rect measures 34 px, and this audit reported every one of them. The
   * player alone produced 21 such findings per surface, which is how a
   * column of pure noise teaches everyone to stop reading it.
   *
   * So ask the browser instead of the stylesheet: probe the four corners
   * of the 44×44 square around the control's centre and see what would
   * receive the tap. A pseudo-element hands back its own owner, so an
   * expander answers for the control it belongs to. Anything the control
   * genuinely does not cover comes back as something else — a real
   * finding, kept.
   */
  function tapReaches(el, r) {
    var cx = r.left + r.width / 2;
    var cy = r.top + r.height / 2;
    var h = MIN_TOUCH / 2 - 1;
    var pts = [
      [cx - h, cy - h],
      [cx + h, cy - h],
      [cx - h, cy + h],
      [cx + h, cy + h],
    ];
    // elementFromPoint only answers for the visible viewport, so a
    // control below the fold cannot be probed. Fall back to the plain
    // rect verdict there — i.e. REPORT it.
    //
    // The first version returned "fine" instead, on the reasoning that
    // an unprobeable control is not evidence of a defect. That quietly
    // dropped every finding below the first screenful, which on a long
    // panel is most of the page: the dossier's 184×15 Wikipedia link
    // disappeared from the audit entirely. An audit that over-reports
    // wastes a minute; one that under-reports is worse than none.
    if (r.top < 0 || r.left < 0 || r.bottom > window.innerHeight || r.right > window.innerWidth) {
      return false;
    }
    for (var i = 0; i < pts.length; i++) {
      var x = Math.max(0, Math.min(window.innerWidth - 1, pts[i][0]));
      var y = Math.max(0, Math.min(window.innerHeight - 1, pts[i][1]));
      var hit = document.elementFromPoint(x, y);
      if (!hit) return false;
      // The control itself, or something inside it (its own icon or
      // label). A pseudo-element hands back its owner, which is how an
      // expander answers here.
      //
      // Deliberately NOT its ancestors: an early version accepted them,
      // and a 184×15 link sitting in a big card passed because the
      // card caught every corner. That silently deleted real findings
      // across the whole app — the check has to prove the CONTROL is
      // reachable, not that something is.
      if (hit !== el && !el.contains(hit)) return false;
    }
    return true;
  }

  function checkTouch(root, out) {
    var els = root.querySelectorAll(INTERACTIVE);
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!visible(el)) continue;
      if (el.tagName === 'A' && !el.getAttribute('href')) continue;
      var r = el.getBoundingClientRect();
      if (r.width < MIN_TOUCH || r.height < MIN_TOUCH) {
        // Small on screen is allowed; small to the FINGER is not.
        if (tapReaches(el, r)) continue;
        out.push({
          rule: 'touch',
          selector: sel(el),
          detail: Math.round(r.width) + '×' + Math.round(r.height) + ' px (min 44×44)',
          text: (el.textContent || '').trim().slice(0, 30),
        });
      }
    }
  }

  /**
   * Is this element's width contained by a horizontal scroller?
   *
   * CLAUDE.md's rule is that wide content scrolls inside its own
   * `overflow-x: auto` container and the body never scrolls sideways, so
   * content that honours it is not a defect — the 24 hour-columns of the
   * Statistik heatmap alone produced two dozen findings per width, all
   * working as designed, which is how a real one goes unnoticed. The
   * scroller itself is still measured: it has no scrolling ancestor.
   *
   * `hidden` deliberately does NOT count. That clips content without
   * offering any way to reach it, which is a defect worth reporting.
   */
  function scrollsInside(el) {
    var n = el.parentElement;
    while (n && n.nodeType === 1) {
      var ox = getComputedStyle(n).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
      n = n.parentElement;
    }
    return false;
  }

  function checkOverflow(root, out, vw) {
    var els = root.querySelectorAll('*');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!visible(el) || scrollsInside(el)) continue;
      var r = el.getBoundingClientRect();
      if (r.width > vw + 1 || r.right > vw + 1) {
        out.push({
          rule: 'overflow',
          selector: sel(el),
          detail:
            'right edge ' +
            Math.round(r.right) +
            'px, width ' +
            Math.round(r.width) +
            'px, viewport ' +
            vw +
            'px',
          text: (el.textContent || '').trim().slice(0, 30),
        });
      }
    }
  }

  /** Two boxes overlap by more than a hairline. */
  function overlaps(a, b) {
    var x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    var y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return x > 2 && y > 2;
  }

  /**
   * Siblings in normal flow must not sit on top of one another.
   * Positioned elements are skipped: an overlay covering its stage is
   * the design, not a bug, and flagging it would bury the real hits.
   */
  function checkOverlap(root, out) {
    var parents = [root].concat(Array.prototype.slice.call(root.querySelectorAll('*')));
    for (var p = 0; p < parents.length; p++) {
      // SVG children overlap by design — a path crossing a polyline is a
      // drawing, not a layout bug, and flagging it buries the real hits.
      if (parents[p].closest && parents[p].closest('svg')) continue;
      var kids = [];
      var ch = parents[p].children;
      for (var i = 0; i < ch.length; i++) {
        var cs = getComputedStyle(ch[i]);
        if (cs.position !== 'static' && cs.position !== 'relative') continue;
        if (cs.float !== 'none' || !visible(ch[i])) continue;
        kids.push(ch[i]);
      }
      for (var a = 0; a < kids.length; a++) {
        for (var b = a + 1; b < kids.length; b++) {
          var ra = kids[a].getBoundingClientRect();
          var rb = kids[b].getBoundingClientRect();
          if (!overlaps(ra, rb)) continue;
          out.push({
            rule: 'overlap',
            selector: sel(kids[a]) + '  ✕  ' + sel(kids[b]),
            detail: 'in-flow siblings overlap inside ' + sel(parents[p]),
            text: '',
          });
        }
      }
    }
  }

  /**
   * Two pieces of TEXT sharing the same pixels.
   *
   * Separate from checkOverlap on purpose. That rule ignores positioned
   * elements, because an overlay covering its stage is the design — but
   * that exemption is exactly where this project's worst offenders hide:
   * an absolutely-positioned label printed straight through another
   * label. Two texts on top of one another is essentially never
   * intentional, whatever the position property says.
   */
  /** Does this element paint a box of its own (button, pill, picture)? */
  function paints(el) {
    var tag = el.tagName.toUpperCase();
    if (tag === 'IMG' || tag === 'SVG' || tag === 'VIDEO' || tag === 'CANVAS') return true;
    var cs = getComputedStyle(el);
    if (cs.backgroundImage && cs.backgroundImage !== 'none') return true;
    var c = parseRgb(cs.backgroundColor);
    return !!(c && c.a > 0.05);
  }

  /** a fully inside b? */
  function contains(a, b) {
    return (
      a.left >= b.left - 1 &&
      a.right <= b.right + 1 &&
      a.top >= b.top - 1 &&
      a.bottom <= b.bottom + 1
    );
  }

  function checkTextCollision(root, out) {
    var all = root.querySelectorAll('*');
    var texts = [];
    var painted = [];
    for (var i = 0; i < all.length; i++) {
      if (!visible(all[i])) continue;
      var rect = all[i].getBoundingClientRect();
      var t = ownText(all[i]);
      if (t) texts.push({ el: all[i], rect: rect, text: t });
      // A control or pill printed across a label is the same defect
      // wearing a different hat, and it is the one the Mediathek card
      // actually has — the ✓ button clips the species pill. Text against
      // text alone never sees it: a one-glyph button carries no text
      // worth calling text, and a play button carries none at all.
      if (paints(all[i])) painted.push({ el: all[i], rect: rect, text: '' });
    }
    _collide(texts, texts, out, 'text over text');
    _collide(texts, painted, out, 'painted box clips text');
  }

  /**
   * Cross-compare two element lists for PARTIALLY overlapping boxes.
   *
   * Partial is the whole discrimination. A backdrop, a scrim or a card
   * body fully CONTAINS the text it sits behind — that is layering, and
   * flagging it would bury every real hit under one finding per label.
   * A box that covers only part of a text is a collision.
   */
  function _collide(left, right, out, why) {
    var same = left === right;
    for (var a = 0; a < left.length; a++) {
      for (var b = same ? a + 1 : 0; b < right.length; b++) {
        var x = left[a];
        var y = right[b];
        if (x.el === y.el) continue;
        if (x.el.contains(y.el) || y.el.contains(x.el)) continue;
        if (!overlaps(x.rect, y.rect)) continue;
        if (contains(x.rect, y.rect) || contains(y.rect, x.rect)) continue;
        out.push({
          rule: 'textcollide',
          selector: sel(x.el) + '  ✕  ' + sel(y.el),
          detail: why,
          text: (x.text || '').slice(0, 24),
        });
      }
    }
  }

  /**
   * Text that is actually BURIED — hit-testing, not box arithmetic.
   *
   * Box overlap cannot answer "is this readable", because it knows
   * nothing about stacking order: the player's own chrome legitimately
   * covers the page behind it. elementFromPoint answers the real
   * question — click where this text is, and something else answers.
   * That is how the mobile dock eating the weather panel's Abbrechen /
   * Speichern buttons shows up, and it is invisible to every other rule
   * here because the dock is not inside the surface at all.
   *
   * Every sample point must be occluded before it counts; a single
   * clipped corner is checkTextCollision's job, not this one.
   */
  function checkOccluded(root, out) {
    var els = root.querySelectorAll('*');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!ownText(el) || !visible(el)) continue;
      var r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
      var pts = [
        [r.left + r.width * 0.25, r.top + r.height / 2],
        [r.left + r.width * 0.5, r.top + r.height / 2],
        [r.left + r.width * 0.75, r.top + r.height / 2],
      ];
      var blocker = null;
      var tested = 0;
      for (var p = 0; p < pts.length; p++) {
        var x = pts[p][0];
        var y = pts[p][1];
        if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
        tested++;
        var hit = document.elementFromPoint(x, y);
        if (!hit || hit === el || el.contains(hit) || hit.contains(el)) {
          blocker = null;
          break;
        }
        blocker = hit;
      }
      if (blocker && tested > 0) {
        out.push({
          rule: 'occluded',
          selector: sel(el),
          detail: 'buried under ' + sel(blocker),
          text: ownText(el).slice(0, 30),
        });
      }
    }
  }

  /**
   * Run every rule over one scope.
   * @param {string} scopeSel  CSS selector for the surface's root
   */
  window.__uiaudit = function (scopeSel) {
    var root = scopeSel ? document.querySelector(scopeSel) : document.body;
    if (!root) return { error: 'scope not found: ' + scopeSel, findings: [] };
    var vw = document.documentElement.clientWidth;
    var out = [];
    checkOverflow(root, out, vw);
    checkTouch(root, out);
    checkContrast(root, out);
    checkOverlap(root, out);
    checkTextCollision(root, out);
    checkOccluded(root, out);
    return {
      findings: out,
      pageScrollWidth: document.documentElement.scrollWidth,
      viewport: vw,
    };
  };
})();
