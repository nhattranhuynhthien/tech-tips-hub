import fs from 'node:fs';
import path from 'node:path';
import * as yaml from 'js-yaml';
import { generateSeoSlug } from './slug';

export interface Source {
  id: string;
  name: string;
  type?: 'rss' | 'atom' | 'json-api' | 'reddit' | 'youtube' | 'telegram';
  site_url?: string;
  url?: string;
  lang?: string;
  kind?: 'tips' | 'news';
  allowNews?: boolean;
  contentType?: 'article' | 'community' | 'video' | 'vendor';
  enabled?: boolean;
  trust?: number;
  tipOnly?: boolean;
  maxPerRun?: number;
  weight?: number;
  categories?: string[];
  description?: string;
}

export interface SourceHealth {
  status: 'ok' | 'degraded' | 'paused';
  failure_count: number;
  last_success: string | null;
  last_failure: string | null;
  paused_until: string | null;
  last_error: string | null;
}

export interface Tip {
  id: string;
  slug?: string;
  url: string;
  source: {
    id: string;
    name: string;
    site_url?: string;
    kind?: string;
    content_type?: string;
  };
  author?: string | null;
  published_at: string;
  fetched_at: string;
  original_lang: string;
  title: Record<string, string> & { en: string; vi: string };
  summary: Record<string, string> & { en: string; vi: string };
  key_points?: Record<string, string[]>;
  categories: string[];
  tags: string[];
  difficulty?: 'easy' | 'medium' | 'advanced' | null;
  score: number;
  howto?: boolean;
  hidden?: boolean;
  reading_time_min: number;
  hn_points?: number;
  hn_comments_url?: string;
  translated?: {
    [key: string]: string | boolean;
  };
  alsoFrom?: Array<{ sourceName: string; url: string }>;
  source_type?: 'community-telegram' | 'community-facebook' | 'community-web' | string;
}

export interface Category {
  id: string;
  slug: string;
  name: {
    en: string;
    vi: string;
  };
  description: {
    en: string;
    vi: string;
  };
  icon: string;
  color: string;
  keywords: string[];
}

let cachedTips: Tip[] | null = null;
let cachedCategories: Category[] | null = null;
let cachedSources: Source[] | null = null;
let cachedHealth: Record<string, SourceHealth> | null = null;

function tipTimestampMs(tip: Tip): number {
  const ts = new Date(tip.published_at || tip.fetched_at || 0).getTime();
  return Number.isFinite(ts) ? ts : 0;
}

function isViReady(tip: Tip): boolean {
  return tip.original_lang === 'vi' || tip.translated?.vi === 'machine';
}

export function getAllTips(includeHidden = false): Tip[] {
  if (cachedTips) {
    return includeHidden ? cachedTips : cachedTips.filter((t) => !t.hidden);
  }
  const indexPath = path.resolve('./data/index.json');
  if (!fs.existsSync(indexPath)) return [];
  try {
    const raw = fs.readFileSync(indexPath, 'utf-8');
    const map = JSON.parse(raw);
    const list: Tip[] = Object.values(map);
    const sourcesById = new Map(getAllSources().map((source) => [source.id, source]));
    for (const t of list) {
      const configuredSource = sourcesById.get(t.source?.id);
      if (configuredSource?.name) t.source.name = configuredSource.name;
      if (!t.source.content_type) t.source.content_type = configuredSource?.contentType || 'article';
      if (!t.source.kind) t.source.kind = configuredSource?.kind || (t.howto ? 'tips' : 'news');
      if (!t.slug) {
        const title = t.title?.vi || t.title?.en || '';
        t.slug = generateSeoSlug(title, t.id);
      }
    }
    cachedTips = list;
    return includeHidden ? cachedTips : cachedTips.filter((t) => !t.hidden);
  } catch (err) {
    console.error('Error reading index.json:', err);
    return [];
  }
}

export function sortTipsNewestFirst(tips: Tip[]): Tip[] {
  return [...tips].sort((a, b) => {
    const timeDiff = tipTimestampMs(b) - tipTimestampMs(a);
    if (timeDiff !== 0) return timeDiff;
    return String(a.id).localeCompare(String(b.id));
  });
}

export function getAllCategories(): Category[] {
  if (cachedCategories) return cachedCategories;
  const catPath = path.resolve('./config/categories.yml');
  if (!fs.existsSync(catPath)) return [];
  try {
    const raw = fs.readFileSync(catPath, 'utf-8');
    const doc = yaml.load(raw) as { categories: Category[] };
    cachedCategories = doc.categories || [];
    return cachedCategories;
  } catch (err) {
    console.error('Error reading categories.yml:', err);
    return [];
  }
}

export function getAllSources(): Source[] {
  if (cachedSources) return cachedSources;
  const srcPath = path.resolve('./config/sources.json');
  if (!fs.existsSync(srcPath)) return [];
  try {
    const raw = fs.readFileSync(srcPath, 'utf-8');
    const list = JSON.parse(raw) as Source[];
    cachedSources = (list || []).filter((source) => source.enabled === true);
    return cachedSources;
  } catch (err) {
    console.error('Error reading sources.json:', err);
    return [];
  }
}

export function getSourceHealth(): Record<string, SourceHealth> {
  if (cachedHealth) return cachedHealth;
  const healthPath = path.resolve('./data/health.json');
  if (!fs.existsSync(healthPath)) {
    cachedHealth = {};
    return cachedHealth;
  }
  try {
    const raw = fs.readFileSync(healthPath, 'utf-8');
    const parsed = JSON.parse(raw) as { sources?: Record<string, Partial<SourceHealth>> };
    const rawSources = parsed && typeof parsed === 'object' && parsed.sources && typeof parsed.sources === 'object'
      ? parsed.sources
      : {};
    const validStatuses = new Set<SourceHealth['status']>(['ok', 'degraded', 'paused']);
    const result: Record<string, SourceHealth> = {};
    for (const [id, entry] of Object.entries(rawSources)) {
      if (!entry || typeof entry !== 'object') continue;
      const status: SourceHealth['status'] =
        entry.status && validStatuses.has(entry.status) ? entry.status : 'ok';
      result[id] = {
        status,
        failure_count: typeof entry.failure_count === 'number' && Number.isFinite(entry.failure_count)
          ? entry.failure_count
          : 0,
        last_success: typeof entry.last_success === 'string' ? entry.last_success : null,
        last_failure: typeof entry.last_failure === 'string' ? entry.last_failure : null,
        paused_until: typeof entry.paused_until === 'string' ? entry.paused_until : null,
        last_error: typeof entry.last_error === 'string' ? entry.last_error : null,
      };
    }
    cachedHealth = result;
    return cachedHealth;
  } catch {
    cachedHealth = {};
    return cachedHealth;
  }
}

function loadRecentFeaturedIds(now: Date): Set<string> {
  const featuredHistoryIds = new Set<string>();
  try {
    const historyPath = path.resolve('./data/history_featured.json');
    if (!fs.existsSync(historyPath)) return featuredHistoryIds;
    const historyData = JSON.parse(fs.readFileSync(historyPath, 'utf-8'));
    if (!Array.isArray(historyData)) return featuredHistoryIds;

    const fourteenDaysAgo = now.getTime() - 14 * 24 * 60 * 60 * 1000;
    const todayUtc = now.toISOString().slice(0, 10);
    for (const entry of historyData) {
      const entryDate = entry.date || (entry.featured_at ? String(entry.featured_at).slice(0, 10) : '');
      if (entryDate === todayUtc) continue;
      const entryTime = new Date(entry.featured_at || entry.date).getTime();
      if (!Number.isNaN(entryTime) && entryTime >= fourteenDaysAgo && typeof entry.id === 'string') {
        featuredHistoryIds.add(entry.id);
      }
    }
  } catch {
    return featuredHistoryIds;
  }
  return featuredHistoryIds;
}

function compareFeaturedCandidates(a: Tip, b: Tip, lang: 'vi' | 'en'): number {
  if (lang === 'vi') {
    const aVi = isViReady(a) ? 1 : 0;
    const bVi = isViReady(b) ? 1 : 0;
    if (bVi !== aVi) return bVi - aVi;
  }
  const aTips = a.source?.kind === 'tips' ? 1 : 0;
  const bTips = b.source?.kind === 'tips' ? 1 : 0;
  if (bTips !== aTips) return bTips - aTips;
  const scoreDiff = (b.score ?? 0) - (a.score ?? 0);
  if (scoreDiff !== 0) return scoreDiff;
  return tipTimestampMs(b) - tipTimestampMs(a);
}

export function getTrickOfTheDay(lang: 'vi' | 'en' = 'vi'): Tip | null {
  const tips = getAllTips(false).filter((t) => Boolean(t.howto));
  if (tips.length === 0) return null;

  const now = new Date();
  const maxAgeMs = 72 * 60 * 60 * 1000;
  const featuredHistoryIds = loadRecentFeaturedIds(now);

  // 1. Primary pool: howto items within 72h not featured in past 14 days (preferring VI-ready on vi)
  const freshUnfeatured = tips.filter((t) => {
    if (featuredHistoryIds.has(t.id)) return false;
    const pubMs = new Date(t.published_at).getTime();
    const ageMs = now.getTime() - pubMs;
    return Number.isFinite(pubMs) && ageMs >= 0 && ageMs <= maxAgeMs;
  });

  if (freshUnfeatured.length > 0) {
    const preferred = lang === 'vi' ? freshUnfeatured.filter(isViReady) : freshUnfeatured;
    const pool = preferred.length > 0 ? preferred : freshUnfeatured;
    return [...pool].sort((a, b) => compareFeaturedCandidates(a, b, lang))[0];
  }

  // 2. Graceful fallback: highest-scoring unfeatured howto item so Hero never disappears when feed is quiet
  const unfeaturedAll = tips.filter((t) => !featuredHistoryIds.has(t.id));
  const fallbackPool = unfeaturedAll.length > 0 ? unfeaturedAll : tips;
  return [...fallbackPool].sort((a, b) => compareFeaturedCandidates(a, b, lang))[0] || null;
}

export function getNewsOfTheDay(): Tip | null {
  const allNews = getAllTips(false).filter((tip) => tip.source?.kind === 'news');
  if (allNews.length === 0) return null;

  const now = Date.now();
  const dayMs = 24 * 60 * 60 * 1000;
  const recentNews = allNews.filter((tip) => {
    const publishedAt = tipTimestampMs(tip);
    return publishedAt > 0 && publishedAt <= now && now - publishedAt <= dayMs;
  });

  if (recentNews.length > 0) {
    return [...recentNews].sort(
      (a, b) => (b.score ?? 0) - (a.score ?? 0) || tipTimestampMs(b) - tipTimestampMs(a),
    )[0];
  }

  // Graceful fallback: newest / highest-scoring news article so News Hero never disappears
  return [...allNews].sort(
    (a, b) => tipTimestampMs(b) - tipTimestampMs(a) || (b.score ?? 0) - (a.score ?? 0),
  )[0];
}
