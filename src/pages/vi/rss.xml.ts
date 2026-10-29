import { getAllTips } from '../../lib/data';
import { SITE_URL } from '../../lib/constants';

export async function GET() {
  const tips = getAllTips().slice(0, 50);

  const itemsXml = tips
    .map((tip) => {
      const title = tip.title.vi || tip.title.en || '';
      const desc = tip.summary.vi || tip.summary.en || '';
      const pubDate = new Date(tip.published_at || tip.fetched_at).toUTCString();
      const link = `${SITE_URL}/vi/tip/${tip.slug || tip.id}`;

      return `
    <item>
      <title><![CDATA[${title}]]></title>
      <link>${link}</link>
      <guid isPermaLink="true">${link}</guid>
      <description><![CDATA[${desc}]]></description>
      <pubDate>${pubDate}</pubDate>
      <source url="${tip.url}">${tip.source.name}</source>
      ${tip.categories.map((c) => `<category>${c}</category>`).join('\n      ')}
    </item>`;
    })
    .join('');

  const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Tech Tips Hub (Tiếng Việt)</title>
    <link>${SITE_URL}/vi</link>
    <description>Sổ tay tổng hợp thủ thuật và mẹo công nghệ song ngữ, luôn ghi nguồn gốc</description>
    <language>vi-VN</language>
    <atom:link href="${SITE_URL}/vi/rss.xml" rel="self" type="application/rss+xml"/>
    ${itemsXml}
  </channel>
</rss>`;

  return new Response(rss, {
    headers: {
      'Content-Type': 'application/xml; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}

