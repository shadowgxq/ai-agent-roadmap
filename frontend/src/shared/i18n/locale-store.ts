import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, i18n, type Locale } from './instance';

type LocaleState = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
};

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: DEFAULT_LOCALE,
      setLocale: (locale) => {
        void i18n.changeLanguage(locale);
        set({ locale });
      },
    }),
    { name: LOCALE_STORAGE_KEY },
  ),
);
