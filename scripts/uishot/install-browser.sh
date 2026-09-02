#!/usr/bin/env bash
# ─── scripts/uishot/install-browser.sh ────────────────────────────────────
# Install the screenshot harness's browser OUTSIDE the git tree.
#
# Nothing here touches the repo: no package.json entry, no node_modules in
# the checkout, no system packages. Everything lands in one prefix that can
# be deleted with a single rm -rf.
#
# Three things get installed, because the devbox container is minimal:
#   1. playwright + Chromium          (the browser itself)
#   2. Debian runtime libs            (libX11, libnss3, libgbm … 21 missing)
#   3. fonts + a private fontconfig   (no fonts at all on the host, so
#                                      without this Chromium paints boxes
#                                      and NO text — screenshots come out
#                                      silently wordless)
#
# Usage:   bash scripts/uishot/install-browser.sh
# Prefix:  $SQ_UIBROWSER_HOME, default ~/.cache/sq-uibrowser
set -euo pipefail

PREFIX="${SQ_UIBROWSER_HOME:-$HOME/.cache/sq-uibrowser}"
PW_VERSION="1.49.1"

echo "[uishot] prefix: $PREFIX"
mkdir -p "$PREFIX"
cd "$PREFIX"

# ── 1. playwright + Chromium ───────────────────────────────────────────────
if [ ! -f package.json ]; then
  printf '{\n  "name": "sq-uibrowser",\n  "private": true,\n  "version": "1.0.0"\n}\n' > package.json
fi
echo "[uishot] installing playwright@$PW_VERSION ..."
npm install --silent --no-audit --no-fund "playwright@$PW_VERSION"
export PLAYWRIGHT_BROWSERS_PATH="$PREFIX/browsers"
echo "[uishot] downloading chromium ..."
# The host-requirement validator always fails here (that is exactly what
# step 2 fixes), so its non-zero exit must not abort the install.
npx --yes "playwright@$PW_VERSION" install chromium >/dev/null 2>&1 || true

# ── 2. Debian runtime libs, unpacked into a private sysroot ────────────────
SYSROOT="$PREFIX/sysroot"
if [ ! -d "$SYSROOT/usr/lib/x86_64-linux-gnu" ]; then
  echo "[uishot] downloading Debian runtime libs (no root needed) ..."
  DEB="$PREFIX/debs"
  mkdir -p "$DEB" "$SYSROOT"
  TOP="libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0
       libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1
       libdrm2 libxcb1 libxkbcommon0 libasound2 libglib2.0-0 libxrender1 libxi6
       libcups2 libpango-1.0-0 libcairo2 libexpat1 libxcb-dri3-0 libxshmfence1
       libwayland-client0 fonts-liberation libfontconfig1 libfreetype6"
  # shellcheck disable=SC2086
  CLOSURE=$(apt-cache depends --recurse --no-recommends --no-suggests \
    --no-conflicts --no-breaks --no-replaces --no-enhances $TOP 2>/dev/null \
    | grep '^\w' | sort -u)
  ( cd "$DEB" && apt-get download $CLOSURE >/dev/null 2>&1 || true )
  for f in "$DEB"/*.deb; do dpkg -x "$f" "$SYSROOT" 2>/dev/null || true; done
  echo "[uishot] sysroot: $(du -sh "$SYSROOT" | cut -f1)"
fi

# ── 3. fontconfig pointing at the vendored fonts ───────────────────────────
# The unpacked fonts.conf refers to absolute /usr/share/fonts, which does
# not exist here. Without this file Chromium renders zero glyphs.
mkdir -p "$PREFIX/fontcache"
cp -f "$SYSROOT/etc/fonts/fonts.dtd" "$PREFIX/" 2>/dev/null || true
cat > "$PREFIX/fonts.conf" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>$SYSROOT/usr/share/fonts</dir>
  <cachedir>$PREFIX/fontcache</cachedir>
  <!-- app/web/static/css/01-base.css asks for:
         Inter, system-ui, Segoe UI, Roboto, Arial, sans-serif
       The repo ships no @font-face, so on a real device the first
       INSTALLED family wins. None of these exist here, and without an
       alias fontconfig picks a monospace face and every width the
       harness measures is wrong. -->
  <alias><family>Inter</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>Roboto</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>system-ui</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>-apple-system</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>BlinkMacSystemFont</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>Segoe UI</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>Helvetica Neue</family><prefer><family>Arimo</family></prefer></alias>
  <alias><family>Helvetica</family><prefer><family>Arimo</family></prefer></alias>
  <alias><family>Arial</family><prefer><family>Arimo</family></prefer></alias>
  <alias><family>sans-serif</family><prefer><family>DejaVu Sans</family></prefer></alias>
  <alias><family>serif</family><prefer><family>DejaVu Serif</family></prefer></alias>
  <alias><family>monospace</family><prefer><family>DejaVu Sans Mono</family></prefer></alias>
</fontconfig>
EOF

echo "[uishot] done. total: $(du -sh "$PREFIX" | cut -f1)"
echo "[uishot] run the harness with:  node scripts/uishot/run.mjs"
