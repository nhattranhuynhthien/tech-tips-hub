import vi from '../i18n/vi.json';
import en from '../i18n/en.json';

export type Locale = 'vi' | 'en';

export function getTranslations(lang: Locale) {
  return lang === 'en' ? en : vi;
}
