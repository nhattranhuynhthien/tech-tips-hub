import { createFullTipsResponse } from '../../lib/tipsApi';

export async function GET() {
  return createFullTipsResponse();
}
