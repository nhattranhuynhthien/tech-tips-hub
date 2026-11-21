import type { Locale } from './i18n';

function resolveTimeZone(lang: Locale): string {
  return lang === 'vi' ? 'Asia/Ho_Chi_Minh' : 'UTC';
}

function parseDate(value: string | Date | undefined | null): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function getDateParts(
  date: Date,
  lang: Locale,
  options: Intl.DateTimeFormatOptions,
): Record<string, string> {
  const formatter = new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-US', {
    timeZone: resolveTimeZone(lang),
    ...options,
  });
  const parts: Record<string, string> = {};
  for (const part of formatter.formatToParts(date)) {
    if (part.type !== 'literal') {
      parts[part.type] = part.value;
    }
  }
  if (parts.hour === '24') {
    parts.hour = '00';
  }
  return parts;
}

/**
 * Deterministic DD/MM in Asia/Ho_Chi_Minh (vi) or UTC (en).
 */
export function formatShortDate(value: string | Date | undefined | null, lang: Locale): string {
  const date = parseDate(value);
  if (!date) return '';
  try {
    const parts = getDateParts(date, lang, { day: '2-digit', month: '2-digit' });
    if (!parts.day || !parts.month) return '';
    return `${parts.day}/${parts.month}`;
  } catch {
    return '';
  }
}

/**
 * Deterministic DD/MM/YYYY in Asia/Ho_Chi_Minh (vi) or UTC (en).
 */
export function formatFullDate(value: string | Date | undefined | null, lang: Locale): string {
  const date = parseDate(value);
  if (!date) return '';
  try {
    const parts = getDateParts(date, lang, {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
    if (!parts.day || !parts.month || !parts.year) return '';
    return `${parts.day}/${parts.month}/${parts.year}`;
  } catch {
    return '';
  }
}

/**
 * Deterministic DD/MM HH:mm (24h) in Asia/Ho_Chi_Minh (vi) or UTC (en).
 */
export function formatUpdatedAt(value: string | Date | undefined | null, lang: Locale): string {
  const date = parseDate(value);
  if (!date) return '';
  try {
    const parts = getDateParts(date, lang, {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    });
    if (!parts.day || !parts.month || !parts.hour || !parts.minute) return '';
    return `${parts.day}/${parts.month} ${parts.hour}:${parts.minute}`;
  } catch {
    return '';
  }
}

/**
 * Deterministic readable timestamp with explicit timezone suffix (GMT+7 / UTC)
 * so SSR and CSR match with zero hydration or timezone shift.
 */
export function formatLatestTimestamp(value: string | Date | undefined | null, lang: Locale): string {
  const date = parseDate(value);
  if (!date) return '';
  try {
    const parts = getDateParts(date, lang, {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    });
    if (!parts.day || !parts.month || !parts.year || !parts.hour || !parts.minute) return '';
    const tzLabel = lang === 'vi' ? 'GMT+7' : 'UTC';
    return `${parts.day}/${parts.month}/${parts.year} ${parts.hour}:${parts.minute} ${tzLabel}`;
  } catch {
    return '';
  }
}
