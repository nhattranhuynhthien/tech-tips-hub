type AnyRecord = Record<string, any>;
type Lang = 'vi' | 'en';
const runtime = globalThis as typeof globalThis & { process?: { env: Record<string, string | undefined> } };

const API = 'https://api.telegram.org';
const GITHUB_API = 'https://api.github.com';
const PENDING = 'pending';
const INBOX_LABEL = 'community-inbox';
const MAX_SUMMARY = 300;
const MAX_URL_LENGTH = 2048;
const MAX_BODY_BYTES = 524288;
const ALLOWED_TAGS = new Set([
  'android', 'ios', 'windows', 'macos', 'linux', 'browser', 'office', 'security', 'ai', 'dev', 'hardware', 'web', 'khac',
]);
const TRACKING_PARAM_RE = /^(utm_.+|fbclid|gclid|msclkid|ref|source|mc_cid|mc_eid|igshid|si|spm)$/i;
const IPV4_RE = /^\d+\.\d+\.\d+\.\d+$/;
const PRIVATE_IPV4_RE = /^(0\.|10\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|127\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|192\.0\.0\.|192\.0\.2\.|192\.168\.|198\.1[89]\.|198\.51\.100\.|203\.0\.113\.|22[4-9]\.|23\d\.|24\d\.|25[0-5]\.)/;

export class UserFacingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'UserFacingError';
  }
}

// Node.js Vercel Functions read duration settings from this exported config.
export const config = { maxDuration: 60 };

function env(name: string, fallback = ''): string { return runtime.process?.env[name]?.trim() || fallback; }

function adminIds(): string[] {
  return env('ADMIN_IDS').split(',').map((value) => value.trim()).filter(Boolean);
}

// So sánh chuỗi theo thời gian hằng định để tránh lộ secret qua timing.
function safeEqual(a: string, b: string): boolean {
  const aBytes = new TextEncoder().encode(a);
  const bBytes = new TextEncoder().encode(b);
  const maxLen = Math.max(aBytes.length, bBytes.length);
  let diff = aBytes.length ^ bBytes.length;
  for (let i = 0; i < maxLen; i += 1) {
    diff |= (aBytes[i] ?? 0) ^ (bBytes[i] ?? 0);
  }
  return diff === 0;
}

function headerValue(headers: AnyRecord | undefined, name: string): string {
  if (!headers || typeof headers !== 'object' || Array.isArray(headers)) return '';
  const lower = name.toLowerCase();
  let matched: string | undefined;
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() !== lower) continue;
    // Reject mixed-case duplicate headers, header arrays, and non-string objects coercing via toString().
    if (matched !== undefined || typeof value !== 'string') return '';
    matched = value;
  }
  return matched ?? '';
}
function networkErrorDetail(error: unknown): string {
  const value = error as { name?: string; message?: string; cause?: { code?: string; message?: string } };
  const parts = [value?.name, value?.message, value?.cause?.code, value?.cause?.message].filter(Boolean);
  return parts.join(' | ') || 'unknown network error';
}
function decodeBase64Utf8(value: string): string {
  const binary = atob(value.replace(/\s/g, ''));
  return new TextDecoder().decode(Uint8Array.from(binary, (character) => character.charCodeAt(0)));
}
function encodeBase64Utf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}
function repoParts(): [string, string] {
  const parts = env('GITHUB_REPO').split('/');
  if (parts.length !== 2 || parts.some((part) => !part)) throw new Error('GITHUB_REPO is not configured');
  return [parts[0], parts[1]];
}
function cleanText(value: unknown, limit = 2000): string {
  return String(value ?? '').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '').trim().slice(0, limit);
}
function truncateHtmlSafe(html: string, limit: number): string {
  if (html.length <= limit) return html;
  let cut = html.slice(0, limit);
  // Strip any partial HTML entity (&amp, &qu, &#12, &) or partial tag (<b) at the truncation boundary.
  cut = cut.replace(/&[a-zA-Z0-9#]*$/, '');
  cut = cut.replace(/<[^>]*$/, '');
  return cut;
}
function escapeHtml(value: unknown, rawLimit = 500, escapedLimit = 1200): string {
  const escaped = cleanText(value, rawLimit)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  return truncateHtmlSafe(escaped, escapedLimit);
}
export function languageOf(text: string): Lang { return /[ăâđêôơưáàảãạấầẩẫậắằẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủụứừửữựýỳỷỹỵ]/i.test(text) ? 'vi' : 'en'; }
function replyText(lang: Lang, vi: string, en: string): string { return lang === 'vi' ? vi : en; }
async function sha1(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-1', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((part) => part.toString(16).padStart(2, '0')).join('');
}

export function normalizeUrl(input: string): string {
  const raw = String(input ?? '').trim();
  if (!raw || raw.length > MAX_URL_LENGTH || /[\u0000-\u001F\u007F]/.test(raw)) {
    throw new Error('Invalid URL: URL is empty, malformed, or exceeds 2048 characters');
  }
  const authorityMatch = raw.match(/^https?:\/\/([^/?#]+)/i);
  const rawAuthority = authorityMatch?.[1] ?? '';
  if (!authorityMatch || !rawAuthority || rawAuthority.includes('\\') || rawAuthority.includes('@')) {
    throw new Error('Only public HTTP(S) links are accepted');
  }
  const parsed = new URL(raw);
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error('Only public HTTP(S) links are accepted');
  }
  const host = parsed.hostname.toLowerCase();
  const normalizedHost = host.replace(/\.+$/, '');
  const rawHost = rawAuthority.startsWith('[')
    ? rawAuthority.toLowerCase()
    : rawAuthority.replace(/:\d*$/, '').toLowerCase();
  if (
    !normalizedHost ||
    !normalizedHost.includes('.') ||
    host.endsWith('.') ||
    host.includes('..') ||
    host.startsWith('[') ||
    normalizedHost === 'localhost' ||
    normalizedHost.endsWith('.localhost') ||
    normalizedHost.endsWith('.local') ||
    normalizedHost.endsWith('.internal') ||
    normalizedHost.endsWith('.home.arpa') ||
    normalizedHost.endsWith('.lan') ||
    normalizedHost === 'metadata.goog' ||
    normalizedHost.endsWith('.metadata.goog') ||
    (IPV4_RE.test(normalizedHost) && (rawHost !== normalizedHost || PRIVATE_IPV4_RE.test(normalizedHost)))
  ) {
    throw new Error('Only public HTTP(S) links are accepted');
  }
  const queryKeys: string[] = [];
  parsed.searchParams.forEach((_value, key) => queryKeys.push(key));
  queryKeys.forEach((key) => { if (TRACKING_PARAM_RE.test(key)) parsed.searchParams.delete(key); });
  parsed.hash = '';
  if (parsed.pathname !== '/') parsed.pathname = parsed.pathname.replace(/\/+$/, '');
  parsed.searchParams.sort();
  const normalized = parsed.toString();
  if (normalized.length > MAX_URL_LENGTH) {
    throw new Error('Invalid URL: URL exceeds 2048 characters');
  }
  return normalized;
}

export function sourceFor(url: string, forwardedName = ''): { type: string; name: string } {
  const hostname = new URL(url).hostname.toLowerCase().replace(/^www\./, '');
  if (/(^|\.)facebook\.com$|(^|\.)fb\.com$|(^|\.)fb\.watch$/.test(hostname)) return { type: 'community-facebook', name: forwardedName || 'Nhóm Facebook' };
  if (hostname === 't.me' || hostname.endsWith('.t.me')) return { type: 'community-telegram', name: forwardedName || 'Kênh Telegram' };
  return { type: 'community-web', name: forwardedName || hostname };
}
export function summarize(value: string): string {
  const text = cleanText(value, 1200);
  return text.length > MAX_SUMMARY ? `${text.slice(0, MAX_SUMMARY - 1)}…` : text;
}

async function telegram(method: string, payload: AnyRecord): Promise<any> {
  const token = env('TELEGRAM_BOT_TOKEN');
  if (!token) throw new Error('Telegram bot is not configured');
  let response: Response;
  try {
    response = await fetch(`${API}/bot${token}/${method}`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
      signal: AbortSignal.timeout(20000),
    });
  } catch (error) {
    throw new Error(`Telegram API ${method} request failed: ${networkErrorDetail(error)}`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) throw new Error(`Telegram API request failed (${response.status})`);
  return data.result;
}

async function github(path: string, init: RequestInit = {}): Promise<any> {
  const token = env('GITHUB_TOKEN');
  if (!token) throw new Error('GitHub token is not configured');
  const method = (init.method || 'GET').toUpperCase();
  const retryable = method === 'GET';
  let response: Response | undefined;
  for (let attempt = 0; attempt < (retryable ? 3 : 1); attempt += 1) {
    try {
      response = await fetch(`${GITHUB_API}${path}`, {
        ...init,
        headers: {
          accept: 'application/vnd.github+json', authorization: `Bearer ${token}`,
          'x-github-api-version': '2022-11-28', 'content-type': 'application/json',
          ...(init.headers || {}),
        },
        signal: AbortSignal.timeout(12000),
      });
      break;
    } catch (error) {
      if (retryable && attempt < 2) {
        await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
        continue;
      }
      throw new Error(`GitHub API ${method} ${path.split('?')[0]} request failed: ${networkErrorDetail(error)}`);
    }
  }
  if (!response) throw new Error(`GitHub API ${method} ${path.split('?')[0]} returned no response`);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`GitHub API request failed (${response.status})`);
  return body;
}
function repoPath(suffix: string): string {
  const [owner, repo] = repoParts();
  return `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}${suffix}`;
}
function branch(): string { return encodeURIComponent(env('GITHUB_BRANCH', 'main')); }

async function ensureLabel(name: string, color = '6f42c1'): Promise<void> {
  try {
    await github(repoPath('/labels'), { method: 'POST', body: JSON.stringify({ name, color }) });
  } catch (error) {
    // GitHub returns 422 when the repository already has the label.
    if (!(error instanceof Error) || !error.message.includes('(422)')) throw error;
  }
}
async function listIssues(options: { labels?: string[]; state?: 'open' | 'closed' | 'all'; since?: string; maxPages?: number } = {}): Promise<AnyRecord[]> {
  const results: AnyRecord[] = [];
  const maxPages = options.maxPages ?? 5;
  // GitHub returns at most 100 items per page; walk pages until exhausted (capped).
  for (let page = 1; page <= maxPages; page += 1) {
    const params = new URLSearchParams({
      state: options.state || 'open',
      per_page: '100',
      page: String(page),
      sort: 'created',
      direction: 'desc',
    });
    if (options.labels?.length) params.set('labels', options.labels.join(','));
    if (options.since) params.set('since', options.since);
    const batch = await github(repoPath(`/issues?${params}`));
    if (!Array.isArray(batch) || batch.length === 0) break;
    results.push(...batch);
    if (batch.length < 100) break;
  }
  return results;
}
async function getIssue(number: number): Promise<AnyRecord> { return github(repoPath(`/issues/${number}`)); }
async function updateIssue(number: number, patch: AnyRecord): Promise<AnyRecord> {
  return github(repoPath(`/issues/${number}`), { method: 'PATCH', body: JSON.stringify(patch) });
}

function parseIssueBody(body: string): AnyRecord {
  const match = body.match(/```json\s*([\s\S]*)```\s*$/i);
  if (!match) throw new Error('Issue data block is missing');
  const parsed = JSON.parse(match[1]);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Issue data block is invalid');
  return parsed;
}
function makeIssueBody(record: AnyRecord, userId: string): string {
  const safeJson = JSON.stringify({ ...record, telegramUserId: userId }, null, 2).replace(/`/g, '\\u0060');
  return [
    'Hộp thư cộng đồng Tech Tips Hub. Chỉ nội dung đã duyệt mới được đưa lên trang.',
    '', '```json', safeJson, '```',
  ].join('\n');
}
function issueBelongsToUser(issue: AnyRecord, userId: string): boolean {
  if (issue.labels?.some((label: AnyRecord) => label.name === `user-${userId}`)) return true;
  try {
    const record = parseIssueBody(issue.body || '');
    return String(record.telegramUserId ?? '') === userId;
  } catch {
    return false;
  }
}
async function fetchIssueOrThrow(issueNumber: number): Promise<AnyRecord> {
  try {
    return await getIssue(issueNumber);
  } catch (error) {
    if (error instanceof Error && error.message.includes('(404)')) {
      throw new UserFacingError(`Không tìm thấy bài #${issueNumber}.`);
    }
    throw error;
  }
}

async function readCommunity(): Promise<{ entries: AnyRecord[]; sha?: string }> {
  try {
    const data = await github(repoPath(`/contents/data/community.json?ref=${branch()}`));
    const text = decodeBase64Utf8(data.content || '');
    const entries = JSON.parse(text);
    if (!Array.isArray(entries)) throw new Error('community.json must be an array');
    return { entries, sha: data.sha };
  } catch (error) {
    if (error instanceof Error && error.message.includes('(404)')) return { entries: [] };
    throw error;
  }
}
async function appendCommunity(record: AnyRecord): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const current = await readCommunity();
    if (current.entries.some((entry) => entry.id === record.id || entry.url === record.url)) return;
    const entries = [...current.entries, record];
    const payload: AnyRecord = {
      message: `chore(community): approve ${record.id}`,
      content: encodeBase64Utf8(`${JSON.stringify(entries, null, 2)}\n`),
      branch: env('GITHUB_BRANCH', 'main'),
    };
    if (current.sha) payload.sha = current.sha;
    try {
      await github(repoPath('/contents/data/community.json'), { method: 'PUT', body: JSON.stringify(payload) });
      return;
    } catch (error) {
      if (attempt === 2 || !(error instanceof Error) || !['(409)', '(422)'].some((code) => error.message.includes(code))) throw error;
    }
  }
}

async function send(chatId: number | string, text: string, extra: AnyRecord = {}): Promise<void> {
  const cleaned = String(text ?? '').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '').trim();
  const safeText = extra.parse_mode === 'HTML'
    ? truncateHtmlSafe(cleaned, 3900)
    : cleaned.slice(0, 3900);
  await telegram('sendMessage', { chat_id: chatId, text: safeText, ...extra });
}
async function sendAdminCard(issue: AnyRecord, record: AnyRecord): Promise<void> {
  const admins = adminIds();
  const lang: Lang = record?.originalLang === 'en' ? 'en' : 'vi';
  const titleMap = record?.title && typeof record.title === 'object' && !Array.isArray(record.title) ? record.title : {};
  const summaryMap = record?.summary && typeof record.summary === 'object' && !Array.isArray(record.summary) ? record.summary : {};
  const title = titleMap[lang] || titleMap.vi || titleMap.en || '(chưa có tiêu đề)';
  const summary = summaryMap[lang] || summaryMap.vi || summaryMap.en || '';
  const text = [
    `<b>Bài chờ duyệt #${issue.number}</b>`,
    `Nguồn: ${escapeHtml(record?.sourceName || '(không rõ nguồn)', 80, 300)} (${escapeHtml(record?.sourceType || 'community', 40, 120)})`,
    `Tiêu đề: ${escapeHtml(title, 160, 600)}`,
    `Tóm tắt: ${escapeHtml(summary, 260, 900)}`,
    `Link: ${escapeHtml(record?.url || 'Không có link công khai', 1000, 1500)}`,
  ].join('\n');
  const keyboard = { inline_keyboard: [[
    { text: '✅ Duyệt', callback_data: `ap:${issue.number}` },
    { text: '⛔ Từ chối', callback_data: `rj:${issue.number}` },
  ]] };
  for (const adminId of admins) await send(adminId, text, { parse_mode: 'HTML', reply_markup: keyboard, disable_web_page_preview: true });
}

function extractUrl(text: string): string | undefined {
  const match = text.match(/https?:\/\/[^\s<>"'`]+/i);
  if (!match) return undefined;
  return match[0].replace(/[),.!?\]>'"]+$/, '');
}
async function submittedRecord(rawUrl: string, note: string, sourceName = '', originalLang?: Lang): Promise<AnyRecord> {
  const url = normalizeUrl(rawUrl);
  const source = sourceFor(url, cleanText(sourceName, 120));
  const lang = originalLang || languageOf(note);
  const cleanNote = cleanText(note, 1200);
  const title = cleanNote.split(/\r?\n/)[0]?.slice(0, 160) || new URL(url).hostname;
  const summary = summarize(cleanNote);
  return {
    id: (await sha1(url)).slice(0, 16), title: { vi: lang === 'vi' ? title : null, en: lang === 'en' ? title : null },
    summary: { vi: lang === 'vi' ? summary : null, en: lang === 'en' ? summary : null },
    url, sourceType: source.type, sourceName: source.name, originalLang: lang,
    submittedBy: 'Cộng đồng đóng góp', publishedAt: new Date().toISOString(), tags: [],
  };
}

async function isDuplicate(id: string, url: string): Promise<boolean> {
  const community = await readCommunity();
  if (community.entries.some((entry) => entry.id === id || entry.id?.startsWith(id) || entry.url === url)) return true;
  const issues = await listIssues({ labels: [PENDING], state: 'open' });
  return issues.some((issue) => String(issue.title || '').includes(id));
}
async function createSubmission(record: AnyRecord, userId: string, chatId: number, lang: Lang): Promise<void> {
  const limit = Math.max(1, Math.min(100, Number(env('SUBMIT_LIMIT_PER_DAY', '10')) || 10));
  const oldest = new Date(Date.now() - 86400000);
  const since = oldest.toISOString();
  const recent = await listIssues({ labels: [INBOX_LABEL], state: 'all', since, maxPages: 2 });
  const recentCount = recent.filter(
    (issue) => issueBelongsToUser(issue, userId) && Date.parse(issue.created_at) >= oldest.getTime(),
  ).length;
  if (recentCount >= limit) {
    await send(chatId, replyText(lang, 'Bạn đã đạt giới hạn gửi bài hôm nay. Hãy thử lại sau.', 'You have reached today’s submission limit. Please try again later.'));
    return;
  }
  if (await isDuplicate(record.id, record.url)) {
    await send(chatId, replyText(lang, 'Link này đã có trong hệ thống.', 'This link is already in the system.'));
    return;
  }
  const sourceLabel = record.sourceType.replace('community-', 'src-');
  for (const label of [INBOX_LABEL, PENDING, sourceLabel]) await ensureLabel(label);
  const title = record.title[record.originalLang] || record.title.vi || record.title.en || new URL(record.url).hostname;
  const issue = await github(repoPath('/issues'), {
    method: 'POST', body: JSON.stringify({
      title: `[${record.id}] ${cleanText(title, 100)}`,
      body: makeIssueBody(record, userId), labels: [INBOX_LABEL, PENDING, sourceLabel],
    }),
  });
  await sendAdminCard(issue, record);
  await send(chatId, replyText(lang, 'Đã nhận. Bài sẽ được duyệt sớm.', 'Received. Your tip will be reviewed soon.'));
}

async function pendingIssues(maxPages = 2): Promise<AnyRecord[]> {
  return listIssues({ labels: [PENDING], state: 'open', maxPages });
}
export function isAdmin(userId: unknown): boolean {
  let id: string;
  if (typeof userId === 'string') {
    id = userId;
  } else if (typeof userId === 'number' && Number.isSafeInteger(userId)) {
    id = String(userId);
  } else {
    return false;
  }
  if (!id || id !== id.trim()) return false;
  return adminIds().includes(id);
}

async function approve(issueNumber: number): Promise<void> {
  const issue = await fetchIssueOrThrow(issueNumber);
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) {
    throw new UserFacingError('Bài viết này đã được xử lý trước đó.');
  }
  const record = parseIssueBody(issue.body || '');
  if (typeof record.url !== 'string' || !record.url.trim()) {
    throw new UserFacingError('Không thể duyệt bài chưa có link công khai.');
  }
  let safeUrl: string;
  try {
    safeUrl = normalizeUrl(record.url);
  } catch {
    throw new UserFacingError('Link trong bài viết không hợp lệ hoặc không công khai.');
  }
  await appendCommunity({
    id: record.id, title: record.title, summary: record.summary, url: safeUrl,
    sourceType: record.sourceType, sourceName: record.sourceName,
    originalLang: record.originalLang, submittedBy: record.submittedBy || 'Cộng đồng đóng góp',
    publishedAt: record.publishedAt, approvedAt: new Date().toISOString(), tags: record.tags || [],
  });
  await ensureLabel('approved');
  const existingLabels = (issue.labels || [])
    .map((label: AnyRecord) => label.name)
    .filter((name: string) => name !== PENDING && name !== 'approved' && name !== 'rejected');
  await updateIssue(issueNumber, { state: 'closed', state_reason: 'completed', labels: [...new Set(['approved', ...existingLabels])] });
}
async function reject(issueNumber: number): Promise<void> {
  const issue = await fetchIssueOrThrow(issueNumber);
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) {
    throw new UserFacingError('Bài viết này đã được xử lý trước đó.');
  }
  await ensureLabel('rejected');
  const existingLabels = (issue.labels || [])
    .map((label: AnyRecord) => label.name)
    .filter((name: string) => name !== PENDING && name !== 'approved' && name !== 'rejected');
  await updateIssue(issueNumber, { state: 'closed', state_reason: 'not_planned', labels: [...new Set(['rejected', ...existingLabels])] });
}

async function clearInlineKeyboard(cb: AnyRecord): Promise<void> {
  const chatId = cb.message?.chat?.id;
  const messageId = cb.message?.message_id;
  if (!chatId || !messageId) return;
  await telegram('editMessageReplyMarkup', {
    chat_id: chatId,
    message_id: messageId,
    reply_markup: { inline_keyboard: [] },
  }).catch(() => {});
}

async function onCallback(cb: AnyRecord): Promise<void> {
  if (!cb || typeof cb !== 'object' || Array.isArray(cb) || typeof cb.id !== 'string' || !cb.id.trim()) return;
  const admin = isAdmin(cb.from?.id);
  if (!admin) {
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: 'Không có quyền', show_alert: true });
    return;
  }
  const cbMatch = String(cb.data || '').match(/^(ap|rj):([1-9]\d*)$/);
  const action = cbMatch?.[1];
  const number = cbMatch ? Number(cbMatch[2]) : NaN;
  if (!action || !Number.isSafeInteger(number) || number <= 0) {
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: 'Yêu cầu không hợp lệ', show_alert: true });
    return;
  }
  try {
    if (action === 'ap') await approve(number); else await reject(number);
    await clearInlineKeyboard(cb);
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: action === 'ap' ? 'Đã đăng' : 'Đã từ chối' });
    if (cb.message?.chat?.id) await send(cb.message.chat.id, action === 'ap' ? `Đã đăng bài #${number}.` : `Đã từ chối bài #${number}.`);
  } catch (error) {
    if (error instanceof UserFacingError) {
      await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: cleanText(error.message, 180), show_alert: true });
      await clearInlineKeyboard(cb);
      return;
    }
    const text = error instanceof Error ? error.message : 'Không xử lý được yêu cầu';
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: cleanText(text, 180), show_alert: true }).catch(() => {});
    throw error;
  }
}

async function editIssue(message: AnyRecord, args: string): Promise<void> {
  const match = args.match(/^(\d+)\s+([\s\S]+)$/);
  if (!match) throw new UserFacingError('Cú pháp: /sua <issue_id> tiêu đề | tóm tắt');
  const issueNumber = Number(match[1]);
  if (!Number.isSafeInteger(issueNumber) || issueNumber <= 0) throw new UserFacingError('ID bài viết không hợp lệ.');
  const sepIdx = match[2].indexOf('|');
  if (sepIdx === -1) throw new UserFacingError('Cần nhập cả tiêu đề và tóm tắt, ngăn cách bằng dấu |.');
  const title = cleanText(match[2].slice(0, sepIdx), 1000);
  const summary = cleanText(match[2].slice(sepIdx + 1), 1000);
  if (!title || !summary) throw new UserFacingError('Cần nhập cả tiêu đề và tóm tắt.');
  const issue = await fetchIssueOrThrow(issueNumber);
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) {
    throw new UserFacingError('Chỉ có thể sửa bài đang chờ duyệt.');
  }
  const record = parseIssueBody(issue.body || '');
  const lang: Lang = record.originalLang === 'en' ? 'en' : 'vi';
  if (!record.title || typeof record.title !== 'object' || Array.isArray(record.title)) record.title = { vi: null, en: null };
  if (!record.summary || typeof record.summary !== 'object' || Array.isArray(record.summary)) record.summary = { vi: null, en: null };
  record.title[lang] = title.slice(0, 160);
  record.summary[lang] = summary.slice(0, MAX_SUMMARY);
  await updateIssue(issue.number, { title: `[${record.id}] ${title.slice(0, 100)}`, body: makeIssueBody(record, String(record.telegramUserId || '')) });
  await send(message.chat.id, `Đã cập nhật bài #${issue.number}.`);
}
async function tagIssue(message: AnyRecord, args: string): Promise<void> {
  const match = args.match(/^(\d+)\s+(.+)$/);
  if (!match) throw new UserFacingError('Cú pháp: /tag <issue_id> android,ios,windows,macos,linux,browser,office,security,ai,dev,hardware');
  const issueNumber = Number(match[1]);
  if (!Number.isSafeInteger(issueNumber) || issueNumber <= 0) throw new UserFacingError('ID bài viết không hợp lệ.');
  const tags = [...new Set(match[2].split(',').map((tag) => tag.trim().toLowerCase()).filter((tag) => ALLOWED_TAGS.has(tag)).map((tag) => (tag === 'web' ? 'browser' : tag)))];
  if (!tags.length) throw new UserFacingError('Không có tag hợp lệ.');
  const issue = await fetchIssueOrThrow(issueNumber);
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) {
    throw new UserFacingError('Chỉ có thể gắn tag cho bài đang chờ duyệt.');
  }
  const record = parseIssueBody(issue.body || '');
  record.tags = tags;
  await updateIssue(issue.number, { body: makeIssueBody(record, String(record.telegramUserId || '')) });
  await send(message.chat.id, `Đã gắn tag cho bài #${issue.number}: ${tags.join(', ')}`);
}

async function onMessage(message: AnyRecord): Promise<void> {
  if (!message || typeof message !== 'object' || Array.isArray(message)) return;
  if (!message.chat || typeof message.chat !== 'object' || !message.from || typeof message.from !== 'object') return;
  if ((typeof message.chat.id !== 'number' && typeof message.chat.id !== 'string') || !message.chat.id) return;
  if ((typeof message.from.id !== 'number' && typeof message.from.id !== 'string') || !message.from.id) return;
  const text = cleanText(message.text || message.caption || '', 5000);
  const userId = String(message.from.id);
  const chatId = message.chat.id;
  const commandMatch = text.match(/^\/(\w+)(?:@\w+)?(?:\s+([\s\S]*))?$/);
  const command = commandMatch?.[1]?.toLowerCase();
  const args = commandMatch?.[2] || '';
  const lang = ['start', 'trangthai', 'danhsach'].includes(command || '') || (command === 'gui' && !args)
    ? 'vi'
    : languageOf(command === 'gui' ? args : text);

  try {
    if (command === 'start') {
      await send(chatId, replyText(lang,
        `Chào bạn! Gửi /gui <link> <ghi chú ngắn> hoặc gửi link trực tiếp. Bạn cũng có thể forward bài từ kênh Telegram công khai. Chỉ gửi tiêu đề/tóm tắt do bạn viết; không gửi toàn văn. Telegram ID của bạn: ${userId}.`,
        `Hello! Send /gui <link> <short note>, a link, or forward a public Telegram channel post. Share only a title/summary in your own words, not the full text. Your Telegram ID: ${userId}.`));
      return;
    }
    if (command === 'trangthai') {
      const issues = (await listIssues({ labels: [INBOX_LABEL], state: 'all', maxPages: 2 }))
        .filter((issue) => issueBelongsToUser(issue, userId));
      const status = issues.slice(0, 10).map((issue) => `${issue.labels?.some((label: AnyRecord) => label.name === PENDING) ? '⏳ Chờ duyệt' : issue.labels?.some((label: AnyRecord) => label.name === 'approved') ? '✅ Đã đăng' : '⛔ Từ chối'} — ${cleanText(issue.title, 120)} (#${issue.number})`);
      await send(chatId, status.length ? status.join('\n') : replyText(lang, 'Bạn chưa gửi bài nào.', 'You have not submitted any tips yet.'));
      return;
    }
    if (command === 'danhsach' || command === 'sua' || command === 'tag') {
      if (!isAdmin(userId)) { await send(chatId, 'Không có quyền.'); return; }
      if (command === 'danhsach') {
        const issues = await pendingIssues();
        if (!issues.length) {
          await send(chatId, 'Không có bài chờ duyệt.');
          return;
        }
        for (const issue of issues.slice(0, 10)) {
          let record: AnyRecord | undefined;
          try {
            const parsed = parseIssueBody(issue.body || '');
            if (parsed && typeof parsed === 'object' && parsed.title && typeof parsed.title === 'object' && !Array.isArray(parsed.title)) {
              record = parsed;
            }
          } catch {
            /* Fallback if body format is customized */
          }
          if (record) {
            await sendAdminCard(issue, record);
          } else {
            const keyboard = { inline_keyboard: [[
              { text: '✅ Duyệt', callback_data: `ap:${issue.number}` },
              { text: '⛔ Từ chối', callback_data: `rj:${issue.number}` },
            ]] };
            await send(chatId, `#${issue.number} ${cleanText(issue.title, 150)}`, { reply_markup: keyboard });
          }
        }
      } else if (command === 'sua') await editIssue(message, args);
      else await tagIssue(message, args);
      return;
    }
    if (!text && !message.forward_origin) return;

    let rawUrl = extractUrl(command === 'gui' ? args : text);
    let note = command === 'gui' ? args.replace(rawUrl || '', '').trim() : text.replace(rawUrl || '', '').trim();
    let forwardedName = '';
    const facebookGroup = note.match(/^\[([^\]]{1,80})\]\s*/);
    if (facebookGroup && rawUrl) {
      try {
        if (sourceFor(normalizeUrl(rawUrl)).type === 'community-facebook') {
          forwardedName = facebookGroup[1].trim();
          note = note.slice(facebookGroup[0].length);
        }
      } catch { /* The regular validation below returns a user-friendly link error. */ }
    }
    const origin = message.forward_origin;
    if (origin?.type === 'channel' && origin.chat?.username && origin.message_id) {
      forwardedName = origin.chat.title || origin.chat.username;
      rawUrl ||= `https://t.me/${origin.chat.username}/${origin.message_id}`;
      note ||= cleanText(message.text || message.caption || '', MAX_SUMMARY);
    } else if (origin && !rawUrl) {
      await send(chatId, replyText(lang, 'Tin forward không có link công khai. Hãy gửi /gui kèm link công khai để quản trị viên xem xét.', 'This forwarded message has no public link. Send /gui with a public link for review.'));
      return;
    }
    if (!rawUrl) {
      await send(chatId, replyText(lang, 'Mình chưa thấy link. Gửi /gui <link> <ghi chú> nhé.', 'I could not find a link. Send /gui <link> <short note>.'));
      return;
    }
    if (cleanText(note, 1200).length < 8) {
      await send(chatId, replyText(
        lang,
        'Vui lòng kèm tiêu đề hoặc ghi chú ngắn (ít nhất vài từ) mô tả mẹo công nghệ. Ví dụ: /gui https://... Cách tắt quảng cáo trên Windows 11',
        'Please include a short title or note describing the tip. Example: /gui https://... How to disable ads on Windows 11',
      ));
      return;
    }
    try {
      const record = await submittedRecord(rawUrl, note, forwardedName, languageOf(note || text));
      await createSubmission(record, userId, chatId, lang);
    } catch (error) {
      const textMessage = error instanceof Error ? error.message : '';
      if (textMessage.includes('Invalid URL') || textMessage.includes('Only public')) {
        await send(chatId, replyText(lang, 'Link không hợp lệ. Hãy gửi link công khai bắt đầu bằng https://.', 'That link is invalid. Please send a public https:// link.'));
        return;
      }
      throw error;
    }
  } catch (error) {
    if (error instanceof UserFacingError) {
      await send(chatId, error.message);
      return;
    }
    throw error;
  }
}

export default async function handler(req: any, res: any): Promise<void> {
  const method = String(req?.method || '').toUpperCase();
  if (method === 'GET' || method === 'HEAD') {
    res.status(200).send('ok');
    return;
  }
  if (method !== 'POST') {
    res.status(405).send('method not allowed');
    return;
  }
  const secret = env('TELEGRAM_WEBHOOK_SECRET');
  const provided = headerValue(req.headers, 'x-telegram-bot-api-secret-token');
  if (!secret || !safeEqual(provided, secret)) {
    res.status(401).send('unauthorized');
    return;
  }

  const contentLengthRaw = headerValue(req.headers, 'content-length').trim();
  if (contentLengthRaw) {
    const contentLength = Number(contentLengthRaw);
    if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
      res.status(413).send('payload too large');
      return;
    }
  }

  let update: AnyRecord;
  try {
    if (typeof req.body === 'string') {
      if (new TextEncoder().encode(req.body).byteLength > MAX_BODY_BYTES) {
        res.status(413).send('payload too large');
        return;
      }
      update = JSON.parse(req.body);
    } else if (req.body instanceof Uint8Array) {
      if (req.body.byteLength > MAX_BODY_BYTES) {
        res.status(413).send('payload too large');
        return;
      }
      update = JSON.parse(new TextDecoder().decode(req.body));
    } else if (req.body && typeof req.body === 'object' && !Array.isArray(req.body)) {
      const serialized = JSON.stringify(req.body);
      if (typeof serialized !== 'string' || new TextEncoder().encode(serialized).byteLength > MAX_BODY_BYTES) {
        res.status(413).send('payload too large');
        return;
      }
      update = req.body;
    } else {
      res.status(400).send('bad request');
      return;
    }
    if (!update || typeof update !== 'object' || Array.isArray(update)) {
      res.status(400).send('bad request');
      return;
    }
  } catch {
    res.status(400).send('bad request');
    return;
  }

  try {
    if (update.callback_query) await onCallback(update.callback_query);
    else if (update.message) await onMessage(update.message);
  } catch (error) {
    console.error('telegram handler error', error instanceof Error ? error.message : 'unknown error');
    for (const id of adminIds()) {
      try { await send(id, 'Có lỗi khi xử lý một cập nhật Telegram. Xem log function để kiểm tra.'); } catch { /* Best effort. */ }
    }
  } finally {
    // Chỉ phản hồi HTTP 200 sau khi toàn bộ tác vụ gửi tin nhắn Telegram đã hoàn thành
    if (!res.writableEnded) {
      res.status(200).send('ok');
    }
  }
}
