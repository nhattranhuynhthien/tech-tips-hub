/**
 * Validate external URLs to allow only http: and https: protocols.
 * Rejects javascript:, data:, vbscript:, file:, and malformed URLs.
 */
export function safeExternalUrl(url: unknown): string {
  if (typeof url !== 'string') return '#';
  const trimmed = url.trim();
  if (!trimmed) return '#';
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString();
    }
  } catch {
    return '#';
  }
  return '#';
}
