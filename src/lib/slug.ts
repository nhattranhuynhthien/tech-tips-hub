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

export function matchTipBySlugOrId(param: string, tips: Array<{ id: string; slug?: string }>) {
  if (!param) return undefined;
  
  // 1. Khớp chính xác slug hoặc ID đầy đủ
  const exact = tips.find((t) => t.slug === param || t.id === param);
  if (exact) return exact;

  // 2. Khớp 6 ký tự hash ở cuối slug (ví dụ: ...-494dec)
  const parts = param.split('-');
  const possibleHash = parts[parts.length - 1];
  if (possibleHash && possibleHash.length >= 6) {
    const byHash = tips.find((t) => t.id.startsWith(possibleHash));
    if (byHash) return byHash;
  }

  return undefined;
}
