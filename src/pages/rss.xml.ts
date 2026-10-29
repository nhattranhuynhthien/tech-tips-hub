import { GET as getViFeed } from './vi/rss.xml';

export async function GET() {
  return getViFeed();
}

