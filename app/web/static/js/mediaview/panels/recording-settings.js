// ─── mediaview/panels/recording-settings.js ────────────────────────────────
// "Aufnahme-Settings" tab. Mirrors the cam-edit Erkennung wizard:
// same numeric circles, same icons, same "Gesetzt vs. Erreicht" rows.
// Reads item.recording_settings + item.achievement.
//
// SKELETON — re-exports the existing settings-panel renderer; task #3
// migrates it into a real tab body.

export { lbRenderSettingsPanel } from '../../mediathek/bbox-overlay/settings-panel.js';
