import assert from 'node:assert/strict';
import esbuild from '../node_modules/esbuild/lib/main.js';

const built = await esbuild.build({
  entryPoints: ['api/telegram.ts'],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
});

const modUrl = 'data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64');
const tg = await import(modUrl);

// 1. URL normalization, tracking stripping & SSRF / private / obfuscated host rejection
assert.equal(tg.normalizeUrl('https://Example.COM?utm_source=x&b=2&a=1#frag'), 'https://example.com/?a=1&b=2');
assert.equal(
  tg.normalizeUrl('https://example.com/tips/linux///?fbclid=123&gclid=456&igshid=abc&si=xyz&spm=a2o0o&id=7'),
  'https://example.com/tips/linux?id=7',
);
assert.equal(tg.normalizeUrl('https://100.63.0.1/ok'), 'https://100.63.0.1/ok');
assert.equal(tg.normalizeUrl('https://100.128.0.1/ok'), 'https://100.128.0.1/ok');

const blockedUrls = [
  'http://localhost:3000/test',
  'http://localhost./test',
  'http://app.localhost/test',
  'http://printer.local/test',
  'http://metadata.google.internal/computeMetadata/v1/',
  'http://127.0.0.1/admin',
  'http://10.0.0.1/internal',
  'http://172.16.0.1/internal',
  'http://192.168.1.10/router',
  'http://0.0.0.0/test',
  'http://169.254.169.254/latest/meta-data/',
  'http://100.64.0.1/cgnat',
  'http://100.100.100.200/cgnat',
  'http://100.127.255.254/cgnat',
  'http://2130706433/admin',
  'http://0x7f000001/admin',
  'http://0177.0.0.1/admin',
  'http://127.1/admin',
  'http://134744072/obfuscated-public',
  'http://0x08080808/obfuscated-hex',
  'http://[::1]/admin',
  'http://[::ffff:127.0.0.1]/admin',
  'ftp://example.com/file.zip',
  'javascript:alert(1)',
  'file:///etc/passwd',
  'https://user:pass@example.com/secret',
  'https://@example.com/secret',
];
for (const bad of blockedUrls) {
  assert.throws(() => tg.normalizeUrl(bad), /Only public HTTP/, `Expected rejection for ${bad}`);
}
assert.throws(
  () => tg.normalizeUrl(`https://example.com/${'a'.repeat(2050)}`),
  /Invalid URL/,
  'URLs exceeding 2048 characters must be rejected',
);

// 2. Language & source detection
assert.equal(tg.languageOf('Mẹo tăng tốc Windows 11 cực nhanh'), 'vi');
assert.equal(tg.languageOf('How to speed up Windows 11'), 'en');
assert.deepEqual(tg.sourceFor('https://m.facebook.com/groups/1/posts/2'), { type: 'community-facebook', name: 'Nhóm Facebook' });
assert.deepEqual(tg.sourceFor('https://t.me/techtips/42'), { type: 'community-telegram', name: 'Kênh Telegram' });

// 3. Handler end-to-end behavior with stateful mocked GitHub & Telegram APIs
process.env.TELEGRAM_WEBHOOK_SECRET = 'test-secret';
process.env.TELEGRAM_BOT_TOKEN = 'test-bot-token';
process.env.GITHUB_TOKEN = 'test-gh-token';
process.env.GITHUB_REPO = 'owner/repo';
process.env.ADMIN_IDS = '999,888';
process.env.SUBMIT_LIMIT_PER_DAY = '10';

let calls = [];
let mockIssues = [];
let nextIssueNumber = 10;
let communityEntries = [];
let injectGithubError = null;

function findIssue(num) {
  return mockIssues.find((issue) => issue.number === num) || null;
}

globalThis.fetch = async (url, init) => {
  const u = String(url);
  const method = (init?.method || 'GET').toUpperCase();
  const body = init?.body ? JSON.parse(init.body) : null;
  calls.push({ url: u, method, body });

  if (u.startsWith('https://api.github.com') && injectGithubError) {
    const status = injectGithubError;
    return new Response(JSON.stringify({ message: 'injected failure' }), { status });
  }

  if (u.includes('/contents/data/community.json') && method === 'GET') {
    return new Response(
      JSON.stringify({ content: Buffer.from(JSON.stringify(communityEntries)).toString('base64'), sha: 'sha1' }),
      { status: 200 },
    );
  }
  if (u.includes('/contents/data/community.json') && method === 'PUT') {
    communityEntries = JSON.parse(Buffer.from(body.content, 'base64').toString('utf8'));
    return new Response(JSON.stringify({ content: {} }), { status: 200 });
  }
  if (u.includes('/issues?')) {
    const parsedUrl = new URL(u);
    const reqLabels = (parsedUrl.searchParams.get('labels') || '').split(',').filter(Boolean);
    const reqState = parsedUrl.searchParams.get('state') || 'open';
    const filtered = mockIssues.filter((issue) => {
      if (reqState !== 'all' && issue.state !== reqState) return false;
      const issueLabelNames = (issue.labels || []).map((l) => l.name);
      return reqLabels.every((label) => issueLabelNames.includes(label));
    });
    return new Response(JSON.stringify(filtered), { status: 200 });
  }
  const issueMatch = u.match(/\/issues\/(\d+)$/);
  if (issueMatch && method === 'GET') {
    const issue = findIssue(Number(issueMatch[1]));
    if (!issue) return new Response(JSON.stringify({ message: 'Not Found' }), { status: 404 });
    return new Response(JSON.stringify(issue), { status: 200 });
  }
  if (issueMatch && method === 'PATCH') {
    const num = Number(issueMatch[1]);
    const idx = mockIssues.findIndex((issue) => issue.number === num);
    if (idx === -1) return new Response(JSON.stringify({ message: 'Not Found' }), { status: 404 });
    const patched = { ...mockIssues[idx], ...body };
    if (Array.isArray(body.labels)) {
      patched.labels = body.labels.map((name) => (typeof name === 'string' ? { name } : name));
    }
    mockIssues[idx] = patched;
    return new Response(JSON.stringify(patched), { status: 200 });
  }
  if (u.endsWith('/labels')) {
    return new Response(JSON.stringify({}), { status: 201 });
  }
  if (u.endsWith('/issues') && method === 'POST') {
    const created = {
      number: nextIssueNumber++,
      state: 'open',
      title: body.title,
      body: body.body,
      created_at: new Date().toISOString(),
      labels: body.labels.map((name) => ({ name })),
    };
    mockIssues.push(created);
    return new Response(JSON.stringify(created), { status: 201 });
  }
  if (u.includes('api.telegram.org')) {
    return new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 });
  }
  return new Response('{}', { status: 200 });
};

function makeRes() {
  return {
    statusCode: 0,
    payload: '',
    writableEnded: false,
    status(c) { this.statusCode = c; return this; },
    send(b) { this.payload = b; this.writableEnded = true; },
  };
}

function telegramCalls(methodName) {
  return calls.filter((c) => c.url.includes(`/bottest-bot-token/${methodName}`));
}

// 3.0 HTTP method, health check, secret authentication & malformed JSON checks
{
  const getRes = makeRes();
  await tg.default({ method: 'GET', headers: {} }, getRes);
  assert.equal(getRes.statusCode, 200);
  assert.equal(getRes.payload, 'ok');

  const headRes = makeRes();
  await tg.default({ method: 'HEAD', headers: {} }, headRes);
  assert.equal(headRes.statusCode, 200);

  const putRes = makeRes();
  await tg.default({ method: 'PUT', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: {} }, putRes);
  assert.equal(putRes.statusCode, 405);

  const noSecretRes = makeRes();
  await tg.default({ method: 'POST', headers: {}, body: {} }, noSecretRes);
  assert.equal(noSecretRes.statusCode, 401);

  const wrongSecretRes = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'wrong-secret' }, body: {} },
    wrongSecretRes,
  );
  assert.equal(wrongSecretRes.statusCode, 401);

  calls = [];
  const badJsonRes = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: '{invalid json' },
    badJsonRes,
  );
  assert.equal(badJsonRes.statusCode, 400);
  assert.equal(telegramCalls('sendMessage').length, 0, 'Malformed JSON must NOT spam admins');

  calls = [];
  const arrayJsonRes = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: '[]' },
    arrayJsonRes,
  );
  assert.equal(arrayJsonRes.statusCode, 400);
  assert.equal(telegramCalls('sendMessage').length, 0, 'Non-object JSON must NOT spam admins');
}

// 3.1 Empty ADMIN_IDS must never authorize empty or missing user IDs
{
  const savedAdmins = process.env.ADMIN_IDS;
  process.env.ADMIN_IDS = '';
  assert.equal(tg.isAdmin(''), false);
  assert.equal(tg.isAdmin(undefined), false);
  assert.equal(tg.isAdmin(null), false);
  assert.equal(tg.isAdmin(999), false);

  process.env.ADMIN_IDS = ' ,  , ';
  assert.equal(tg.isAdmin(''), false);
  assert.equal(tg.isAdmin(undefined), false);

  calls = [];
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: { callback_query: { id: 'cb-empty', from: { id: '' }, data: 'ap:10' } },
    },
    makeRes(),
  );
  const answers = telegramCalls('answerCallbackQuery');
  assert.equal(answers.length, 1);
  assert.equal(answers[0].body.text, 'Không có quyền');
  assert.equal(calls.some((c) => c.url.includes('api.github.com')), false);
  process.env.ADMIN_IDS = savedAdmins;
}

// 3a. Bare URL without note is politely rejected without creating an empty GitHub issue
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: { message: { chat: { id: 100 }, from: { id: 200 }, text: 'https://t.me/channel/55' } },
  },
  makeRes(),
);
assert.equal(calls.some((c) => c.url.endsWith('/issues') && c.method === 'POST'), false);

// 3b. Valid submission with backticks creates safe JSON issue, full ISO-8601 since, and NO user-* labels
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      message: {
        chat: { id: 100 },
        from: { id: 200 },
        text: '/gui https://example.com/docker-tip Cách dọn Docker rác bằng lệnh ```docker system prune -af``` nhanh gọn',
      },
    },
  },
  makeRes(),
);
const issue10 = findIssue(10);
assert.ok(issue10, 'Issue #10 should be created');
assert.equal(issue10.body.match(/```/g).length, 2, 'Inner backticks must be escaped inside JSON fence');

const rateLimitListCall = calls.find((c) => c.url.includes('/issues?') && c.url.includes('community-inbox'));
assert.ok(rateLimitListCall, 'Rate-limit query must use community-inbox label');
const rateLimitUrl = new URL(rateLimitListCall.url);
assert.equal(rateLimitUrl.searchParams.get('state'), 'all');
assert.match(
  rateLimitUrl.searchParams.get('since') || '',
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/,
  'since parameter must be full ISO-8601 UTC timestamp',
);
const labelCreations = calls.filter((c) => c.url.endsWith('/labels') && c.method === 'POST').map((c) => c.body.name);
assert.equal(labelCreations.some((name) => name.startsWith('user-')), false, 'Must NOT create user-* labels');
assert.ok(labelCreations.includes('community-inbox'), 'Must ensure community-inbox label');
const issue10Labels = issue10.labels.map((l) => l.name);
assert.equal(issue10Labels.some((name) => name.startsWith('user-')), false, 'Issue must NOT have user-* label');
assert.ok(issue10Labels.includes('community-inbox') && issue10Labels.includes('pending') && issue10Labels.includes('src-web'));

// 3c. Admin /sua preserves pipe | characters inside summary and /tag accepts dev,security,web
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      message: {
        chat: { id: 999 },
        from: { id: 999 },
        text: '/sua 10 Mẹo dọn Docker | Dùng lệnh docker ps -a | grep Exited để lọc container cũ',
      },
    },
  },
  makeRes(),
);
assert.ok(findIssue(10).body.includes('docker ps -a | grep Exited'), 'Pipe inside summary must not be truncated');

await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: { message: { chat: { id: 999 }, from: { id: 999 }, text: '/tag 10 dev,security,web' } },
  },
  makeRes(),
);
assert.ok(findIssue(10).body.includes('"dev"') && findIssue(10).body.includes('"browser"'));

// 3d. /sua and /tag syntax/validation errors reply directly to admin chat WITHOUT global admin alert spam
for (const badCmd of ['/sua', '/sua 10 khong co dau gach', '/tag', '/tag 10 invalidtag1,invalidtag2', '/sua 99999 T | S']) {
  calls = [];
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: { message: { chat: { id: 999 }, from: { id: 999 }, text: badCmd } },
    },
    makeRes(),
  );
  const msgs = telegramCalls('sendMessage');
  assert.equal(msgs.length, 1, `Expected 1 direct reply for "${badCmd}", got ${msgs.length}`);
  assert.equal(msgs[0].body.chat_id, 999);
  assert.equal(msgs[0].body.text.includes('Có lỗi khi xử lý'), false, `Must NOT send global admin error alert for "${badCmd}"`);
}

// 3e. Approve callback clears inline keyboard, and second click does NOT spam global admin alerts
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      callback_query: {
        id: 'cb-ap-1',
        from: { id: 999 },
        data: 'ap:10',
        message: { chat: { id: 999 }, message_id: 77 },
      },
    },
  },
  makeRes(),
);
assert.equal(findIssue(10).state, 'closed');
assert.equal(communityEntries.length, 1);
const markupEdits1 = telegramCalls('editMessageReplyMarkup');
assert.equal(markupEdits1.length, 1, 'Approve must clear inline keyboard');
assert.deepEqual(markupEdits1[0].body, {
  chat_id: 999,
  message_id: 77,
  reply_markup: { inline_keyboard: [] },
});
assert.equal(telegramCalls('answerCallbackQuery')[0].body.text, 'Đã đăng');

// Second click on already-approved issue #10
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      callback_query: {
        id: 'cb-ap-2',
        from: { id: 999 },
        data: 'ap:10',
        message: { chat: { id: 999 }, message_id: 77 },
      },
    },
  },
  makeRes(),
);
const secondAnswer = telegramCalls('answerCallbackQuery');
assert.equal(secondAnswer.length, 1);
assert.equal(secondAnswer[0].body.show_alert, true);
assert.equal(telegramCalls('editMessageReplyMarkup').length, 1, 'Stale inline keyboard should be cleared on double-click');
assert.equal(telegramCalls('sendMessage').length, 0, 'Double-clicking already-processed issue must NOT alert admins');

// Editing a closed issue also replies directly without admin alert spam
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: { message: { chat: { id: 999 }, from: { id: 999 }, text: '/sua 10 New | Summary' } },
  },
  makeRes(),
);
assert.equal(telegramCalls('sendMessage').length, 1);
assert.equal(telegramCalls('sendMessage')[0].body.chat_id, 999);
assert.equal(telegramCalls('sendMessage')[0].body.text.includes('Chỉ có thể sửa'), true);

// 3f. Reject callback clears inline keyboard and double-click does NOT alert admins
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      message: {
        chat: { id: 100 },
        from: { id: 200 },
        text: '/gui https://example.com/reject-me Cách kiểm tra ổ cứng SSD trên Linux nhanh',
      },
    },
  },
  makeRes(),
);
assert.ok(findIssue(11), 'Issue #11 should be created');

calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      callback_query: {
        id: 'cb-rj-1',
        from: { id: 999 },
        data: 'rj:11',
        message: { chat: { id: 999 }, message_id: 88 },
      },
    },
  },
  makeRes(),
);
assert.equal(findIssue(11).state, 'closed');
assert.ok(findIssue(11).labels.some((l) => l.name === 'rejected'));
assert.ok(findIssue(11).labels.some((l) => l.name === 'community-inbox'));
assert.equal(telegramCalls('editMessageReplyMarkup').length, 1);

calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      callback_query: {
        id: 'cb-rj-2',
        from: { id: 999 },
        data: 'rj:11',
        message: { chat: { id: 999 }, message_id: 88 },
      },
    },
  },
  makeRes(),
);
assert.equal(telegramCalls('answerCallbackQuery')[0].body.show_alert, true);
assert.equal(telegramCalls('editMessageReplyMarkup').length, 1);
assert.equal(telegramCalls('sendMessage').length, 0, 'Double-clicking reject must NOT alert admins');

// 3g. Daily rate-limit blocks submission when user hits SUBMIT_LIMIT_PER_DAY (and ignores other users / expired issues)
process.env.SUBMIT_LIMIT_PER_DAY = '2';
// Add an expired issue (> 24h ago) for user 200 and a recent issue for user 300
mockIssues.push({
  number: 90,
  state: 'closed',
  title: '[old0000000000000] Old tip',
  created_at: new Date(Date.now() - 30 * 3600 * 1000).toISOString(),
  body: '```json\n{"id":"old0000000000000","telegramUserId":"200"}\n```',
  labels: [{ name: 'community-inbox' }, { name: 'approved' }],
});
mockIssues.push({
  number: 91,
  state: 'open',
  title: '[other00000000000] Other user tip',
  created_at: new Date().toISOString(),
  body: '```json\n{"id":"other00000000000","telegramUserId":"300"}\n```',
  labels: [{ name: 'community-inbox' }, { name: 'pending' }],
});

// User 200 already has 2 recent issues (#10 and #11) -> 3rd submission must be blocked
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      message: {
        chat: { id: 100 },
        from: { id: 200 },
        text: '/gui https://example.com/third-tip Mẹo dùng phím tắt VS Code siêu nhanh cho lập trình viên',
      },
    },
  },
  makeRes(),
);
assert.equal(calls.some((c) => c.url.endsWith('/issues') && c.method === 'POST'), false, 'Rate-limited user must not create issue');
assert.ok(
  telegramCalls('sendMessage').some((c) => c.body.chat_id === 100 && c.body.text.includes('giới hạn gửi bài')),
  'Rate-limited user must receive polite limit reply',
);

// User 300 only has 1 recent issue (#91) -> submission must succeed
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      message: {
        chat: { id: 300 },
        from: { id: 300 },
        text: '/gui https://example.com/user-300-tip How to configure SSH config aliases cleanly',
      },
    },
  },
  makeRes(),
);
assert.equal(calls.some((c) => c.url.endsWith('/issues') && c.method === 'POST'), true, 'Another user under limit should succeed');

// 3h. /trangthai shows ONLY that user's issues (including legacy user-<id> label) and excludes other users
mockIssues.push({
  number: 92,
  state: 'open',
  title: '[legacy0000000000] Legacy user 200 tip',
  created_at: new Date().toISOString(),
  body: 'Custom body without JSON',
  labels: [{ name: 'community-inbox' }, { name: 'pending' }, { name: 'user-200' }],
});

calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: { message: { chat: { id: 100 }, from: { id: 200 }, text: '/trangthai' } },
  },
  makeRes(),
);
const statusListCall = calls.find((c) => c.url.includes('/issues?'));
assert.ok(statusListCall && new URL(statusListCall.url).searchParams.get('labels') === 'community-inbox');
const statusReply = telegramCalls('sendMessage').find((c) => c.body.chat_id === 100)?.body.text || '';
assert.ok(statusReply.includes('(#10)'), 'Status must include user 200 approved issue #10');
assert.ok(statusReply.includes('(#11)'), 'Status must include user 200 rejected issue #11');
assert.ok(statusReply.includes('(#92)'), 'Status must include user 200 legacy-labeled issue #92');
assert.equal(statusReply.includes('(#91)'), false, 'Status must NOT leak user 300 issue #91');
assert.equal(statusReply.includes('user-300-tip'), false, 'Status must NOT leak user 300 submissions');

// 3i. Unexpected server error (e.g. GitHub 500) DOES still notify all admins
calls = [];
injectGithubError = 500;
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: {
      callback_query: {
        id: 'cb-err',
        from: { id: 999 },
        data: 'ap:10',
        message: { chat: { id: 999 }, message_id: 77 },
      },
    },
  },
  makeRes(),
);
injectGithubError = null;
const alertTargets = telegramCalls('sendMessage')
  .filter((c) => c.body.text.includes('Có lỗi khi xử lý'))
  .map((c) => String(c.body.chat_id))
  .sort();
assert.deepEqual(alertTargets, ['888', '999'], 'Unexpected 500 errors must still alert all configured admins');

console.log('✅ All Telegram webhook unit & integration tests passed!');
