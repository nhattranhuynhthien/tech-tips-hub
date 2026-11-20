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

// 1. URL normalization & private/local host rejection
assert.equal(tg.normalizeUrl('https://Example.COM?utm_source=x&b=2&a=1#frag'), 'https://example.com/?a=1&b=2');
assert.equal(tg.normalizeUrl('https://example.com/tips/linux///?fbclid=123&gclid=456'), 'https://example.com/tips/linux');
assert.throws(() => tg.normalizeUrl('http://localhost:3000/test'), /Only public HTTP/);
assert.throws(() => tg.normalizeUrl('http://127.0.0.1/admin'), /Only public HTTP/);
assert.throws(() => tg.normalizeUrl('http://192.168.1.10/router'), /Only public HTTP/);

// 2. Language & source detection
assert.equal(tg.languageOf('Mẹo tăng tốc Windows 11 cực nhanh'), 'vi');
assert.equal(tg.languageOf('How to speed up Windows 11'), 'en');
assert.deepEqual(tg.sourceFor('https://m.facebook.com/groups/1/posts/2'), { type: 'community-facebook', name: 'Nhóm Facebook' });
assert.deepEqual(tg.sourceFor('https://t.me/techtips/42'), { type: 'community-telegram', name: 'Kênh Telegram' });

// 3. Handler end-to-end behavior with mocked GitHub & Telegram APIs
process.env.TELEGRAM_WEBHOOK_SECRET = 'test-secret';
process.env.TELEGRAM_BOT_TOKEN = 'test-bot-token';
process.env.GITHUB_TOKEN = 'test-gh-token';
process.env.GITHUB_REPO = 'owner/repo';
process.env.ADMIN_IDS = '999';

let calls = [];
let mockIssue = null;

globalThis.fetch = async (url, init) => {
  const u = String(url);
  const method = init?.method || 'GET';
  const body = init?.body ? JSON.parse(init.body) : null;
  calls.push({ url: u, method, body });

  if (u.includes('/contents/data/community.json') && method === 'GET') {
    return new Response(JSON.stringify({ content: Buffer.from('[]').toString('base64'), sha: 'sha1' }), { status: 200 });
  }
  if (u.includes('/contents/data/community.json') && method === 'PUT') {
    return new Response(JSON.stringify({ content: {} }), { status: 200 });
  }
  if (u.includes('/issues?')) {
    return new Response(JSON.stringify(mockIssue ? [mockIssue] : []), { status: 200 });
  }
  if (u.match(/\/issues\/\d+$/) && method === 'GET') {
    return new Response(JSON.stringify(mockIssue), { status: 200 });
  }
  if (u.match(/\/issues\/\d+$/) && method === 'PATCH') {
    mockIssue = { ...mockIssue, ...body };
    return new Response(JSON.stringify(mockIssue), { status: 200 });
  }
  if (u.endsWith('/labels')) {
    return new Response(JSON.stringify({}), { status: 201 });
  }
  if (u.endsWith('/issues') && method === 'POST') {
    mockIssue = { number: 10, state: 'open', title: body.title, body: body.body, labels: body.labels.map((name) => ({ name })) };
    return new Response(JSON.stringify(mockIssue), { status: 201 });
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

// 3a. Bare URL without note is politely rejected without creating an empty GitHub issue
calls = [];
await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: { message: { chat: { id: 100 }, from: { id: 200 }, text: 'https://t.me/channel/55' } },
  },
  makeRes()
);
assert.equal(calls.some((c) => c.url.endsWith('/issues') && c.method === 'POST'), false);

// 3b. Valid submission with backticks in note creates safe JSON issue & 16-char ID
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
  makeRes()
);
assert.ok(mockIssue, 'Issue should be created');
assert.equal(mockIssue.body.match(/```/g).length, 2, 'Inner backticks must be escaped inside JSON fence');

// 3c. Admin /sua preserves pipe | characters inside summary and /tag accepts dev,security
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
  makeRes()
);
assert.ok(mockIssue.body.includes('docker ps -a | grep Exited'), 'Pipe inside summary must not be truncated');

await tg.default(
  {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
    body: { message: { chat: { id: 999 }, from: { id: 999 }, text: '/tag 10 dev,security,web' } },
  },
  makeRes()
);
assert.ok(mockIssue.body.includes('"dev"') && mockIssue.body.includes('"browser"'));

console.log('✅ All Telegram webhook unit & integration tests passed!');
