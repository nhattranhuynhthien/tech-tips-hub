import { getAllTips } from '../../lib/data';

export async function GET() {
  const tips = getAllTips();
  // Rút gọn trường để tải nhanh qua mạng (khoảng vài chục KB)
  const compact = tips.map((t) => ({
    id: t.id,
    slug: t.slug || t.id,
    title: t.title,
    summary: t.summary,
    source: t.source,
    categories: t.categories,
    tags: t.tags,
    difficulty: t.difficulty,
  }));

  return new Response(JSON.stringify(compact), {
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}

