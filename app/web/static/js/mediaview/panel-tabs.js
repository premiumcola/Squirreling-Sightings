// ─── mediaview/panel-tabs.js ───────────────────────────────────────────────
// The ONE tab-strip renderer for every MediaView mode. Two long-diverged
// visual languages share this single implementation via `variant`:
//
//   * default  — recorded / weather. A self-contained root holding the
//     strip + ONE lazy content surface (each tab's render(host, ctx) runs
//     on activation, the surface is cleared + re-rendered on switch).
//     Classes: .mv-tabs-root[data-mode] · .mv-tabs-strip · .mv-tab ·
//     .mv-tabs-content (styled by 30d/30g). data-mode colour-codes the
//     active tab per F4 (live=gelb · recorded=grau · weather=blau).
//
//   * ld       — live-detect. The strip mounts into `host` (zone-tabs);
//     N PERSISTENT panels mount into `contentHost` (zone-detail, the sole
//     scroll surface) and toggle .active — the streaming tick writes into
//     the active panel continuously, so panels are caller-populated (via
//     the returned panelEl) + repainted by onChange handlers, never
//     cleared. Adds a fullscreen button, per-tab scroll-memory, and
//     localStorage tab-persistence. Classes: .mv-ld-tab-* (styled by 30f)
//     — kept distinct so the live strip's iOS-tuned CSS is untouched.
//
// Tab descriptor: { id, label, icon?, render?(host, ctx) }. `icon` is a
// function returning inline SVG (ld variant only); `render` is the lazy
// content builder (default variant only).
//
// Returns: { setActive(id), getActive(), panelEl(id), onChange(fn),
//            teardown() }.

// MediaView mode → tab-strip accent (default variant only). Unknown modes
// fall back to neutral 'recorded' grey rather than an un-themed strip.
const _MODE_ACCENT = {
  live: 'live',
  'live-detect': 'live',
  recorded: 'recorded',
  timelapse: 'recorded',
  weather: 'weather',
};

// Per-variant class + behaviour vocabulary. The two sets never mix — a
// renderer instance speaks exactly one of them for its whole lifetime.
function _vocab(variant) {
  if (variant === 'ld') {
    return {
      root: 'mv-ld-tab-bar-root',
      strip: 'mv-ld-tab-bar',
      btn: 'mv-ld-tab-btn',
      dataAttr: 'tabId',
      useActiveClass: true,
      icons: true,
      panel: 'mv-ld-tab-panel',
    };
  }
  return {
    root: 'mv-tabs-root',
    strip: 'mv-tabs-strip',
    btn: 'mv-tab',
    dataAttr: 'tab',
    useActiveClass: false,
    icons: false,
    panel: null,
  };
}

// Generic localStorage access — silent on private-mode / quota errors.
// persistKey is opt-in (ld variant); a null key makes both no-ops, so
// the default variant never touches storage.
function _lsGet(k) {
  try {
    return k ? localStorage.getItem(k) : null;
  } catch {
    return null;
  }
}
function _lsSet(k, v) {
  try {
    if (k) localStorage.setItem(k, v);
  } catch {
    /* quota / private-mode — silent */
  }
}

export function renderPanelTabs(host, tabs, opts = {}) {
  if (!host || !Array.isArray(tabs) || !tabs.length) return null;
  // Replace the strip host's content — matches the prior innerHTML-based
  // render so a re-open on a fresh host never accumulates strips.
  host.innerHTML = '';
  const st = _initState(host, tabs, opts);
  _buildStrip(st);
  _buildSurface(st);
  _activate(st, st.activeId, true);
  return _api(st);
}

// Resolve the runtime state container once; every helper reads/writes it
// by reference so the wiring stays split into small functions.
function _initState(host, tabs, opts) {
  const variant = opts.variant === 'ld' ? 'ld' : 'default';
  const valid = (id) => tabs.some((t) => t.id === id);
  const remembered = _lsGet(opts.persistKey);
  const activeId = valid(remembered)
    ? remembered
    : valid(opts.initialId)
      ? opts.initialId
      : tabs[0].id;
  const handlers = Array.isArray(opts.onChange)
    ? [...opts.onChange]
    : typeof opts.onChange === 'function'
      ? [opts.onChange]
      : [];
  return {
    host,
    tabs,
    opts,
    variant,
    v: _vocab(variant),
    persistent: !!opts.persistentPanels,
    contentHost: opts.contentHost || null,
    scrollSurface: opts.scrollMemory ? opts.scrollSurface || opts.contentHost || null : null,
    accent: _MODE_ACCENT[opts.mode] || 'recorded',
    ctx: opts.ctx || {},
    persistKey: opts.persistKey || null,
    panelIdPrefix: opts.panelIdPrefix || '',
    activeId,
    handlers,
    scrollTops: new Map(),
    panels: {},
    contentEl: null,
    stripRoot: null,
    fsBtn: null,
    fsActive: false,
  };
}

function _buildStrip(st) {
  const { v, tabs, activeId } = st;
  const root = document.createElement('div');
  root.className = v.root;
  if (st.variant === 'default') root.dataset.mode = st.accent;
  const strip = document.createElement('div');
  strip.className = v.strip;
  strip.setAttribute('role', 'tablist');
  for (const t of tabs) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = v.btn;
    btn.dataset[v.dataAttr] = t.id;
    const on = t.id === activeId;
    if (v.useActiveClass) btn.classList.toggle('active', on);
    else btn.dataset.active = on ? '1' : '0';
    btn.innerHTML =
      v.icons && typeof t.icon === 'function' ? `${t.icon()}<span>${t.label}</span>` : t.label;
    btn.addEventListener('click', () => _activate(st, t.id, false));
    strip.appendChild(btn);
  }
  root.appendChild(strip);
  if (st.opts.fullscreen) _buildFsBtn(st, root);
  st.host.appendChild(root);
  st.stripRoot = root;
}

// ld variant only — the expand-to-fullscreen button at the strip's right
// edge. The renderer owns the on/off + icon/aria swap; the caller's
// onToggle(active) owns whatever it collapses (live: the timeline zone).
function _buildFsBtn(st, root) {
  const fs = st.opts.fullscreen;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = fs.btnClass || 'mv-ld-iconbtn mv-ld-fs-btn';
  btn.dataset.active = '0';
  if (fs.expandLabel) btn.setAttribute('aria-label', fs.expandLabel);
  btn.innerHTML = typeof fs.expandIcon === 'function' ? fs.expandIcon() : '';
  btn.addEventListener('click', () => _toggleFs(st));
  root.appendChild(btn);
  st.fsBtn = btn;
}

function _toggleFs(st) {
  const fs = st.opts.fullscreen;
  const btn = st.fsBtn;
  if (!btn) return;
  st.fsActive = !st.fsActive;
  btn.dataset.active = st.fsActive ? '1' : '0';
  const icon = st.fsActive ? fs.collapseIcon : fs.expandIcon;
  btn.innerHTML = typeof icon === 'function' ? icon() : '';
  const label = st.fsActive ? fs.collapseLabel : fs.expandLabel;
  if (label) btn.setAttribute('aria-label', label);
  try {
    fs.onToggle?.(st.fsActive);
  } catch (err) {
    console.warn('[mediaview:tabs] fullscreen toggle failed', err);
  }
}

function _buildSurface(st) {
  if (st.persistent) {
    // Persistent panels (ld) — one per tab, caller-populated, toggled
    // .active. Stable ids (panelIdPrefix + tab.id) so callers + the
    // streaming tick reach them by id.
    for (const t of st.tabs) {
      const panel = document.createElement('div');
      panel.id = st.panelIdPrefix + t.id;
      panel.className = st.v.panel;
      panel.dataset.tabId = t.id;
      if (st.contentHost) st.contentHost.appendChild(panel);
      st.panels[t.id] = panel;
    }
    return;
  }
  // Lazy single content surface (default) — inside the strip root, or a
  // supplied contentHost.
  const content = document.createElement('div');
  content.className = 'mv-tabs-content';
  content.dataset.tabContent = '';
  (st.contentHost || st.stripRoot).appendChild(content);
  st.contentEl = content;
}

function _activate(st, id, initial) {
  if (!st.tabs.some((t) => t.id === id)) return;
  if (id === st.activeId && !initial) return;
  const surf = st.scrollSurface;
  // Save the OUTGOING tab's scroll position before swapping panels.
  if (surf && st.activeId && !initial) st.scrollTops.set(st.activeId, surf.scrollTop);
  st.activeId = id;
  _lsSet(st.persistKey, id);
  st.stripRoot.querySelectorAll('.' + st.v.btn).forEach((b) => {
    const on = b.dataset[st.v.dataAttr] === id;
    if (st.v.useActiveClass) b.classList.toggle('active', on);
    else b.dataset.active = on ? '1' : '0';
  });
  if (st.persistent) {
    for (const t of st.tabs) st.panels[t.id]?.classList.toggle('active', t.id === id);
    if (surf) surf.scrollTop = st.scrollTops.get(id) || 0;
  } else {
    _renderLazy(st);
  }
  _fire(st, id, initial);
}

function _renderLazy(st) {
  const t = st.tabs.find((x) => x.id === st.activeId);
  if (!t || !st.contentEl) return;
  st.contentEl.innerHTML = '';
  if (typeof t.render !== 'function') return;
  try {
    t.render(st.contentEl, st.ctx);
  } catch (err) {
    console.warn('[mediaview:tabs] render failed for', t.id, err);
  }
}

function _fire(st, id, initial) {
  for (const h of st.handlers) {
    try {
      h(id, initial);
    } catch (err) {
      console.warn('[mediaview:tabs] change handler error', err);
    }
  }
}

function _api(st) {
  return {
    setActive: (id) => _activate(st, id, false),
    getActive: () => st.activeId,
    // Persistent panel for ld; the lazy content surface otherwise.
    panelEl: (id) => st.panels[id] || st.contentEl || null,
    onChange: (fn) => {
      if (typeof fn === 'function') st.handlers.push(fn);
    },
    teardown: () => {
      try {
        st.stripRoot?.remove();
      } catch {
        /* already detached */
      }
      for (const id in st.panels) {
        try {
          st.panels[id]?.remove();
        } catch {
          /* already detached */
        }
      }
      st.handlers.length = 0;
      st.scrollTops.clear();
    },
  };
}
