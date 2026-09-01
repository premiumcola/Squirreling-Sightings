// ─── sichtungen/_ach-defs.js ────────────────────────────────────────────
// Pure data + tier helpers for the Achievements / Sichtungen grid — no
// DOM, no fetch. Split out of the former sichtungen.js monolith so the
// grid data (ACH_DEFS) and the tier math (_achTier / _rarityText) can be
// imported by both _achievements.js (the grid renderer) and
// _dossier-panel.js (the redesigned species dossier, which needs
// _achTier for its own bronze/silver/gold badge) without either
// importing the other.

// Top 20 Bavarian garden birds (LBV Stunde der Gartenvögel 2025 Bayern),
// sorted by frequency (most common first). freq values drive rarity pills.
export const ACH_DEFS = [
  {
    id: 'haussperling',
    name: 'Haussperling',
    icon: '🐦',
    cat: 'birds',
    freq: 'sehr haeufig',
    rank: 1,
  },
  { id: 'amsel', name: 'Amsel', icon: '🐦', cat: 'birds', freq: 'sehr haeufig', rank: 2 },
  { id: 'kohlmeise', name: 'Kohlmeise', icon: '🐦', cat: 'birds', freq: 'sehr haeufig', rank: 3 },
  { id: 'star', name: 'Star', icon: '🐦', cat: 'birds', freq: 'haeufig', rank: 4 },
  { id: 'feldsperling', name: 'Feldsperling', icon: '🐦', cat: 'birds', freq: 'haeufig', rank: 5 },
  { id: 'blaumeise', name: 'Blaumeise', icon: '🐦', cat: 'birds', freq: 'haeufig', rank: 6 },
  { id: 'ringeltaube', name: 'Ringeltaube', icon: '🐦', cat: 'birds', freq: 'haeufig', rank: 7 },
  { id: 'mauersegler', name: 'Mauersegler', icon: '🐦', cat: 'birds', freq: 'haeufig', rank: 8 },
  { id: 'elster', name: 'Elster', icon: '🐦', cat: 'birds', freq: 'regelmaessig', rank: 9 },
  {
    id: 'mehlschwalbe',
    name: 'Mehlschwalbe',
    icon: '🐦',
    cat: 'birds',
    freq: 'regelmaessig',
    rank: 10,
  },
  { id: 'buchfink', name: 'Buchfink', icon: '🐦', cat: 'birds', freq: 'regelmaessig', rank: 11 },
  {
    id: 'rotkehlchen',
    name: 'Rotkehlchen',
    icon: '🐦',
    cat: 'birds',
    freq: 'regelmaessig',
    rank: 12,
  },
  { id: 'gruenfink', name: 'Grünfink', icon: '🐦', cat: 'birds', freq: 'regelmaessig', rank: 13 },
  {
    id: 'rabenkraehe',
    name: 'Rabenkrähe',
    icon: '🐦',
    cat: 'birds',
    freq: 'regelmaessig',
    rank: 14,
  },
  {
    id: 'hausrotschwanz',
    name: 'Hausrotschwanz',
    icon: '🐦',
    cat: 'birds',
    freq: 'gelegentlich',
    rank: 15,
  },
  {
    id: 'moenchsgrasmucke',
    name: 'Mönchsgrasmücke',
    icon: '🐦',
    cat: 'birds',
    freq: 'gelegentlich',
    rank: 16,
  },
  { id: 'stieglitz', name: 'Stieglitz', icon: '🐦', cat: 'birds', freq: 'gelegentlich', rank: 17 },
  {
    id: 'buntspecht',
    name: 'Buntspecht',
    icon: '🐦',
    cat: 'birds',
    freq: 'gelegentlich',
    rank: 18,
  },
  { id: 'kleiber', name: 'Kleiber', icon: '🐦', cat: 'birds', freq: 'selten', rank: 19 },
  { id: 'eichelhaher', name: 'Eichelhäher', icon: '🐦', cat: 'birds', freq: 'selten', rank: 20 },
  // Säugetiere — Eichhörnchen sind das Aushängeschild des Projekts, daher
  // pinnen wir sie über die Vögel hinweg an den Anfang.
  {
    id: 'eichhoernchen_orange',
    name: 'Eichhörnchen (rot)',
    icon: '🐿️',
    cat: 'mammals',
    freq: 'haeufig',
    rank: 1,
    pin: -3,
  },
  {
    id: 'eichhoernchen_schwarz',
    name: 'Eichhörnchen (schwarz)',
    icon: '🐿️',
    cat: 'mammals',
    freq: 'selten',
    rank: 2,
    pin: -2,
  },
  {
    id: 'eichhoernchen_hell',
    name: 'Eichhörnchen (hell)',
    icon: '🐿️',
    cat: 'mammals',
    freq: 'selten',
    rank: 3,
    pin: -1,
  },
  { id: 'igel', name: 'Igel', icon: '🦔', cat: 'mammals', freq: 'gelegentlich', rank: 4 },
  { id: 'feldhase', name: 'Feldhase', icon: '🐇', cat: 'mammals', freq: 'selten', rank: 5 },
  { id: 'reh', name: 'Reh', icon: '🦌', cat: 'mammals', freq: 'selten', rank: 6 },
  { id: 'fuchs', name: 'Fuchs', icon: '🦊', cat: 'mammals', freq: 'selten', rank: 7 },
];

export function _achTier(count) {
  if (!count || count < 1) return 'locked';
  if (count >= 20) return 'gold';
  if (count >= 5) return 'silver';
  return 'bronze';
}

// Rarity → German label + subtle text colour when unlocked. Locked
// medals always render rarity in a neutral gray regardless of rank so
// the eye focuses on what's already been discovered, not what's missing.
const _FREQ_META = {
  'sehr haeufig': { label: 'Sehr häufig', color: 'rgba(150,200,150,0.7)' },
  haeufig: { label: 'Häufig', color: 'rgba(150,200,150,0.6)' },
  regelmaessig: { label: 'Regelmäßig', color: 'rgba(200,200,150,0.7)' },
  gelegentlich: { label: 'Gelegentlich', color: 'rgba(210,170,100,0.7)' },
  selten: { label: 'Selten', color: 'rgba(210,120,100,0.7)' },
};

export function _rarityText(freq, isUnlocked) {
  const m = _FREQ_META[freq];
  if (!m) return '';
  const color = isUnlocked ? m.color : 'rgba(255,255,255,0.25)';
  return `<span class="medal-rarity" style="color:${color}">${m.label}</span>`;
}
