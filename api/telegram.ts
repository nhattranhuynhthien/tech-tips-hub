type AnyRecord = Record<string, any>;
type Lang = 'vi' | 'en';
const runtime = globalThis as typeof globalThis & { process?: { env: Record<string, string | undefined> } };

const API = 'https://api.telegram.org';
const GITHUB_API = 'https://api.github.com';
const PENDING = 'pending';
const MAX_SUMMARY = 300;
const ALLOWED_TAGS = new Set(['android', 'ios', 'windows', 'macos', 'linux', 'web', 'ai', 'khac']);

// Node.js Vercel Functions read duration settings from this exported config.
export const config = { maxDuration: 60 };

function env(name: string, fallback = ''): string { return runtime.process?.env[name]?.trim() || fallback; }
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
function escapeHtml(value: unknown): string {
  return cleanText(value, 1000).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
export function languageOf(text: string): Lang { return /[ăâđêôơưáàảãạấầẩẫậắằẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủụứừửữựýỳỷỹỵ]/i.test(text) ? 'vi' : 'en'; }
function replyText(lang: Lang, vi: string, en: string): string { return lang === 'vi' ? vi : en; }
async function sha1(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-1', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((part) => part.toString(16).padStart(2, '0')).join('');
}

export function normalizeUrl(input: string): string {
  const parsed = new URL(input);
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error('Only public HTTP(S) links are accepted');
  const queryKeys: string[] = [];
  parsed.searchParams.forEach((_value, key) => queryKeys.push(key));
  queryKeys.forEach((key) => { if (/^(utm_.+|fbclid)$/i.test(key)) parsed.searchParams.delete(key); });
  parsed.hash = '';
  if (parsed.pathname !== '/') parsed.pathname = parsed.pathname.replace(/\/+$/, '');
  else parsed.pathname = '';
  parsed.searchParams.sort();
  return parsed.toString().replace(/\/$/, '');
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
    const detail = error instanceof Error ? error.message : 'unknown network error';
    throw new Error(`Telegram API ${method} request failed: ${detail}`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) throw new Error(`Telegram API request failed (${response.status})`);
  return data.result;
}

async function github(path: string, init: RequestInit = {}): Promise<any> {
  const token = env('GITHUB_TOKEN');
  if (!token) throw new Error('GitHub token is not configured');
  const response = await fetch(`${GITHUB_API}${path}`, {
    ...init,
    headers: {
      accept: 'application/vnd.github+json', authorization: `Bearer ${token}`,
      'x-github-api-version': '2022-11-28', 'content-type': 'application/json',
      ...(init.headers || {}),
    },
    signal: AbortSignal.timeout(10000),
  });
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
async function listIssues(query: string): Promise<AnyRecord[]> {
  const [owner] = repoParts();
  const params = new URLSearchParams({ q: `repo:${owner}/${repoParts()[1]} is:issue ${query}`, per_page: '100', sort: 'created', order: 'desc' });
  const result = await github(`/search/issues?${params}`);
  return result.items || [];
}
async function getIssue(number: number): Promise<AnyRecord> { return github(repoPath(`/issues/${number}`)); }
async function updateIssue(number: number, patch: AnyRecord): Promise<AnyRecord> {
  return github(repoPath(`/issues/${number}`), { method: 'PATCH', body: JSON.stringify(patch) });
}

function parseIssueBody(body: string): AnyRecord {
  const match = body.match(/```json\s*([\s\S]*)```\s*$/i);
  if (!match) throw new Error('Issue data block is missing');
  return JSON.parse(match[1]);
}
function makeIssueBody(record: AnyRecord, userId: string): string {
  return [
    'Hộp thư cộng đồng Tech Tips Hub. Chỉ nội dung đã duyệt mới được đưa lên trang.',
    '', '```json', JSON.stringify({ ...record, telegramUserId: userId }, null, 2), '```',
  ].join('\n');
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
  await telegram('sendMessage', { chat_id: chatId, text: cleanText(text, 3900), ...extra });
}
async function sendAdminCard(issue: AnyRecord, record: AnyRecord): Promise<void> {
  const admins = env('ADMIN_IDS').split(',').map((id) => id.trim()).filter(Boolean);
  const lang = record.originalLang as Lang;
  const title = record.title[lang] || record.title.vi || record.title.en || '(chưa có tiêu đề)';
  const summary = record.summary[lang] || '';
  const text = [
    `<b>Bài chờ duyệt #${issue.number}</b>`,
    `Nguồn: ${escapeHtml(record.sourceName)} (${escapeHtml(record.sourceType)})`,
    `Tiêu đề: ${escapeHtml(title)}`, `Tóm tắt: ${escapeHtml(summary)}`,
    `Link: ${escapeHtml(record.url || 'Không có link công khai')}`,
  ].join('\n');
  const keyboard = { inline_keyboard: [[
    { text: '✅ Duyệt', callback_data: `ap:${issue.number}` },
    { text: '⛔ Từ chối', callback_data: `rj:${issue.number}` },
  ]] };
  for (const adminId of admins) await send(adminId, text, { parse_mode: 'HTML', reply_markup: keyboard, disable_web_page_preview: true });
}

function extractUrl(text: string): string | undefined {
  const match = text.match(/https?:\/\/[^\s<>]+/i);
  if (!match) return undefined;
  return match[0].replace(/[),.!?]+$/, '');
}
async function submittedRecord(rawUrl: string, note: string, sourceName = '', originalLang?: Lang): Promise<AnyRecord> {
  const url = normalizeUrl(rawUrl);
  const source = sourceFor(url, sourceName);
  const lang = originalLang || languageOf(note);
  const cleanNote = cleanText(note, 1200);
  const title = cleanNote.split(/\r?\n/)[0]?.slice(0, 160) || new URL(url).hostname;
  const summary = summarize(cleanNote);
  return {
    id: await sha1(url), title: { vi: lang === 'vi' ? title : null, en: lang === 'en' ? title : null },
    summary: { vi: lang === 'vi' ? summary : null, en: lang === 'en' ? summary : null },
    url, sourceType: source.type, sourceName: source.name, originalLang: lang,
    submittedBy: 'Cộng đồng đóng góp', publishedAt: new Date().toISOString(), tags: [],
  };
}

async function isDuplicate(id: string, url: string): Promise<boolean> {
  const community = await readCommunity();
  if (community.entries.some((entry) => entry.id === id || entry.url === url)) return true;
  const issues = await listIssues(`in:title ${id}`);
  return issues.length > 0;
}
async function createSubmission(record: AnyRecord, userId: string, chatId: number, lang: Lang): Promise<void> {
  const limit = Math.max(1, Math.min(100, Number(env('SUBMIT_LIMIT_PER_DAY', '10')) || 10));
  const oldest = new Date(Date.now() - 86400000);
  const since = oldest.toISOString().slice(0, 10);
  const recent = await listIssues(`label:user-${userId} created:>=${since}`);
  if (recent.filter((issue) => Date.parse(issue.created_at) >= oldest.getTime()).length >= limit) {
    await send(chatId, replyText(lang, 'Bạn đã đạt giới hạn gửi bài hôm nay. Hãy thử lại sau.', 'You have reached today’s submission limit. Please try again later.'));
    return;
  }
  if (await isDuplicate(record.id, record.url)) {
    await send(chatId, replyText(lang, 'Link này đã có trong hệ thống.', 'This link is already in the system.'));
    return;
  }
  const userLabel = `user-${userId}`;
  const sourceLabel = record.sourceType.replace('community-', 'src-');
  for (const label of [PENDING, sourceLabel, userLabel]) await ensureLabel(label);
  const title = record.title[record.originalLang] || record.title.vi || record.title.en || new URL(record.url).hostname;
  const issue = await github(repoPath('/issues'), {
    method: 'POST', body: JSON.stringify({
      title: `[${record.id}] ${cleanText(title, 100)}`,
      body: makeIssueBody(record, userId), labels: [PENDING, sourceLabel, userLabel],
    }),
  });
  await sendAdminCard(issue, record);
  await send(chatId, replyText(lang, 'Đã nhận. Bài sẽ được duyệt sớm.', 'Received. Your tip will be reviewed soon.'));
}

async function pendingIssues(): Promise<AnyRecord[]> {
  return listIssues('label:pending');
}
function isAdmin(userId: unknown): boolean { return env('ADMIN_IDS').split(',').map((value) => value.trim()).includes(String(userId)); }

async function approve(issueNumber: number): Promise<void> {
  const issue = await getIssue(issueNumber);
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) throw new Error('Issue is no longer pending');
  const record = parseIssueBody(issue.body || '');
  if (!record.url) throw new Error('Không thể duyệt bài chưa có link công khai.');
  await appendCommunity({
    id: record.id, title: record.title, summary: record.summary, url: record.url,
    sourceType: record.sourceType, sourceName: record.sourceName,
    originalLang: record.originalLang, submittedBy: record.submittedBy || 'Cộng đồng đóng góp',
    publishedAt: record.publishedAt, approvedAt: new Date().toISOString(), tags: record.tags || [],
  });
  await ensureLabel('approved');
  await updateIssue(issueNumber, { state: 'closed', state_reason: 'completed', labels: ['approved', ...issue.labels.map((label: AnyRecord) => label.name).filter((name: string) => name !== PENDING)] });
}
async function reject(issueNumber: number): Promise<void> {
  const issue = await getIssue(issueNumber);
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) throw new Error('Issue is no longer pending');
  await ensureLabel('rejected');
  const labels = (issue.labels || []).map((label: AnyRecord) => label.name).filter((name: string) => name !== PENDING && name !== 'approved' && name !== 'rejected');
  await updateIssue(issueNumber, { state: 'closed', state_reason: 'not_planned', labels: ['rejected', ...labels] });
}

async function onCallback(cb: AnyRecord): Promise<void> {
  const admin = isAdmin(cb.from?.id);
  if (!admin) {
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: 'Không có quyền', show_alert: true });
    return;
  }
  const [action, rawNumber] = String(cb.data || '').split(':');
  const number = Number(rawNumber);
  if (!['ap', 'rj'].includes(action) || !Number.isSafeInteger(number) || number <= 0) {
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: 'Yêu cầu không hợp lệ', show_alert: true });
    return;
  }
  try {
    if (action === 'ap') await approve(number); else await reject(number);
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: action === 'ap' ? 'Đã đăng' : 'Đã từ chối' });
    if (cb.message?.chat?.id) await send(cb.message.chat.id, action === 'ap' ? `Đã đăng bài #${number}.` : `Đã từ chối bài #${number}.`);
  } catch (error) {
    const text = error instanceof Error ? error.message : 'Không xử lý được yêu cầu';
    await telegram('answerCallbackQuery', { callback_query_id: cb.id, text: cleanText(text, 180), show_alert: true });
    throw error;
  }
}

async function editIssue(message: AnyRecord, args: string): Promise<void> {
  const match = args.match(/^(\d+)\s+([\s\S]+)$/);
  if (!match) throw new Error('Cú pháp: /sua <issue_id> tiêu đề | tóm tắt');
  const [title, summary] = match[2].split('|').map((value) => cleanText(value, 1000));
  if (!title || !summary) throw new Error('Cần nhập cả tiêu đề và tóm tắt.');
  const issue = await getIssue(Number(match[1]));
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) throw new Error('Chỉ có thể sửa bài đang chờ duyệt.');
  const record = parseIssueBody(issue.body || '');
  const lang = record.originalLang as Lang;
  record.title[lang] = title.slice(0, 160);
  record.summary[lang] = summary.slice(0, MAX_SUMMARY);
  await updateIssue(issue.number, { title: `[${record.id}] ${title.slice(0, 100)}`, body: makeIssueBody(record, record.telegramUserId) });
  await send(message.chat.id, `Đã cập nhật bài #${issue.number}.`);
}
async function tagIssue(message: AnyRecord, args: string): Promise<void> {
  const match = args.match(/^(\d+)\s+(.+)$/);
  if (!match) throw new Error('Cú pháp: /tag <issue_id> android,ios,windows,macos,linux,web,ai,khac');
  const tags = [...new Set(match[2].split(',').map((tag) => tag.trim().toLowerCase()).filter((tag) => ALLOWED_TAGS.has(tag)))];
  if (!tags.length) throw new Error('Không có tag hợp lệ.');
  const issue = await getIssue(Number(match[1]));
  if (issue.state !== 'open' || !issue.labels?.some((label: AnyRecord) => label.name === PENDING)) throw new Error('Chỉ có thể gắn tag cho bài đang chờ duyệt.');
  const record = parseIssueBody(issue.body || '');
  record.tags = tags;
  await updateIssue(issue.number, { body: makeIssueBody(record, record.telegramUserId) });
  await send(message.chat.id, `Đã gắn tag cho bài #${issue.number}: ${tags.join(', ')}`);
}

async function onMessage(message: AnyRecord): Promise<void> {
  if (!message?.chat?.id || !message.from?.id) return;
  const text = cleanText(message.text || message.caption || '', 5000);
  const userId = String(message.from.id);
  const chatId = message.chat.id;
  const commandMatch = text.match(/^\/(\w+)(?:@\w+)?(?:\s+([\s\S]*))?$/);
  const command = commandMatch?.[1]?.toLowerCase();
  const args = commandMatch?.[2] || '';
  const lang = ['start', 'trangthai', 'danhsach'].includes(command || '') || (command === 'gui' && !args)
    ? 'vi'
    : languageOf(command === 'gui' ? args : text);

  if (command === 'start') {
    await send(chatId, replyText(lang,
      `Chào bạn! Gửi /gui <link> <ghi chú ngắn> hoặc gửi link trực tiếp. Bạn cũng có thể forward bài từ kênh Telegram công khai. Chỉ gửi tiêu đề/tóm tắt do bạn viết; không gửi toàn văn. Telegram ID của bạn: ${userId}.`,
      `Hello! Send /gui <link> <short note>, a link, or forward a public Telegram channel post. Share only a title/summary in your own words, not the full text. Your Telegram ID: ${userId}.`));
    return;
  }
  if (command === 'trangthai') {
    const issues = await listIssues(`label:user-${userId}`);
    const status = issues.slice(0, 10).map((issue) => `${issue.labels?.some((label: AnyRecord) => label.name === PENDING) ? '⏳ Chờ duyệt' : issue.labels?.some((label: AnyRecord) => label.name === 'approved') ? '✅ Đã đăng' : '⛔ Từ chối'} — ${cleanText(issue.title, 120)} (#${issue.number})`);
    await send(chatId, status.length ? status.join('\n') : replyText(lang, 'Bạn chưa gửi bài nào.', 'You have not submitted any tips yet.'));
    return;
  }
  if (command === 'danhsach' || command === 'sua' || command === 'tag') {
    if (!isAdmin(userId)) { await send(chatId, 'Không có quyền.'); return; }
    if (command === 'danhsach') {
      const issues = await pendingIssues();
      await send(chatId, issues.length ? issues.slice(0, 10).map((issue) => `#${issue.number} ${cleanText(issue.title, 150)}`).join('\n') : 'Không có bài chờ duyệt.');
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
}

export default async function handler(req: any, res: any): Promise<void> {
  if (req.method !== 'POST') { res.status(200).send('ok'); return; }
  const secret = env('TELEGRAM_WEBHOOK_SECRET');
  if (!secret || req.headers?.['x-telegram-bot-api-secret-token'] !== secret) {
    res.status(401).send('unauthorized'); return;
  }
  // Acknowledge before doing network work so Telegram does not retry on a slow GitHub API call.
  res.status(200).send('ok');
  try {
    const update = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
    if (update?.callback_query) await onCallback(update.callback_query);
    else if (update?.message) await onMessage(update.message);
  } catch (error) {
    console.error('telegram handler error', error instanceof Error ? error.message : 'unknown error');
    for (const id of env('ADMIN_IDS').split(',').map((part) => part.trim()).filter(Boolean)) {
      try { await send(id, 'Có lỗi khi xử lý một cập nhật Telegram. Xem log function để kiểm tra.'); } catch { /* Best effort. */ }
    }
  }
}
