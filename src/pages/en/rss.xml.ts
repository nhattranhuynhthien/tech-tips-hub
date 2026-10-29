import { getAllTips } from '../../lib/data';

export async function GET() {
  const tips = getAllTips().slice(0, 50);

  const itemsXml = tips
    .map((tip) => {
      const title = tip.title.en || tip.title.vi || '';
      const desc = tip.summary.en || tip.summary.vi || '';
      const pubDate = new Date(tip.published_at || tip.fetched_at).toUTCString();
      const link = `https://techtipshub.pages.dev/en/tip/${tip.id}`;

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
    <title>Tech Tips Hub (English)</title>
    <link>https://techtipshub.pages.dev/en</link>
    <description>Handcrafted practical tech tricks and shortcuts from across the web</description>
    <language>en-US</language>
    <atom:link href="https://techtipshub.pages.dev/en/rss.xml" rel="self" type="application/rss+xml"/>
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

