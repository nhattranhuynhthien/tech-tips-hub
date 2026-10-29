import fs from 'node:fs';
import path from 'node:path';
import * as yaml from 'js-yaml';

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

export function getAllTips(): Tip[] {
  if (cachedTips) return cachedTips;
  const indexPath = path.resolve('./data/index.json');
  if (!fs.existsSync(indexPath)) return [];
  try {
    const raw = fs.readFileSync(indexPath, 'utf-8');
    const map = JSON.parse(raw);
    const list: Tip[] = Object.values(map);
    // Danh sách đã được xếp thứ tự đa dạng (diversify) từ pipeline
    cachedTips = list;
    return list;
  } catch (err) {
    console.error('Error reading index.json:', err);
    return [];
  }
}

export function getTipById(id: string): Tip | undefined {
  const tips = getAllTips();
  return tips.find((t) => t.id === id);
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
  const tips = getAllTips();
  if (tips.length === 0) return null;

  const now = new Date();
  const maxAgeMs = 4 * 24 * 60 * 60 * 1000; // Trong vòng 4 ngày (96h)

  // Chỉ chọn từ bài viết là thủ thuật thật (howto == true hoặc có difficulty)
  const candidates = tips.filter((t) => {
    if (!t.howto && !t.difficulty) return false;
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

  // Dự phòng: bài howto điểm cao nhất trong kho
  const fallback = tips.find((t) => t.howto || t.difficulty);
  return fallback || null;
}

export function getCategoriesWithCounts(): Array<Category & { count: number }> {
  const categories = getAllCategories();
  const tips = getAllTips();
  return categories.map((cat) => {
    const count = tips.filter((t) => t.categories.includes(cat.id)).length;
    return { ...cat, count };
  });
}
