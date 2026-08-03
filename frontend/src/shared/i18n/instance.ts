import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './locales/en.json';
import zh from './locales/zh.json';

export const SUPPORTED_LOCALES = ['en', 'zh'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en';

/** localStorage key（与 locale-store persist 名称一致）。 */
export const LOCALE_STORAGE_KEY = 'ui-locale';

export const resources = {
  en: { translation: en },
  zh: { translation: zh },
} as const;

function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/** 从持久化的 locale-store 读取初始语言（zustand persist 结构）。 */
function readInitialLocale(): Locale {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_LOCALE;
  }
  try {
    const raw = localStorage.getItem(LOCALE_STORAGE_KEY);
    const locale = raw ? (JSON.parse(raw) as { state?: { locale?: unknown } }).state?.locale : null;
    return isLocale(locale) ? locale : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export const i18n = i18next.createInstance();

void i18n.use(initReactI18next).init({
  resources,
  lng: readInitialLocale(),
  fallbackLng: DEFAULT_LOCALE,
  interpolation: { escapeValue: false },
  // 资源已同步内置，无需 Suspense 边界。
  react: { useSuspense: false },
});
