// ─── scripts/uishot/_report.mjs ────────────────────────────────────────────
// Printing. This is a CLI tool, so it writes to stdout on purpose —
// CLAUDE.md's no-console rule is about the shipped frontend under
// app/web/static/js, which is also the only tree eslint walks.

const RULE_LABEL = {
  occluded: 'text buried under something else',
  overflow: 'overflows viewport',
  textcollide: 'text printed over text',
  overlap: 'in-flow siblings overlap',
  contrast: 'contrast below 4.5:1',
  touch: 'touch target under 44px',
};

const RULE_ORDER = ['occluded', 'overflow', 'textcollide', 'overlap', 'contrast', 'touch'];

/**
 * Console noise the harness causes itself: the two CDN <script> tags it
 * aborts on purpose, and the service worker that has no route here.
 * Filtering them keeps a real app error visible instead of buried.
 */
const HARNESS_NOISE = [
  'net::ERR_FAILED',
  'bad HTTP response code (404) was received when fetching the script',
  'Failed to register a ServiceWorker',
];

function appErrors(list) {
  return list.filter((m) => !HARNESS_NOISE.some((n) => m.includes(n)));
}

/** Collapse repeats of the same rule+selector across one surface. */
function dedupe(findings) {
  const seen = new Map();
  for (const f of findings) {
    const key = `${f.rule}|${f.selector}|${f.detail}`;
    if (!seen.has(key)) seen.set(key, { ...f, count: 1 });
    else seen.get(key).count += 1;
  }
  return [...seen.values()];
}

/** One surface × width block. */
export function printShot(shot) {
  const head = `${shot.surface} @ ${shot.width}px`;
  process.stdout.write(`\n  ${head}\n    png: ${shot.png}\n`);
  if (shot.error) {
    process.stdout.write(`    MOUNT FAILED: ${shot.error}\n`);
    return;
  }
  for (const msg of appErrors(shot.consoleErrors).slice(0, 4)) {
    process.stdout.write(`    console: ${msg.slice(0, 160)}\n`);
  }
  const items = dedupe(shot.findings);
  if (!items.length) {
    process.stdout.write('    no violations\n');
    return;
  }
  const byRule = {};
  for (const f of items) (byRule[f.rule] ||= []).push(f);
  for (const rule of RULE_ORDER) {
    const list = byRule[rule];
    if (!list) continue;
    process.stdout.write(`    ${RULE_LABEL[rule]} (${list.length}):\n`);
    for (const f of list.slice(0, 12)) {
      const n = f.count > 1 ? ` ×${f.count}` : '';
      const t = f.text ? `  "${f.text}"` : '';
      process.stdout.write(`      ${f.selector}${n}\n        ${f.detail}${t}\n`);
    }
    if (list.length > 12) process.stdout.write(`      … ${list.length - 12} more\n`);
  }
}

/** Closing tally across every shot. */
export function printSummary(shots, outDir) {
  const tally = {};
  let failed = 0;
  for (const s of shots) {
    if (s.error) failed += 1;
    for (const f of dedupe(s.findings)) tally[f.rule] = (tally[f.rule] || 0) + 1;
  }
  process.stdout.write('\n' + '─'.repeat(64) + '\n');
  process.stdout.write(`  ${shots.length} shots -> ${outDir}\n`);
  const line = RULE_ORDER.map((r) => `${r} ${tally[r] || 0}`).join(' · ');
  process.stdout.write(`  ${line}${failed ? ` · ${failed} mount failures` : ''}\n`);
  process.stdout.write('  These are findings, not a gate. Look at the PNGs.\n');
}
