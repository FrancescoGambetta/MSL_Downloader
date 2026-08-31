import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { applyPalette, applyMode, PALETTES } from '@/lib/themes';
import { applyFont, FONTS } from '@/lib/fonts';
import { translate } from '@/lib/translations';

const SettingsContext = createContext(null);

const STORAGE_KEY = 'msl_settings_v3';

const DEFAULTS = {
  language: 'en',
  palette: 'petrolio-oro',
  mode: 'dark',
  font: 'inter',
  // Relative to the backend's own working directory (webapi/main.py is meant
  // to run from the project root -- see its docstring), so a fresh clone
  // downloads into <project>/output without needing a machine-specific
  // absolute path configured first.
  outputFolder: 'output',
};

function loadStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
  } catch {
    return { ...DEFAULTS };
  }
}

// Resolved and applied at module load, before React paints, so a stored dark
// theme doesn't flash the light one on the way in.
const INITIAL_SETTINGS = loadStored();
applyPalette(INITIAL_SETTINGS.palette);
applyMode(INITIAL_SETTINGS.mode);
applyFont(INITIAL_SETTINGS.font);

export function AppSettingsProvider({ children }) {
  const [settings, setSettings] = useState(INITIAL_SETTINGS);

  useEffect(() => {
    applyPalette(settings.palette);
  }, [settings.palette]);

  useEffect(() => {
    applyMode(settings.mode);
  }, [settings.mode]);

  useEffect(() => {
    applyFont(settings.font);
  }, [settings.font]);

  useEffect(() => {
    // The document language drives hyphenation and assistive tech, and the
    // markup can only hardcode one — keep it in sync with the chosen language.
    document.documentElement.lang = settings.language;
  }, [settings.language]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* storage full or unavailable — settings just won't persist */
    }
  }, [settings]);

  const update = useCallback((patch) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  const t = useCallback(
    (key, params) => translate(settings.language, key, params),
    [settings.language]
  );

  const value = useMemo(
    () => ({ settings, update, t, palettes: PALETTES, fonts: FONTS }),
    [settings, update, t]
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useAppSettings() {
  const context = useContext(SettingsContext);
  if (!context) throw new Error('useAppSettings must be used within an AppSettingsProvider');
  return context;
}
