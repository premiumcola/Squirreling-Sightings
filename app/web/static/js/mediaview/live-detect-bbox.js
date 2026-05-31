// ─── mediaview/live-detect-bbox.js ─────────────────────────────────────────
// The verdict-styled bbox SVG overlay + the letterbox positioner that aligns
// every overlay layer to the visible image rect. Its own file (the renderer is
// large); trails/zone reuse _positionSvgOverImage from here. Reads state via S.
import { byId, esc } from '../core/dom.js';
import { OBJ_LABEL, colors } from '../core/icons.js';
import { fittedRect } from '../core/video-fit.js';
import { zoneEl } from './live-detect-skeleton.js';
import { S } from './live-detect-state.js';
import { _debugDiagOn, _updateDiagStrip, _refreshMediaRow, _collectBboxDiagFields, _renderDiagStrip } from './live-detect-diag.js';
import { _ensureBboxOverlay, _updateSuppressedHint } from './live-detect-overlays.js';
import { _renderDetailPill } from './live-detect-panels.js';
import { _HOLD_MS_CEILING } from './live-detect.js';

export function _renderBboxOverlay() {
  // SIMU-FIX-03b · the bbox SVG's visibility is gated SOLELY by the
  // `S.overlays.bboxes` boolean. The floating-pill bar's own
  // visibility (controlled separately via SIMU-02c's tap toggle)
  // never affects this render path — the pill bar is a CONTROL for
  // the boolean, never a GATE for the painting.
  const svg = _ensureBboxOverlay();
  if (!svg || !S.session) return;
  svg.style.display = S.overlays.bboxes ? 'block' : 'none';
  if (!S.overlays.bboxes) {
    svg.innerHTML = '';
    _updateSuppressedHint(0);
    return;
  }
  const fs = S.session.lastFrameSize || { w: 1920, h: 1080 };
  svg.setAttribute('viewBox', `0 0 ${fs.w} ${fs.h}`);
  _positionSvgOverImage(svg);
  // A1/A3 · refresh the debug strip on every render so the user
  // can screenshot it on iPhone without DevTools. No-op when the
  // Debug pill is off — _updateDiagStrip / _refreshMediaRow gate on
  // _debugDiagOn() so non-debug sessions pay zero cost.
  _refreshMediaRow();
  if (_debugDiagOn()) {
    const fields = _collectBboxDiagFields(svg, fs);
    _updateDiagStrip('bbox', fields.fields, fields.opts);
  }
  const rect = svg.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) {
    _updateDiagStrip('position-fail', {
      svg: svg.id,
      svgRect: `${Math.round(rect.width)}×${Math.round(rect.height)}`,
    });
    svg.innerHTML = '';
    return;
  }
  // A1 · clear any sticky position-fail from the last cycle now
  // that the SVG has a real size again. Same for paint-fail
  // (rebuilt below if needed).
  if (S.diagState.posFail) {
    S.diagState.posFail = null;
    _renderDiagStrip();
  }
  // gp384 / C84 — hold-time merge. Prefer the live tick's detections
  // (full opacity, _holdAge=0). If the tick is empty, fall back to
  // the most recent detection per label from S.detBuffer — each
  // entry carries its age so the render can fade the bbox out over
  // the active hold-time (dynamic per cadence — see C84). One entry
  // per label is enough; older entries on the same label are
  // dominated by the most-recent one's opacity anyway. holdMs falls
  // back to the legacy 1500 ms ceiling until the first cycle EMA
  // observation lands, so the first tick still gets a sensible hold.
  const now = Date.now();
  const holdMs = Number.isFinite(S.holdMsActive) ? S.holdMsActive : _HOLD_MS_CEILING;
  const liveDets = S.session.lastDetections || [];
  let renderDets;
  if (liveDets.length) {
    renderDets = liveDets.map((d) => ({ ...d, _holdAge: 0 }));
  } else {
    const seen = new Set();
    const held = [];
    for (let i = S.detBuffer.length - 1; i >= 0; i--) {
      const e = S.detBuffer[i];
      const age = now - e.ms;
      if (age > holdMs) break; // S.detBuffer is push-order → older entries follow
      if (seen.has(e.label)) continue; // one bbox per label, most-recent wins
      seen.add(e.label);
      held.push({
        label: e.label,
        score: e.score,
        bbox: e.bbox,
        verdict: e.verdict,
        _holdAge: age,
        track_num: e.track_num,
      });
    }
    renderDets = held;
  }
  // wv612 — verdict-aware rendering. Backend's test-detection
  // endpoint already tags each detection with a verdict — pass /
  // belowthresh / filtered (class not in object_filter). Render each
  // state with a visually distinct style so the user can SEE which
  // detections passed the gates and which were rejected:
  //   pass         → solid stroke, full opacity, "label · NN %"
  //   belowthresh  → solid stroke at 0.55 opacity, "label · unter Schwelle"
  //   filtered     → grey-toned dashed stroke at 0.45 opacity,
  //                  "label · gefiltert" (class-disabled by filter)
  // A small legend below the toggle row only renders while at least
  // one non-pass bbox is currently on screen.
  let _hasSuppressed = false;
  svg.innerHTML = renderDets
    .map((d) => {
      const baseC = colors[d.label] || colors.unknown;
      const isPass = d.verdict === 'pass';
      const isBelow = d.verdict === 'belowthresh';
      const isFiltered = !isPass && !isBelow; // 'filtered' or absent
      if (!isPass) _hasSuppressed = true;
      const c = isFiltered ? '#94a3b8' : baseC; // slate-grey for class-filtered
      const verdictOp = isPass ? 1 : isBelow ? 0.55 : 0.45;
      const holdMul = d._holdAge > 0 ? Math.max(0, 1 - d._holdAge / holdMs) : 1;
      const op = verdictOp * holdMul;
      const dash = isFiltered ? '12 8' : isBelow ? '6 6' : 'none';
      const [x, y, bw, bh] = d.bbox;
      const lbl = OBJ_LABEL[d.label] || d.label;
      const suffix = isPass
        ? `${Math.round((d.score || 0) * 100)} %`
        : isBelow
          ? 'unter Schwelle'
          : 'gefiltert';
      const stroke = S.selectedLabel === d.label ? 5 : 3;
      const dashAttr = dash === 'none' ? '' : ` stroke-dasharray="${dash}"`;
      // SIMU-02e · track-number badge anchored to the bbox top-left.
      // When the backend hands us a track_num, the visible label
      // drops the class word ("Person · 67 %" → "67 %") because the
      // badge already carries identity. Without a track_num, fall
      // back to the original "label · suffix" so nothing regresses.
      const trackNum = Number.isFinite(d.track_num) ? d.track_num : null;
      const hasBadge = trackNum != null && trackNum > 0;
      const labelTxt = hasBadge ? suffix : `${lbl} · ${suffix}`;
      const labelStartX = hasBadge ? x + 26 : x + 4;
      const labelY = hasBadge ? y - 2 : y + 20;
      const labelSize = hasBadge ? 11 : 14;
      const badgeSvg = hasBadge
        ? `<rect x="${x}" y="${y - 12}" width="22" height="12" rx="2" ry="2" fill="${c}" stroke="none"/>
      <text x="${x + 11}" y="${y - 3}" text-anchor="middle" fill="#0b0f14" font-size="9" font-family="system-ui, sans-serif" font-weight="700">#${trackNum}</text>`
        : '';
      return `<g opacity="${op.toFixed(2)}" data-label="${esc(d.label)}" style="pointer-events:auto;cursor:pointer">
      <rect x="${x}" y="${y}" width="${bw}" height="${bh}" fill="none" stroke="${c}" stroke-width="${stroke}" vector-effect="non-scaling-stroke"${dashAttr}/>
      ${badgeSvg}
      <text x="${labelStartX}" y="${labelY}" fill="${c}" font-size="${labelSize}" font-family="system-ui, sans-serif" font-weight="700" paint-order="stroke" stroke="rgba(0,0,0,0.7)" stroke-width="3">${esc(labelTxt)}</text>
    </g>`;
    })
    .join('');
  // D52 · count non-pass dets currently on the canvas so the
  // muted "<n> verworfen — antippen" line can show. _hasSuppressed
  // already flagged the existence; the count is the bare arithmetic.
  const _nonPass = renderDets.reduce((n, d) => n + (d.verdict === 'pass' ? 0 : 1), 0);
  _updateSuppressedHint(_nonPass);
  // A4 · paint-fail check. The SVG itself has size > 0 (we'd have
  // hit the position-fail branch above otherwise), but the painted
  // children might still collapse to 0×0 — happens when the bbox
  // coords land outside the viewBox or when stroke-only rects had
  // their geometry attrs clobbered. Differentiates "SVG sized
  // correctly but children collapsed" from "SVG never got
  // dimensions" — same visual failure, different fix.
  if (renderDets.length > 0) {
    const firstG = svg.firstElementChild;
    const childRect = firstG ? firstG.getBoundingClientRect() : null;
    if (childRect && childRect.width === 0 && childRect.height === 0) {
      const first = renderDets[0];
      const fs = S.session.lastFrameSize || { w: 0, h: 0 };
      _updateDiagStrip('paint-fail', {
        childRect: '0×0',
        parentRect: `${Math.round(rect.width)}×${Math.round(rect.height)}`,
        viewBox: `${fs.w}×${fs.h}`,
        bboxRaw: `[${(first.bbox || []).join(',')}]`,
      });
    } else if (S.diagState.paintFail) {
      S.diagState.paintFail = null;
      _renderDiagStrip();
    }
  } else if (S.diagState.paintFail) {
    S.diagState.paintFail = null;
    _renderDiagStrip();
  }
  // Click handler — toggle detail-pill selection.
  svg.style.pointerEvents = 'auto';
  svg.querySelectorAll('[data-label]').forEach((g) => {
    g.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const lbl = g.dataset.label;
      S.selectedLabel = S.selectedLabel === lbl ? null : lbl;
      _renderBboxOverlay();
      _renderDetailPill();
    });
  });
}

// Position an overlay SVG to cover the IMAGE's visible rect, not the
// whole #lightboxMediaWrap. The image uses object-fit:contain so its
// on-screen rect is letterboxed inside the wrap; without this
// correction every overlay SVG (bboxes / zones / masks) covers the
// wrap and preserveAspectRatio:meet letterboxes the content inside
// the WRAP bounds — polygons land tiny in the corner on 32:9
// monitors and miss the actual pixels. fittedRect is the canonical
// "where does the media really sit inside this element" helper;
// same math drives the canvas zone overlay in the Mediathek +
// Wetter-TL paths.
export function _positionSvgOverImage(svg) {
  // SIMU-FIX-04a · fast path for the SIMU-01 layout. When the SVG
  // sits inside zone-video (the normal case after FIX-04a's
  // `_ensureOverlayLayer` always parents there), just fill the zone
  // — zone-video has aspect-ratio:16/9 and the <video> element fills
  // it identically, so dx=dy=0 / width=100% / height=100% is
  // correct without any getBoundingClientRect math. The SVG's
  // `preserveAspectRatio="xMidYMid meet"` handles any source-aspect
  // mismatch INSIDE the SVG, so non-16:9 cameras (rare) still letter-
  // box correctly. The legacy delta-math path below stays for the
  // recorded-clip lightbox where the wrap layout differs.
  const zoneVid = zoneEl('video');
  if (zoneVid && svg.parentElement === zoneVid) {
    svg.style.left = '0';
    svg.style.top = '0';
    svg.style.width = '100%';
    svg.style.height = '100%';
    svg.style.right = 'auto';
    svg.style.bottom = 'auto';
    svg.style.inset = '0';
    _setMediaBranch('zone-video-fill');
    S.lastVideoRejected = null;
    S.lastImgRejected = null;
    return;
  }
  // Pick whichever media element is currently visible. HLS path
  // uses `<video>` (iOS + desktop hls.js); MJPEG fallback uses
  // `<img>`. Both honour object-fit:contain so the SVG must align
  // to whichever element actually carries the pixels.
  //
  // B19' · video valid only when display!='none' AND videoWidth>0
  // AND readyState>=2 (HAVE_CURRENT_DATA — actual frame decoded,
  // not just metadata). Image valid unless naturalWidth==0 AND
  // complete==false (browser is still fetching the first byte).
  // Rejection reasons are stashed so the MEDIA debug row can show
  // exactly WHY a candidate was skipped on a half-mounted session.
  const videoEl = byId('lightboxVideo');
  const imgEl = byId('lightboxImg');
  // SIMU-01 · the SVG's positioned ancestor is now zone-video (not
  // #lightboxMediaWrap). Use the SVG's parent rect as the reference
  // so dx/dy land in the right coordinate space whether the parent
  // is the new zone or the legacy wrap.
  const wrap = svg.parentElement || byId('lightboxMediaWrap');
  if (!wrap) {
    _setMediaBranch('skipped-no-wrap');
    S.lastVideoRejected = null;
    S.lastImgRejected = null;
    return;
  }
  // Video validity.
  let videoValid = false;
  let videoRejected = null;
  if (!videoEl) {
    videoRejected = 'no-el';
  } else if (videoEl.style.display === 'none') {
    videoRejected = 'display=none';
  } else if (!videoEl.videoWidth) {
    videoRejected = `videoWidth=0 readyState=${videoEl.readyState || 0}`;
  } else if ((videoEl.readyState || 0) < 2) {
    videoRejected = `readyState=${videoEl.readyState || 0}`;
  } else {
    videoValid = true;
  }
  // Image validity. B19' tightens to also reject "not loaded yet"
  // (naturalWidth=0 AND complete=false). Note: complete is true on
  // multipart-replace MJPEG even when naturalWidth=0, so the AND is
  // the right join — img with complete=true is usable for layout
  // measurement even if the natural dimensions read zero.
  let imgValid = false;
  let imgRejected = null;
  if (!imgEl) {
    imgRejected = 'no-el';
  } else if (imgEl.style.display === 'none') {
    imgRejected = 'display=none';
  } else if ((imgEl.naturalWidth || 0) === 0 && !imgEl.complete) {
    imgRejected = 'naturalWidth=0 complete=false';
  } else {
    imgValid = true;
  }
  S.lastVideoRejected = videoValid ? null : videoRejected;
  S.lastImgRejected = imgValid ? null : imgRejected;
  const mediaEl = videoValid ? videoEl : imgValid ? imgEl : null;
  const wrapBox = wrap.getBoundingClientRect();
  if (wrapBox.width <= 0) {
    _setMediaBranch('skipped-no-wrap');
    return;
  }
  const imgBox = mediaEl ? mediaEl.getBoundingClientRect() : null;
  let dx, dy, w, h;
  let branch;
  if (mediaEl && imgBox.width > 0 && imgBox.height > 0) {
    const fit = fittedRect(mediaEl);
    // fit is relative to the img's content box; the img's content
    // box top-left = imgBox.top/left - wrapBox.top/left.
    dx = imgBox.left - wrapBox.left + fit.x;
    dy = imgBox.top - wrapBox.top + fit.y;
    w = fit.w;
    h = fit.h;
    branch = mediaEl === videoEl ? 'video-rect' : 'img-rect';
    if (w <= 0 || h <= 0) {
      // fittedRect returned 0×0 (image laid out but naturalWidth=0,
      // the MJPEG case on Safari). Fall through to aspect-fallback
      // below — DO NOT cover the full wrap height: the wrap also
      // contains the toggle pills row, and covering the full wrap
      // pushes the SVG below the image by exactly the toggle-row
      // height. That's the y=242 offset the screenshot showed.
      dx = null;
    }
  }
  if (dx == null) {
    // B19 · aspect-correct fallback. The wrap may be TALLER than
    // the visible image (toggle pills stacked below it). The image
    // itself is letterboxed inside its own slot via object-fit:
    // contain, but we don't know that slot's height directly. We DO
    // know the source aspect (fs.w / fs.h), so we compute the SVG
    // height as wrap.width * fs.h / fs.w, pin to top:0, and let the
    // SVG's preserveAspectRatio:meet finish the letterbox math.
    const fs = S.session?.lastFrameSize;
    dx = 0;
    dy = 0;
    w = wrapBox.width;
    if (fs && fs.w > 0 && fs.h > 0) {
      h = (wrapBox.width * fs.h) / fs.w;
      branch = 'wrap-fallback-aspect';
    } else {
      // No frame size known yet — first tick hasn't returned.
      // Cover the full wrap (legacy behaviour) so the SVG is at
      // least visible somewhere. Surface this as a distinct branch
      // so the user sees it on the media row and knows the fix is
      // "wait for the first tick".
      h = wrapBox.height;
      branch = 'wrap-fallback-full';
    }
  }
  svg.style.left = `${dx}px`;
  svg.style.top = `${dy}px`;
  svg.style.width = `${w}px`;
  svg.style.height = `${h}px`;
  svg.style.right = 'auto';
  svg.style.bottom = 'auto';
  svg.style.inset = 'auto';
  _setMediaBranch(branch);
}

// B19 / B19' · stash the branch + per-candidate rejection reasons
// that _positionSvgOverImage produced so the next _refreshMediaRow()
// pickup includes them without an extra plumbing arg. Plain module-
// level scratch — the position helper writes them, the media-row
// builder reads them.
export function _setMediaBranch(branch) {
  S.lastMediaBranch = branch;
}

// Per-label trail cap — newest N centroids drawn behind the bbox.
// Matches the batch-A Mediathek trail (mediaview/canvas/trail-layer.js)
// so the recorded and live UIs read identically.
export const _LIVE_TRAIL_MAX_POINTS = 20;

// Trails layer. Connects per-label bbox centroids from the 60 s
// S.detBuffer window into a fading polyline. Visual matches the
// batch-A Mediathek trail (last N points, linear opacity ramp,
// solid head-dot) via the shared `buildTrailSvg` helper —
// recorded clips and live simulation render trails the same way.
