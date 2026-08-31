// La palette controlla SOLO i token di accento (primary, ring, accent).
// I neutri (sfondi, testo, bordi) sono fissi per tema chiaro/scuro e vivono in index.css.

function hexToHsl(hex) {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let hh = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: hh = (g - b) / d + (g < b ? 6 : 0); break;
      case g: hh = (b - r) / d + 2; break;
      default: hh = (r - g) / d + 4;
    }
    hh /= 6;
  }
  return `${Math.round(hh * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

// Display name lives in translations.js (key `palette.<id>`), not here --
// SettingsPanel.jsx looks it up via t() so the palette picker is multilingual.
const RAW_PALETTES = [
  ['petrolio-oro', ['#6b4e2a', '#a07040', '#b8864f', '#ead2a6']],
  ['notte-viola', ['#4f3472', '#7d57a8', '#9474c3', '#e9ddfb']],
  ['oceano-blu', ['#1f4f82', '#2f72bb', '#4f8dd3', '#ddeafb']],
  ['bosco-verde', ['#244c31', '#3f7250', '#5f8a6c', '#deece3']],
  ['porpora-velluto', ['#5c0a0a', '#8e2626', '#a94646', '#f1dddd']],
  ['rosa-antico', ['#743848', '#c5748b', '#da95a7', '#fbe6ec']],
  ['oliva-prato', ['#61743a', '#8ea354', '#a9bb71', '#eef2de']],
  ['terracotta-ocra', ['#6a3828', '#b0643b', '#cd8257', '#f9e8de']],
  ['grafite-seta', ['#2e343b', '#59636f', '#798390', '#e9edf1']],
  ['arancia-rame', ['#8a3f14', '#dc6f24', '#ea8a42', '#fde9d9']],
  ['nebbia-argento', ['#3a4a5c', '#6080a0', '#88a8cc', '#dce8f4']],
  ['inchiostro-abisso', ['#1a1a3a', '#3a3a7a', '#6060c0', '#d8d8f8']],
  ['salvia-pietra', ['#3a4a38', '#6a8464', '#90aa8c', '#dcecd8']],
  ['corallo-sabbia', ['#7a3030', '#c46060', '#e09090', '#fce8e8']],
  ['lacca-prugna', ['#3c0e52', '#7018a0', '#9038c8', '#eed8fc']],
  ['fumo-cenere', ['#2e2820', '#5a5048', '#7a6e66', '#ece6e0']],
];

export const PALETTES = RAW_PALETTES.map(([id, colors]) => ({
  id,
  colors,
  swatch: colors[2],
}));

export const ACCENT_KEYS = [
  'primary', 'primary-foreground', 'ring', 'accent', 'accent-foreground',
];

export function getPalette(id) {
  return PALETTES.find((p) => p.id === id) || PALETTES[0];
}

function accentVars(palette) {
  const [scuro, medio, , pallido] = palette.colors;
  return {
    primary: hexToHsl(medio),
    'primary-foreground': hexToHsl(pallido),
    ring: hexToHsl(medio),
    accent: hexToHsl(pallido),
    'accent-foreground': hexToHsl(scuro),
  };
}

export function applyPalette(paletteId) {
  const palette = getPalette(paletteId);
  const root = document.documentElement;
  ACCENT_KEYS.forEach((k) => root.style.removeProperty(`--${k}`));
  Object.entries(accentVars(palette)).forEach(([k, v]) => root.style.setProperty(`--${k}`, v));
}

export function applyMode(mode) {
  if (mode === 'dark') document.documentElement.classList.add('dark');
  else document.documentElement.classList.remove('dark');
}