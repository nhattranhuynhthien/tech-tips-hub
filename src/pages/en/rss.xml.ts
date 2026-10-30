import { getAllTips } from '../../lib/data';
import { SITE_URL } from '../../lib/constants';
import { escapeXml, xmlCdata } from '../../lib/xml';

export async function GET() {
  const tips = getAllTips().slice(0, 50);

  const itemsXml = tips
    .map((tip) => {
      const title = tip.title.en || tip.title.vi || '';
      const desc = tip.summary.en || tip.summary.vi || '';
      const pubDate = new Date(tip.published_at || tip.fetched_at).toUTCString();
      const link = `${SITE_URL}/en/tip/${tip.slug || tip.id}`;

      return `
    <item>
      <title>${xmlCdata(title)}</title>
      <link>${escapeXml(link)}</link>
      <guid isPermaLink="true">${escapeXml(link)}</guid>
      <description>${xmlCdata(desc)}</description>
      <pubDate>${escapeXml(pubDate)}</pubDate>
      <source url="${escapeXml(tip.url)}">${escapeXml(tip.source.name)}</source>
      ${tip.categories.map((c) => `<category>${escapeXml(c)}</category>`).join('\n      ')}
    </item>`;
    })
    .join('');

  const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Tech Tips Hub (English)</title>
    <link>${escapeXml(`${SITE_URL}/en`)}</link>
    <description>Handcrafted practical tech tricks and shortcuts from across the web</description>
    <language>en-US</language>
    <atom:link href="${escapeXml(`${SITE_URL}/en/rss.xml`)}" rel="self" type="application/rss+xml"/>
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

