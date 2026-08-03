import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ThemeMode = 'light' | 'dark';

/** localStorage key（与 index.html 防闪烁脚本保持一致）。 */
export const THEME_STORAGE_KEY = 'ui-theme';

type ThemeState = {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
};

function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark';
}

function getPreferredThemeMode(): ThemeMode {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light';
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: getPreferredThemeMode(),
      setMode: (mode) => set({ mode }),
    }),
    {
      name: THEME_STORAGE_KEY,
      merge: (persistedState, currentState) => {
        const persistedMode =
          typeof persistedState === 'object' && persistedState !== null && 'mode' in persistedState
            ? persistedState.mode
            : undefined;

        return {
          ...currentState,
          mode: isThemeMode(persistedMode) ? persistedMode : currentState.mode,
        };
      },
    },
  ),
);
