import { getAllTips } from '../../lib/data';

export async function GET() {
  const tips = getAllTips();
  // Rút gọn trường để tải nhanh qua mạng, nhưng vẫn đủ để render thẻ giống TipCard.astro.
  const compact = tips.map((t) => ({
    id: t.id,
    slug: t.slug || t.id,
    url: t.url,
    title: t.title,
    summary: t.summary,
    source: t.source,
    source_type: t.source_type,
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
  }));

  return new Response(JSON.stringify(compact), {
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
