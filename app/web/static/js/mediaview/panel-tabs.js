// ─── mediaview/panel-tabs.js ───────────────────────────────────────────────
// Dark panel-tab strip + active-content surface. Renders into a host
// element supplied by the shell. Active tab and inactive tabs sit on
// the same near-black #0a0e1a surface so the strip + active content
// read as one continuous zone — no border between the tab pill and
// the content beneath it.
//
// Tab descriptor shape:
//   { id, label, render(host, ctx) }
//
// Where `id` is a stable key, `label` is the visible chip text, and
// `render` mounts the tab's content into `host`. Each tab is mounted
// lazily on first activation and torn down by the shell on close.
//
// CSS classes the renderer emits (styled by 30-lightbox-video.css when
// the shell becomes the active mode):
//   .mv-tabs-root   — outer container
//   .mv-tabs-root[data-mode] — per-mode accent colour for the active
//                    tab (live=gelb · recorded=grau · weather=blau)
//   .mv-tabs-strip  — the tab strip
//   .mv-tab         — one tab pill
//   .mv-tab[data-active="1"] — the active tab
//   .mv-tabs-content — the active-tab content block

// MediaView mode → tab-strip accent. F4 colour-codes the panel tabs so
// the operator reads which player they're in at a glance: live is
// yellow, recorded grey, weather blue. Live-detect rides on 'live'.
const _MODE_ACCENT = {
  live: 'live',
  'live-detect': 'live',
  recorded: 'recorded',
  timelapse: 'recorded',
  weather: 'weather',
};

export function renderPanelTabs(host, tabs, opts = {}) {
  if (!host) return null;
  const initialId = opts.initialId || (tabs[0] && tabs[0].id);
  let activeId = initialId;
  // F4 · colour-code by mode. Unknown modes fall back to the neutral
  // 'recorded' grey rather than an un-themed strip.
  const accent = _MODE_ACCENT[opts.mode] || 'recorded';
  const tabsHtml = tabs
    .map(
      (t) =>
        `<button type="button" class="mv-tab" data-tab="${t.id}" data-active="${t.id === activeId ? '1' : '0'}">${t.label}</button>`,
    )
    .join('');
  host.innerHTML = `
    <div class="mv-tabs-root" data-mode="${accent}">
      <div class="mv-tabs-strip" role="tablist">${tabsHtml}</div>
      <div class="mv-tabs-content" data-tab-content></div>
    </div>`;
  const contentHost = host.querySelector('[data-tab-content]');
  const renderActive = () => {
    const t = tabs.find((x) => x.id === activeId);
    if (!t || !contentHost) return;
    contentHost.innerHTML = '';
    try {
      t.render(contentHost, opts.ctx || {});
    } catch (err) {
      console.warn('[mediaview:tabs] render failed for', t.id, err);
    }
  };
  host.querySelectorAll('.mv-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.tab;
      if (!id || id === activeId) return;
      activeId = id;
      host.querySelectorAll('.mv-tab').forEach((b) => {
        b.dataset.active = b.dataset.tab === activeId ? '1' : '0';
      });
      renderActive();
    });
  });
  renderActive();
  return {
    setActive(id) {
      if (!tabs.find((x) => x.id === id) || id === activeId) return;
      activeId = id;
      host.querySelectorAll('.mv-tab').forEach((b) => {
        b.dataset.active = b.dataset.tab === activeId ? '1' : '0';
      });
      renderActive();
    },
    getActive() {
      return activeId;
    },
  };
}
