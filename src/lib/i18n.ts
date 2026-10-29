import vi from '../i18n/vi.json';
import en from '../i18n/en.json';

export type Locale = 'vi' | 'en';

export function getTranslations(lang: Locale) {
  return lang === 'en' ? en : vi;
}

export function formatTemplate(template: string, vars: Record<string, string | number>): string {
  let result = template;
  for (const [key, val] of Object.entries(vars)) {
    result = result.replace(new RegExp(`\\{${key}\\}`, 'g'), String(val));
  }
  return result;
}

