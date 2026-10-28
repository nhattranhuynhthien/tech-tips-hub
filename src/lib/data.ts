import fs from 'node:fs';
import path from 'node:path';
import * as yaml from 'js-yaml';

export interface Source {
  id: string;
  name: string;
  site_url?: string;
  url?: string;
  lang?: string;
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
  difficulty: 'easy' | 'medium' | 'advanced';
  score: number;
  reading_time_min: number;
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
    // Sắp xếp bài viết: bài có điểm cao và mới nhất lên trước
    list.sort((a, b) => b.score - a.score);
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
  // Lấy bài viết có điểm cao nhất hoặc chọn luân phiên theo ngày
  const todayStr = new Date().toISOString().slice(0, 10);
  let hash = 0;
  for (let i = 0; i < todayStr.length; i++) {
    hash = (hash << 5) - hash + todayStr.charCodeAt(i);
    hash |= 0;
  }
  // Lấy trong top 10 bài điểm cao nhất
  const topCandidates = tips.slice(0, Math.min(10, tips.length));
  const selectedIndex = Math.abs(hash) % topCandidates.length;
  return topCandidates[selectedIndex] || tips[0];
}

export function getCategoriesWithCounts(): Array<Category & { count: number }> {
  const categories = getAllCategories();
  const tips = getAllTips();
  return categories.map((cat) => {
    const count = tips.filter((t) => t.categories.includes(cat.id)).length;
    return { ...cat, count };
  });
}
