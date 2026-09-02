#!/usr/bin/env node
// ─── scripts/uishot/run.mjs ────────────────────────────────────────────────
// Photograph the real UI at real phone widths, and audit what it renders.
//
//     node scripts/uishot/run.mjs [surface-id ...]
//
// This exists because every UI change in this repo used to be verified by
// reading CSS and reasoning about it — there was no browser anywhere in
// the toolchain — and defects that are obvious in one glance shipped
// repeatedly. It is a TOOL, not a gate: it is wired into no CI workflow,
// no pre-commit hook and no npm script, and a missing browser exits 3
// with an install command rather than a stack trace.
//
// The browser lives outside the git tree (scripts/uishot/install-browser.sh);
// package.json gains nothing.

import { spawnSync } from 'node:child_process';
import { mkdirSync, existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { launchBrowser, browserHome, missingBrowserMessage } from './_browser.mjs';
import { startServer } from './_server.mjs';
import { SURFACES, seedFixtures } from './_surfaces.mjs';
import { installStubs } from './_stubs.mjs';
import { ensureClip } from './_clip.mjs';
import { printShot, printSummary } from './_report.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..');
const STATIC_DIR = join(REPO, 'app', 'web', 'static');
const OUT_DIR = join(REPO, '.uishots');
const WIDTHS = [375, 393, 1440];

/** Run a repo script, echoing failures. */
function run(cmd, args) {
  const r = spawnSync(cmd, args, { cwd: REPO, encoding: 'utf8' });
  if (r.status !== 0) process.stdout.write(`  [warn] ${cmd} ${args.join(' ')}: ${r.stderr || ''}\n`);
  return r;
}

/** Locate playwright's bundled ffmpeg inside the prefix. */
function ffmpegPath(prefix) {
  const dir = join(prefix, 'browsers');
  if (!existsSync(dir)) return '';
  const hit = readdirSync(dir).find((d) => d.startsWith('ffmpeg-'));
  return hit ? join(dir, hit, 'ffmpeg-linux') : '';
}

/** Shoot one surface at one width. */
async function shoot(browser, baseUrl, surface, width, auditSrc) {
  const page = await browser.newPage({
    viewport: { width, height: width < 500 ? 780 : 900 },
    deviceScaleFactor: 2,
    colorScheme: 'dark',
    isMobile: width < 500,
    hasTouch: width < 500,
  });
  const consoleErrors = [];
  page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));
  page.on('pageerror', (e) => consoleErrors.push(String(e)));
  await installStubs(page);

  const png = join(OUT_DIR, `${surface.id}-${width}.png`);
  const shotRec = { surface: surface.id, width, png, findings: [], consoleErrors, error: null };
  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(400);
    await seedFixtures(page);
    await surface.mount(page, width);
    const target = await page.$(surface.clip);
    if (target) await target.screenshot({ path: png });
    else await page.screenshot({ path: png, fullPage: false });
    await page.addScriptTag({ content: auditSrc });
    const res = await page.evaluate((s) => window.__uiaudit(s), surface.scope);
    shotRec.findings = res.findings || [];
    shotRec.scopeError = res.error || null;
  } catch (err) {
    shotRec.error = String(err).split('\n')[0];
    await page.screenshot({ path: png, fullPage: false }).catch(() => {});
  }
  await page.close();
  return shotRec;
}

async function main() {
  const only = process.argv.slice(2).filter((a) => !a.startsWith('-'));
  const wanted = only.length ? SURFACES.filter((s) => only.includes(s.id)) : SURFACES;
  if (!wanted.length) {
    process.stdout.write(`unknown surface. known: ${SURFACES.map((s) => s.id).join(', ')}\n`);
    return 2;
  }

  mkdirSync(OUT_DIR, { recursive: true });
  process.stdout.write('[uishot] building app.css from the real LOAD_ORDER ...\n');
  run('python3', ['scripts/build_css.py']);
  const shell = join(OUT_DIR, '_shell.html');
  process.stdout.write('[uishot] rendering the real index.html + partials ...\n');
  run('python3', ['scripts/uishot/render_shell.py', shell]);

  let browser;
  let prefix;
  try {
    ({ browser, prefix } = await launchBrowser());
  } catch (err) {
    if (err.code === 'ENOBROWSER') {
      process.stdout.write(err.message);
      return 3;
    }
    process.stdout.write(`\n  Browser failed to launch from ${browserHome()}\n`);
    process.stdout.write(`  ${String(err).split('\n')[0]}\n`);
    process.stdout.write(missingBrowserMessage(browserHome()));
    return 3;
  }

  const clip = join(STATIC_DIR, 'uishot-clip.webm');
  if (!(await ensureClip(browser, ffmpegPath(prefix), clip))) {
    process.stdout.write('  [warn] no stand-in clip — the player timeline will read duration 0\n');
  }
  const server = await startServer(STATIC_DIR, shell);
  const auditSrc = readFileSync(join(HERE, '_inpage-audit.js'), 'utf8');

  const shots = [];
  for (const surface of wanted) {
    process.stdout.write(`\n■ ${surface.title}`);
    for (const width of WIDTHS) {
      const rec = await shoot(browser, server.url, surface, width, auditSrc);
      shots.push(rec);
      printShot(rec);
    }
  }
  printSummary(shots, OUT_DIR);

  await browser.close();
  await server.close();
  return 0;
}

main().then((code) => process.exit(code));
