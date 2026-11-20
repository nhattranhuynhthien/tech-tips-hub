import { getAllTips, type Tip } from './data';
import type { Locale } from './i18n';

export type TipsApiScope = 'tips' | 'news' | 'all';

export interface CompactTipSource {
  id: string;
  name: string;
  site_url?: string;
  kind?: string;
  content_type?: string;
}

export interface CompactTipItem {
  id: string;
  slug: string;
  url: string;
  title: Record<string, string>;
  summary: Record<string, string>;
  source: CompactTipSource;
  source_type?: Tip['source_type'];
  howto?: boolean;
  kind?: string;
  categories: string[];
  tags: string[];
  difficulty?: Tip['difficulty'];
  original_lang: string;
  translated?: Tip['translated'];
  published_at: string;
  fetched_at: string;
  score: number;
  hn_points?: number;
  alsoFrom?: Tip['alsoFrom'];
}

const JSON_HEADERS: Record<string, string> = {
  'Content-Type': 'application/json',
  'Cache-Control': 'public, max-age=3600',
};

export function filterTipsByScope(tips: Tip[], scope: TipsApiScope): Tip[] {
  if (scope === 'tips') {
    return tips.filter((t) => t.source?.kind !== 'news');
  }
  if (scope === 'news') {
    return tips.filter((t) => t.source?.kind === 'news');
  }
  return tips;
}

export function pickLocalizedText(
  map: Record<string, string> | undefined,
  lang: Locale,
  originalLang?: string,
  includeOriginalIfDifferent = false,
): Record<string, string> {
  if (!map || typeof map !== 'object') return {};

  const active = typeof map[lang] === 'string' && map[lang].trim() ? map[lang] : '';
  const result: Record<string, string> = {};

  if (active) {
    result[lang] = active;
  } else {
    const fallbackOrder: string[] = [];
    if (lang !== 'en') fallbackOrder.push('en');
    if (originalLang && originalLang !== lang && !fallbackOrder.includes(originalLang)) {
      fallbackOrder.push(originalLang);
    }
    for (const key of Object.keys(map)) {
      if (!fallbackOrder.includes(key)) fallbackOrder.push(key);
    }

    for (const key of fallbackOrder) {
      const value = map[key];
      if (typeof value === 'string' && value.trim()) {
        // Keep 'en' key directly since all client consumers fall back to `value[lang] || value.en`.
        // For non-'en' fallbacks (e.g. 'zh-CN', or 'vi' when lang='en'), expose under `[lang]`
        // so consumers that only inspect `[lang]` or `.en` (such as saved.astro) still render it.
        const targetKey = key === 'en' ? 'en' : lang;
        result[targetKey] = value;
        break;
      }
    }
  }

  if (includeOriginalIfDifferent && originalLang && originalLang !== lang) {
    const orig = typeof map[originalLang] === 'string' && map[originalLang].trim() ? map[originalLang] : '';
    const primaryValue = result[lang] || result.en || '';
    if (orig && orig !== primaryValue) {
      result[originalLang] = orig;
    }
  }

  return result;
}

function trimSource(source: Tip['source']): CompactTipSource {
  const src = source || ({ id: '', name: '' } as Tip['source']);
  const compact: CompactTipSource = {
    id: src.id,
    name: src.name,
    kind: src.kind,
    content_type: src.content_type,
  };
  if (src.site_url) {
    compact.site_url = src.site_url;
  }
  return compact;
}

function trimTranslated(translated: Tip['translated'], lang: Locale): Tip['translated'] {
  if (!translated || translated[lang] === undefined) return undefined;
  return { [lang]: translated[lang] };
}

export function serializeTipFull(t: Tip): CompactTipItem {
  return {
    id: t.id,
    slug: t.slug || t.id,
    url: t.url,
    title: t.title,
    summary: t.summary,
    source: t.source,
    source_type: t.source_type,
    howto: t.howto,
    kind: t.source?.kind,
    categories: t.categories,
    tags: t.tags,
    difficulty: t.difficulty,
    original_lang: t.original_lang,
    translated: t.translated,
    published_at: t.published_at,
    fetched_at: t.fetched_at,
    score: t.score,
    hn_points: t.hn_points,
    alsoFrom: t.alsoFrom,
  };
}

export function serializeTipForLocale(t: Tip, lang: Locale): CompactTipItem {
  const isMachineTranslated = Boolean(t.translated && t.translated[lang] === 'machine');
  const isUntranslated = t.original_lang !== lang && !isMachineTranslated;

  return {
    id: t.id,
    slug: t.slug || t.id,
    url: t.url,
    title: pickLocalizedText(t.title, lang, t.original_lang, isUntranslated),
    summary: pickLocalizedText(t.summary, lang, t.original_lang, false),
    source: trimSource(t.source),
    source_type: t.source_type,
    howto: t.howto,
    kind: t.source?.kind,
    categories: t.categories,
    tags: t.tags,
    difficulty: t.difficulty,
    original_lang: t.original_lang,
    translated: trimTranslated(t.translated, lang),
    published_at: t.published_at,
    fetched_at: t.fetched_at,
    score: t.score,
    hn_points: t.hn_points,
    alsoFrom: t.alsoFrom,
  };
}

export function buildFullTipsPayload(tips: Tip[] = getAllTips()): CompactTipItem[] {
  return tips.map(serializeTipFull);
}

export function buildLocalizedTipsPayload(
  lang: Locale,
  scope: TipsApiScope,
  tips: Tip[] = getAllTips(),
): CompactTipItem[] {
  return filterTipsByScope(tips, scope).map((t) => serializeTipForLocale(t, lang));
}

export function createJsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: JSON_HEADERS,
  });
}

export function createFullTipsResponse(): Response {
  return createJsonResponse(buildFullTipsPayload());
}

export function createLocalizedTipsResponse(lang: Locale, scope: TipsApiScope): Response {
  return createJsonResponse(buildLocalizedTipsPayload(lang, scope));
}
