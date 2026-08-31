export const FONTS = [
  { id: 'inter', label: 'Interfaccia', family: 'Inter', stack: '"Inter", system-ui, sans-serif' },
  { id: 'lexend', label: 'Lettura', family: 'Lexend', stack: '"Lexend", system-ui, sans-serif' },
  { id: 'spacemono', label: 'Archivio', family: 'Space Mono', stack: '"Space Mono", ui-monospace, monospace' },
];

export function getFont(id) {
  return FONTS.find((f) => f.id === id) || FONTS[0];
}

export function applyFont(id) {
  const f = getFont(id);
  const root = document.documentElement;
  root.style.setProperty('--font-body', f.stack);
  root.style.setProperty('--font-heading', f.stack);
  root.style.setProperty('--font-display', f.stack);
}
