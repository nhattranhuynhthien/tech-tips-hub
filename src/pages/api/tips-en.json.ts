import { createLocalizedTipsResponse } from '../../lib/tipsApi';

export async function GET() {
  return createLocalizedTipsResponse('en', 'tips');
}
