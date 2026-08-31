// ─── mediathek/orchestration.js ────────────────────────────────────────────
// Composition root for the Mediathek package. Owns no logic of its own —
// it re-exports the package's public surface under the one specifier every
// consumer outside mediathek/ already imports, and installs the window.*
// bridges the inline onclicks and the not-yet-migrated modules resolve by
// global name.
//
// R23 split — the 909-line original was carved along its seams; each of
// the five modules below states the concern it owns in its own header:
//   * _cards.js     — tile markup for one item (three branches)
//   * _overview.js  — Level 1, the camera tile grid
//   * _drilldown.js — Level 2, the three openers + close + section title
//   * _paging.js    — page-size math, page slice, grid painter, pagination
//   * _actions.js   — the per-tile delete / confirm handlers
//
// A re-export does NOT put a symbol in this file's scope. Everything the
// window bridges below assign must therefore be imported as well as
// re-exported — hence the paired statements per module.
import { calcItemsPerPage, renderMediaGrid, renderMediaPagination, _goToPage } from './_paging.js';
export {
  _MEDIA_ROWS,
  calcItemsPerPage,
  renderMediaGrid,
  renderMediaPagination,
  _goToPage,
  _ensureProcessingPoll,
  _reflowPageAfterLayout,
  _dropEventAndReslice,
} from './_paging.js';

import { renderMediaOverview } from './_overview.js';
export { renderMediaOverview, _setActiveMocCard, _MOC_ALL_SVG } from './_overview.js';

import {
  openMediaDrilldown,
  openAllMediaDrilldown,
  openCategoryDrilldown,
  closeMediaDrilldown,
  updateMediaSectionTitle,
} from './_drilldown.js';
export {
  openMediaDrilldown,
  openAllMediaDrilldown,
  openCategoryDrilldown,
  closeMediaDrilldown,
  updateMediaSectionTitle,
  _MEDIA_TITLE_SVG,
} from './_drilldown.js';

import { deleteMediaCard, deleteTLCard, confirmMediaCard } from './_actions.js';
export { deleteMediaCard, deleteTLCard, confirmMediaCard } from './_actions.js';

export {
  mediaCardHTML,
  CAM_COLORS,
  camColor,
  getMediaAccentColor,
  fmtMediaDate,
  fmtMediaTimeOnly,
} from './_cards.js';

import { loadMedia } from './media-loader.js';
import { renderMediaFilterPills, _seedTopMediaLabel, _pruneEmptyMediaFilters } from './filters.js';

// hexToRgba lives in core/dom.js next to safeHexColor; _mocChip /
// _buildMocChips in _chips.js. Re-exported here because
// camedit/timelapse-settings.js documents both as part of this module's
// surface.
export { hexToRgba } from '../core/dom.js';
export { _buildMocChips, _mocChip } from './_chips.js';

// ── window.* bridges (Stage 25 D) ───────────────────────────────────────────
// router.js, statistics.js, timeline.js, chrome/storage-stats.js plus
// inline onclicks rendered by mediaCardHTML / renderMediaOverview /
// renderMediaPagination all reach for these by global name. Each
// bridge evaporates when its consumer migrates to a direct import.
window.openMediaDrilldown = openMediaDrilldown;
window.openAllMediaDrilldown = openAllMediaDrilldown;
window.openCategoryDrilldown = openCategoryDrilldown;
window.closeMediaDrilldown = closeMediaDrilldown;
window.loadMedia = loadMedia;
window.renderMediaGrid = renderMediaGrid;
window.renderMediaPagination = renderMediaPagination;
window.renderMediaOverview = renderMediaOverview;
window.renderMediaFilterPills = renderMediaFilterPills;
window.calcItemsPerPage = calcItemsPerPage;
window.updateMediaSectionTitle = updateMediaSectionTitle;
window._pruneEmptyMediaFilters = _pruneEmptyMediaFilters;
window._seedTopMediaLabel = _seedTopMediaLabel;
window._goToPage = _goToPage;
window.deleteMediaCard = deleteMediaCard;
window.deleteTLCard = deleteTLCard;
window.confirmMediaCard = confirmMediaCard;
