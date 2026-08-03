import { SUPPORTED_LOCALES, type Locale } from './instance';
import { useLocaleStore } from './locale-store';

export function useLocale() {
  const locale = useLocaleStore((state) => state.locale);
  const setLocale = useLocaleStore((state) => state.setLocale);

  return { locale, setLocale, available: SUPPORTED_LOCALES as readonly Locale[] };
}
