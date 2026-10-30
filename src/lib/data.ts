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
    // Danh sách đã được xếp thứ tự đa dạng (diversify) từ pipeline
    cachedTips = list;
    return includeHidden ? cachedTips : cachedTips.filter((t) => !t.hidden);
  } catch (err) {
    console.error('Error reading index.json:', err);
    return [];
  }
}

/**
 * Thứ tự chuẩn của danh sách tip trên trang chủ và các trang phân trang.
 * Khớp với bộ sắp xếp mặc định "Hay nhất" phía client (score giảm dần).
 */
export function sortTipsForFeed(tips: Tip[]): Tip[] {
  return [...tips].sort((a, b) => {
    const scoreDiff = (b.score ?? 0) - (a.score ?? 0);
    if (scoreDiff !== 0) return scoreDiff;
    const aTime = new Date(a.published_at || a.fetched_at || 0).getTime();
    const bTime = new Date(b.published_at || b.fetched_at || 0).getTime();
    const timeDiff = (isNaN(bTime) ? 0 : bTime) - (isNaN(aTime) ? 0 : aTime);
    if (timeDiff !== 0) return timeDiff;
    const aId = String(a.id);
    const bId = String(b.id);
    return aId < bId ? -1 : aId > bId ? 1 : 0;
  });
}

export function sortTipsNewestFirst(tips: Tip[]): Tip[] {
  return [...tips].sort((a, b) => {
    const aTime = new Date(a.published_at || a.fetched_at || 0).getTime();
    const bTime = new Date(b.published_at || b.fetched_at || 0).getTime();
    const timeDiff = (isNaN(bTime) ? 0 : bTime) - (isNaN(aTime) ? 0 : aTime);
    if (timeDiff !== 0) return timeDiff;
    return String(a.id).localeCompare(String(b.id));
  });
}

export function getTipById(idOrSlug: string): Tip | undefined {
  const tips = getAllTips(true);
  if (!idOrSlug) return undefined;
  return (
    tips.find((t) => t.id === idOrSlug || t.slug === idOrSlug) ||
    tips.find((t) => idOrSlug.endsWith(t.id.slice(0, 6)) || t.id.startsWith(idOrSlug))
  );
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

export function getTrickOfTheDay(): Tip | null {
  const tips = getAllTips(false);
  if (tips.length === 0) return null;

  const now = new Date();
  const maxAgeMs = 72 * 60 * 60 * 1000; // Trong vòng 72 giờ theo đặc tả

  // Đọc danh sách đã nổi bật trong 14 ngày từ data/history_featured.json
  const featuredHistoryIds = new Set<string>();
  try {
    const historyPath = path.resolve('./data/history_featured.json');
    if (fs.existsSync(historyPath)) {
      const historyData = JSON.parse(fs.readFileSync(historyPath, 'utf-8'));
      if (Array.isArray(historyData)) {
        const fourteenDaysAgo = now.getTime() - 14 * 24 * 60 * 60 * 1000;
        const todayUtc = now.toISOString().slice(0, 10);
        for (const entry of historyData) {
          const entryDate = entry.date || (entry.featured_at ? String(entry.featured_at).slice(0, 10) : '');
          // Mục đã chọn trong hôm nay vẫn phải hiển thị, nếu không sẽ bị lệch sang bài kế tiếp
          if (entryDate === todayUtc) continue;
          const entryTime = new Date(entry.featured_at || entry.date).getTime();
          if (!isNaN(entryTime) && entryTime >= fourteenDaysAgo) {
            featuredHistoryIds.add(entry.id);
          }
        }
      }
    }
  } catch {}

  // Chỉ chọn từ bài viết là thủ thuật thật (howto == true), trong 72 giờ, và chưa nổi bật trong 14 ngày
  const candidates = tips.filter((t) => {
    if (!t.howto) return false;
    if (featuredHistoryIds.has(t.id)) return false;
    try {
      const pubDate = new Date(t.published_at);
      const ageMs = now.getTime() - pubDate.getTime();
      if (!isNaN(pubDate.getTime()) && ageMs >= 0 && ageMs <= maxAgeMs) {
        return true;
      }
    } catch {}
    return false;
  });

  if (candidates.length > 0) {
    // Sắp xếp ưu tiên nguồn chuyên tips và điểm score cao
    candidates.sort((a, b) => {
      const aTips = a.source?.kind === 'tips' ? 1 : 0;
      const bTips = b.source?.kind === 'tips' ? 1 : 0;
      if (bTips !== aTips) return bTips - aTips;
      return b.score - a.score;
    });
    return candidates[0];
  }

  // Không có bài đủ điều kiện trong 72 giờ thì ẩn khối này
  return null;
}

export function getNewsOfTheDay(): Tip | null {
  const now = Date.now();
  const dayMs = 24 * 60 * 60 * 1000;
  const recentNews = getAllTips().filter((tip) => {
    if (tip.source?.kind !== 'news') return false;
    const publishedAt = new Date(tip.published_at || tip.fetched_at || 0).getTime();
    return Number.isFinite(publishedAt) && publishedAt <= now && now - publishedAt <= dayMs;
  });
  return recentNews.sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || Date.parse(b.published_at) - Date.parse(a.published_at))[0] || null;
}

export function getCategoriesWithCounts(): Array<Category & { count: number }> {
  const categories = getAllCategories();
  const tips = getAllTips();
  return categories.map((cat) => {
    const count = tips.filter((t) => t.categories.includes(cat.id)).length;
    return { ...cat, count };
  });
}
