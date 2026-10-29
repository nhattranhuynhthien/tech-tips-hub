import fs from 'node:fs';
import path from 'node:path';
import * as yaml from 'js-yaml';
import { generateSeoSlug } from './slug';

export interface Source {
  id: string;
  name: string;
  site_url?: string;
  url?: string;
  lang?: string;
  kind?: 'tips' | 'news';
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
  };
  author?: string | null;
  published_at: string;
  fetched_at: string;
  original_lang: string;
  title: {
    en: string;
    vi: string;
  };
  summary: {
    en: string;
    vi: string;
  };
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
    [key: string]: string;
  };
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
    for (const t of list) {
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
  const srcPath = path.resolve('./config/sources.yml');
  if (!fs.existsSync(srcPath)) return [];
  try {
    const raw = fs.readFileSync(srcPath, 'utf-8');
    const list = yaml.load(raw) as Source[];
    cachedSources = list || [];
    return cachedSources;
  } catch (err) {
    console.error('Error reading sources.yml:', err);
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
        for (const entry of historyData) {
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
      if (!isNaN(pubDate.getTime()) && now.getTime() - pubDate.getTime() <= maxAgeMs) {
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

export function getCategoriesWithCounts(): Array<Category & { count: number }> {
  const categories = getAllCategories();
  const tips = getAllTips();
  return categories.map((cat) => {
    const count = tips.filter((t) => t.categories.includes(cat.id)).length;
    return { ...cat, count };
  });
}
