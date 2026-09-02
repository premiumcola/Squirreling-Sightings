// ─── sichtungen/index.js ─────────────────────────────────────────────────
// Public API + composition for the Sichtungen panel — the medal grid,
// its (now header-hosted) legend, the mammal clips-only drilldown, the
// redesigned bird species dossier, and the quest pinboard/upcoming/
// archive. Former sichtungen.js monolith, split per CLAUDE.md's file
// size budget (it had grown to 709 lines against a 400-line ceiling).
//
// window.* bridges live here rather than in each sub-module: the
// drilldown functions need the achievement grid's own renderAchievements
// as a callback (so a mammal drilldown open/close can repaint the grid's
// active-card highlight) without _drilldown.js importing _achievements.js
// — that would create the exact cycle _achievements.js's own import of
// _drilldown.js (for _currentAchOpenId) is on the other side of.
import { j } from '../core/api.js';
import { renderAchievements, setAchievementsData } from './_achievements.js';
import {
  toggleAchDrilldown as _toggleAchDrilldownImpl,
  closeAchDrilldown as _closeAchDrilldownImpl,
  loadMoreAchDrill,
} from './_drilldown.js';
import {
  loadBirdDossiers,
  selectSpeciesDossierByName as _selectSpeciesDossierImpl,
} from './_dossier-panel.js';
import {
  setQuestsData,
  renderQuestsPinboard,
  renderQuestsUpcoming,
  renderQuestsArchive,
} from './_quests.js';

window.toggleAchDrilldown = (id, name) => _toggleAchDrilldownImpl(id, name, renderAchievements);
window.closeAchDrilldown = () => _closeAchDrilldownImpl(renderAchievements);
window.loadMoreAchDrill = loadMoreAchDrill;
// Same shape as the drilldown bridges above: the dossier panel gets
// renderAchievements as its repaint callback so a bird tile's own active
// highlight follows the panel opening AND closing (tapping the open
// species again closes it), without _dossier-panel.js importing
// _achievements.js and closing an import cycle.
window.selectSpeciesDossierByName = (name) => _selectSpeciesDossierImpl(name, renderAchievements);
// Legacy name kept so any lingering inline callers don't break.
window.openAchievementDrilldown = (id, name) => window.toggleAchDrilldown(id, name);

export async function loadAchievements() {
  let achData = {};
  let questsData = {};
  let questsUpcoming = [];
  let questsArchive = {};
  try {
    const r = await j('/api/achievements');
    achData = r.achievements || {};
    questsData = r.quests || (r.achievements && r.achievements.quests) || {};
    questsUpcoming = Array.isArray(r.upcoming) ? r.upcoming : [];
    questsArchive = r.quests_archive || {};
  } catch {
    // Defaults above already cover the failure case.
  }
  setAchievementsData(achData);
  setQuestsData(questsData, questsUpcoming, questsArchive);
  renderAchievements();
  renderQuestsPinboard();
  renderQuestsUpcoming();
  renderQuestsArchive();
}
window.loadAchievements = loadAchievements;

export { loadBirdDossiers };
window.loadBirdDossiers = loadBirdDossiers;
