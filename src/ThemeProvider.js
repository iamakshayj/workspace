import React, { createContext, useContext, useLayoutEffect, useMemo, useState } from 'react';

const ThemeContext = createContext(null);
const THEME_KEY = 'flowforge:theme';
const THEME_PREFERENCES = new Set(['system', 'light', 'dark']);

export function validThemePreference(value) {
  return THEME_PREFERENCES.has(value) ? value : 'system';
}

function systemTheme() {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(() => validThemePreference(localStorage.getItem(THEME_KEY)));
  const [resolvedTheme, setResolvedTheme] = useState(() => preference === 'system' ? systemTheme() : preference);

  useLayoutEffect(() => {
    const media = typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null;
    const applyTheme = () => {
      const resolved = preference === 'system' ? (media?.matches ? 'dark' : 'light') : preference;
      setResolvedTheme(resolved);
      document.documentElement.dataset.theme = resolved;
      document.documentElement.dataset.themePreference = preference;
      document.documentElement.style.colorScheme = resolved;
      localStorage.setItem(THEME_KEY, preference);
    };
    applyTheme();
    if (preference === 'system') media?.addEventListener?.('change', applyTheme);
    return () => media?.removeEventListener?.('change', applyTheme);
  }, [preference]);

  const value = useMemo(() => ({
    preference,
    resolvedTheme,
    setThemePreference: (value) => setPreference(validThemePreference(value)),
  }), [preference, resolvedTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const theme = useContext(ThemeContext);
  if (!theme) throw new Error('useTheme must be used within ThemeProvider');
  return theme;
}
