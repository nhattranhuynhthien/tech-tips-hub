// src/lib/slug.ts
// Tiện ích tạo SEO-friendly slug kết hợp tiêu đề không dấu và mã hash ngắn

export function generateSeoSlug(title: string, id: string): string {
  if (!title) {
    return `tip-${id.slice(0, 6)}`;
  }

  const cleanTitle = title
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[đĐ]/g, 'd')
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .slice(0, 60)
    .replace(/-$/, '');

  const shortHash = (id || '').slice(0, 6);
  return `${cleanTitle || 'tip'}-${shortHash}`;
}
