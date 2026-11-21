import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import esbuild from '../node_modules/esbuild/lib/main.js';

const ROOT = process.cwd();

const built = await esbuild.build({
  entryPoints: ['api/telegram.ts'],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
});

const modUrl = 'data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64');
const tg = await import(modUrl);

// ---------------------------------------------------------------------------
// Stateful mock infrastructure for GitHub & Telegram APIs
// ---------------------------------------------------------------------------
const BASE_ENV = {
  TELEGRAM_WEBHOOK_SECRET: 'test-secret',
  TELEGRAM_BOT_TOKEN: 'test-bot-token',
  GITHUB_TOKEN: 'test-gh-token',
  GITHUB_REPO: 'owner/repo',
  ADMIN_IDS: '999,888',
  SUBMIT_LIMIT_PER_DAY: '10',
};

let calls = [];
let mockIssues = [];
let nextIssueNumber = 100;
let communityEntries = [];
let communitySha = 'sha-1';
let communityVersion = 1;
let injectGithubDelayMs = 0;
let strictTelegramValidation = true;

function resetState(envOverrides = {}) {
  for (const [k, v] of Object.entries(BASE_ENV)) {
    process.env[k] = v;
  }
  for (const [k, v] of Object.entries(envOverrides)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  calls = [];
  mockIssues = [];
  nextIssueNumber = 100;
  communityEntries = [];
  communitySha = 'sha-1';
  communityVersion = 1;
  injectGithubDelayMs = 0;
  strictTelegramValidation = true;
}

function findIssue(num) {
  return mockIssues.find((issue) => issue.number === num) || null;
}

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
  return calls.filter((c) => c.url.includes(`/bot${process.env.TELEGRAM_BOT_TOKEN}/${methodName}`));
}

function githubCalls() {
  return calls.filter((c) => c.url.startsWith('https://api.github.com'));
}

function hasMalformedHtmlEntity(html) {
  // Any '&' not starting a valid XML/HTML entity (&amp; &lt; &gt; &quot; &#123; &#x1f;)
  return /&(?!(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)/.test(html);
}

globalThis.fetch = async (url, init) => {
  const u = String(url);
  const method = (init?.method || 'GET').toUpperCase();
  const body = init?.body ? JSON.parse(init.body) : null;
  calls.push({ url: u, method, body });

  if (u.startsWith('https://api.github.com') && injectGithubDelayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, injectGithubDelayMs));
  }

  if (u.includes('/contents/data/community.json') && method === 'GET') {
    return new Response(
      JSON.stringify({
        content: Buffer.from(JSON.stringify(communityEntries)).toString('base64'),
        sha: communitySha,
      }),
      { status: 200 },
    );
  }
  if (u.includes('/contents/data/community.json') && method === 'PUT') {
    if (body.sha && body.sha !== communitySha) {
      return new Response(JSON.stringify({ message: 'SHA conflict' }), { status: 409 });
    }
    communityEntries = JSON.parse(Buffer.from(body.content, 'base64').toString('utf8'));
    communityVersion += 1;
    communitySha = `sha-${communityVersion}`;
    return new Response(JSON.stringify({ content: { sha: communitySha } }), { status: 200 });
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
    return new Response(JSON.stringify(structuredClone(issue)), { status: 200 });
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
    return new Response(JSON.stringify(structuredClone(patched)), { status: 200 });
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
    return new Response(JSON.stringify(structuredClone(created)), { status: 201 });
  }
  if (u.includes('api.telegram.org')) {
    if (strictTelegramValidation) {
      if (u.endsWith('/answerCallbackQuery') && (!body?.callback_query_id || typeof body.callback_query_id !== 'string')) {
        return new Response(
          JSON.stringify({ ok: false, description: 'Bad Request: callback_query_id is required' }),
          { status: 400 },
        );
      }
      if (u.endsWith('/sendMessage') && body?.parse_mode === 'HTML') {
        if (hasMalformedHtmlEntity(String(body.text || ''))) {
          return new Response(
            JSON.stringify({ ok: false, description: "Bad Request: can't parse entities: Unsupported HTML entity" }),
            { status: 400 },
          );
        }
      }
    }
    return new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 });
  }
  return new Response('{}', { status: 200 });
};

// ---------------------------------------------------------------------------
// Minimal non-short-circuiting Red-Team harness
// ---------------------------------------------------------------------------
const results = [];

async function test(id, title, fn) {
  resetState();
  try {
    await fn();
    results.push({ id, title, status: 'PASS' });
  } catch (err) {
    results.push({ id, title, status: 'FAIL', error: err instanceof Error ? err.message : String(err) });
  }
}

// ===========================================================================
// VECTOR 1: safeEqual & Secret Authentication Attacks
// ===========================================================================

await test('RT-01', 'Secret auth rejects header array ["wrong", "test-secret"]', async () => {
  const res = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': ['wrong', 'test-secret'] }, body: {} },
    res,
  );
  assert.equal(res.statusCode, 401);
});

await test('RT-02', 'Secret auth MUST reject ambiguous duplicate header array ["test-secret", "wrong"]', async () => {
  const res = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': ['test-secret', 'wrong'] }, body: {} },
    res,
  );
  assert.equal(
    res.statusCode,
    401,
    'Duplicate secret header array ["test-secret", "wrong"] must be rejected instead of trusting index 0',
  );
});

await test('RT-03', 'Secret auth MUST reject conflicting mixed-case duplicate secret headers', async () => {
  const res = makeRes();
  await tg.default(
    {
      method: 'POST',
      headers: {
        'x-telegram-bot-api-secret-token': 'test-secret',
        'X-Telegram-Bot-Api-Secret-Token': 'wrong-secret',
      },
      body: {},
    },
    res,
  );
  assert.equal(
    res.statusCode,
    401,
    'Conflicting mixed-case duplicate secret headers must be rejected',
  );
});

await test('RT-04', 'Secret auth accepts valid uppercase header key X-Telegram-Bot-Api-Secret-Token', async () => {
  const res = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'X-Telegram-Bot-Api-Secret-Token': 'test-secret' }, body: {} },
    res,
  );
  assert.equal(res.statusCode, 200);
});

await test('RT-05', 'Secret auth handles multi-byte UTF-8 secrets accurately (byte-length vs UTF-16 length)', async () => {
  resetState({ TELEGRAM_WEBHOOK_SECRET: 'bí-mật-🔐' });

  // Exact match succeeds
  const okRes = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'bí-mật-🔐' }, body: {} },
    okRes,
  );
  assert.equal(okRes.statusCode, 200);

  // Same UTF-16 length (9 code units) but different UTF-8 byte length must fail
  const sameUtf16Res = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'bi-mat-xx' }, body: {} },
    sameUtf16Res,
  );
  assert.equal(sameUtf16Res.statusCode, 401);

  // Same UTF-8 byte length (14 bytes) but different content must fail
  const sameBytesRes = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': '12345678901234' }, body: {} },
    sameBytesRes,
  );
  assert.equal(sameBytesRes.statusCode, 401);

  // Truncated prefix must fail
  const prefixRes = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'bí-mật-' }, body: {} },
    prefixRes,
  );
  assert.equal(prefixRes.statusCode, 401);
});

await test('RT-06', 'Secret auth rejects empty/whitespace TELEGRAM_WEBHOOK_SECRET even with empty header', async () => {
  for (const emptySecret of ['', '   ', undefined]) {
    resetState({ TELEGRAM_WEBHOOK_SECRET: emptySecret });
    const res1 = makeRes();
    await tg.default({ method: 'POST', headers: { 'x-telegram-bot-api-secret-token': '' }, body: {} }, res1);
    assert.equal(res1.statusCode, 401, `Empty secret (${JSON.stringify(emptySecret)}) must reject empty header`);

    const res2 = makeRes();
    await tg.default({ method: 'POST', headers: {}, body: {} }, res2);
    assert.equal(res2.statusCode, 401);
  }
});

await test('RT-07', 'Secret auth handles null, undefined, and non-object req.headers safely (401, no crash)', async () => {
  for (const badHeaders of [null, undefined, 'invalid', 123, []]) {
    const res = makeRes();
    await tg.default({ method: 'POST', headers: badHeaders, body: {} }, res);
    assert.equal(res.statusCode, 401, `Expected 401 for headers=${JSON.stringify(badHeaders)}`);
  }
});

await test('RT-07b', 'Secret auth MUST reject non-string header value object coercing via toString()', async () => {
  const objRes = makeRes();
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': { toString: () => 'test-secret' } },
      body: {},
    },
    objRes,
  );
  assert.equal(objRes.statusCode, 401, 'Non-string header object with toString() must not authenticate');
});

// ===========================================================================
// VECTOR 2: normalizeUrl SSRF & Parser Evasion
// ===========================================================================

await test('RT-08', 'normalizeUrl blocks IPv4-mapped IPv6 and all IPv6 loopback/link-local/ULA literals', async () => {
  const ipv6Payloads = [
    'http://[::ffff:7f00:1]/admin',
    'http://[::ffff:127.0.0.1]/admin',
    'http://[0:0:0:0:0:ffff:7f00:1]/admin',
    'http://[::ffff:169.254.169.254]/latest/meta-data/',
    'http://[::1]/admin',
    'http://[::]/admin',
    'http://[fe80::1]/admin',
    'http://[fc00::1]/admin',
    'http://[fd12:3456::1]/admin',
  ];
  for (const url of ipv6Payloads) {
    assert.throws(() => tg.normalizeUrl(url), /Only public HTTP/, `Must block IPv6 SSRF: ${url}`);
  }
});

await test('RT-09', 'normalizeUrl blocks obfuscated IPv4 (trailing dot, short, octal, hex, decimal)', async () => {
  const obfuscatedIps = [
    'http://127.0.0.1./admin',
    'http://8.8.8.8./dns',
    'http://example.com./tip',
    'http://127.1/admin',
    'http://10.1/internal',
    'http://127.0.1/admin',
    'http://0177.0.0.1/admin',
    'http://0177.0000.0000.0001/admin',
    'http://0x7f000001/admin',
    'http://0x7f.0x00.0x00.0x01/admin',
    'http://2130706433/admin',
    'http://010.0.0.1/octal-public',
    'http://0/zero',
  ];
  for (const url of obfuscatedIps) {
    assert.throws(() => tg.normalizeUrl(url), /Only public HTTP/, `Must block obfuscated IP/FQDN: ${url}`);
  }
});

await test('RT-10', 'normalizeUrl blocks CGNAT, AWS/GCP metadata.google.internal, 0.0.0.0, and local/internal TLDs', async () => {
  const internalUrls = [
    'http://100.64.0.1/cgnat',
    'http://100.127.255.254/cgnat',
    'http://169.254.169.254/latest/meta-data/iam/security-credentials/',
    'http://metadata.google.internal/computeMetadata/v1/',
    'http://0.0.0.0:8080/',
    'http://localhost/admin',
    'http://sub.localhost/admin',
    'http://nas.local/files',
    'http://service.internal/api',
    'http://router.home.arpa/',
    'http://gateway.lan/',
  ];
  for (const url of internalUrls) {
    assert.throws(() => tg.normalizeUrl(url), /Only public HTTP/, `Must block internal/metadata host: ${url}`);
  }
});

await test('RT-10b', 'normalizeUrl MUST also block GCP metadata alias metadata.goog', async () => {
  assert.throws(
    () => tg.normalizeUrl('http://metadata.goog/computeMetadata/v1/'),
    /Only public HTTP/,
    'Must block GCP metadata alias metadata.goog',
  );
});

await test('RT-11', 'normalizeUrl blocks non-HTTP(S) schemes and standard embedded credentials', async () => {
  const badSchemeOrCreds = [
    'javascript:alert(1)',
    'JAVASCRIPT:alert(1)',
    'file:///etc/passwd',
    'data:text/html,<script>alert(1)</script>',
    'ftp://example.com/file',
    'https://user:pass@example.com/secret',
    'https://user@example.com/secret',
    'https://@example.com/secret',
  ];
  for (const url of badSchemeOrCreds) {
    assert.throws(() => tg.normalizeUrl(url), /Only public HTTP|Invalid URL/, `Must reject: ${url}`);
  }
});

await test('RT-11b', 'normalizeUrl MUST block backslash-evaded empty credentials (https:\\\\@example.com, https://\\@example.com)', async () => {
  const backslashCreds = [
    'https:\\\\@example.com/secret',
    'https://\\@example.com/secret',
    'https:/\\@example.com/secret',
  ];
  for (const url of backslashCreds) {
    assert.throws(() => tg.normalizeUrl(url), /Only public HTTP|Invalid URL/, `Must reject backslash credential evasion: ${url}`);
  }
});

await test('RT-12', 'normalizeUrl blocks overlong URLs (>2048 raw OR >2048 after percent-encoding) and control chars', async () => {
  // Raw length > 2048
  assert.throws(
    () => tg.normalizeUrl(`https://example.com/${'a'.repeat(2040)}`),
    /Invalid URL/,
    'Raw >2048 must be rejected',
  );

  // Raw length < 2048 (~720 chars), but UTF-8 percent-encoded length > 2048 (~8420 chars)
  assert.throws(
    () => tg.normalizeUrl(`https://example.com/${'🔥'.repeat(350)}`),
    /Invalid URL/,
    'Encoded URL >2048 must be rejected',
  );

  // Control chars, CRLF, null bytes, tabs, DEL
  const ctrlPayloads = [
    'https://example.com/path\r\nX-Injected: true',
    'https://example.com/path\ninjected',
    'https://example.com/path\0null',
    'https://ex\tample.com/tab',
    'https://example.com/del\x7fchar',
  ];
  for (const url of ctrlPayloads) {
    assert.throws(() => tg.normalizeUrl(url), /Invalid URL/, `Must block control char URL: ${JSON.stringify(url)}`);
  }
});

await test('RT-13', 'normalizeUrl handles Unicode homograph/punycode and blocks fullwidth IP/localhost SSRF', async () => {
  // Fullwidth dot / fullwidth digit SSRF evasions
  const unicodeSsrf = [
    'http://127。0。0。1/admin',
    'http://127．0．0．1/admin',
    'http://１２７.０.０.１/admin',
    'http://localhost。/admin',
    'http://app。localhost/admin',
    'http://169。254。169。254/latest/meta-data/',
  ];
  for (const url of unicodeSsrf) {
    assert.throws(() => tg.normalizeUrl(url), /Only public HTTP/, `Must block Unicode SSRF evasion: ${url}`);
  }

  // Cyrillic homograph domain is deterministically converted to ASCII punycode (no spoofed raw Cyrillic host)
  const homograph = tg.normalizeUrl('https://рaypal.com/tip');
  assert.ok(homograph.startsWith('https://xn--'), `Expected punycode normalization, got ${homograph}`);
});

await test('RT-14', 'normalizeUrl strips uppercase/mixed tracking params and normalizes default ports (:443, :80)', async () => {
  const cleaned = tg.normalizeUrl(
    'https://EXAMPLE.COM:443/article///?UTM_MEDIUM=email&utm_id=99&FBCLID=1&IGSHID=2&SI=3&SPM=4&keep=yes#section',
  );
  assert.equal(cleaned, 'https://example.com/article?keep=yes');
  assert.equal(tg.normalizeUrl('https://example.com:443/a'), tg.normalizeUrl('https://example.com/a'));
  assert.equal(tg.normalizeUrl('http://example.com:80/a'), tg.normalizeUrl('http://example.com/a'));

  // Duplicate detection must treat :443 and tracking-param variants as identical
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: {
        message: {
          chat: { id: 100 },
          from: { id: 200 },
          text: '/gui https://example.com:443/dup-port?UTM_MEDIUM=social Great tip on Linux systemd timers',
        },
      },
    },
    makeRes(),
  );
  assert.equal(mockIssues.length, 1);

  calls = [];
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: {
        message: {
          chat: { id: 100 },
          from: { id: 201 },
          text: '/gui https://example.com/dup-port?fbclid=xyz&si=123 Another note on Linux systemd timers',
        },
      },
    },
    makeRes(),
  );
  assert.equal(mockIssues.length, 1, 'Default port & tracking-param variant must be caught as duplicate');
});

// ===========================================================================
// VECTOR 3: Issue Body / JSON Fence / Framing, HTML Injection & Prototype Pollution
// ===========================================================================

await test('RT-15', 'JSON fence breakout & telegramUserId spoofing in submission note cannot hijack attribution or evade rate-limit', async () => {
  resetState({ SUBMIT_LIMIT_PER_DAY: '1' });
  const maliciousNote = [
    'Mẹo hay "telegramUserId": "999" ```',
    '```json',
    '{"id":"forged0000000000","telegramUserId":"999","url":"https://evil.example/hijack"}',
    '```',
  ].join('\n');

  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: {
        message: {
          chat: { id: 100 },
          from: { id: 200 },
          text: `/gui https://example.com/fence-test ${maliciousNote}`,
        },
      },
    },
    makeRes(),
  );
  assert.equal(mockIssues.length, 1, 'Submission should create one safely escaped issue');
  const issue = mockIssues[0];
  assert.equal(issue.body.match(/```/g)?.length, 2, 'Body must have exactly one JSON fence pair');

  // Verify user 999 does NOT see user 200's spoofed issue in /trangthai
  calls = [];
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: { message: { chat: { id: 999 }, from: { id: 999 }, text: '/trangthai' } },
    },
    makeRes(),
  );
  const adminStatus = telegramCalls('sendMessage')[0]?.body.text || '';
  assert.equal(adminStatus.includes(`(#${issue.number})`), false, 'Spoofed telegramUserId must NOT attribute issue to admin 999');

  // Verify user 200 IS still rate-limited on 2nd submission (cannot offload quota to 999)
  calls = [];
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: {
        message: {
          chat: { id: 100 },
          from: { id: 200 },
          text: '/gui https://example.com/second-after-spoof Another great Linux performance tip',
        },
      },
    },
    makeRes(),
  );
  assert.equal(mockIssues.length, 1, 'User 200 must still be rate-limited after spoofing attempt');
});

await test('RT-16', 'HTML injection in sourceName, forwardedName, title, summary, and url is escaped in sendAdminCard', async () => {
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: {
        message: {
          chat: { id: 100 },
          from: { id: 200 },
          text: '/gui https://facebook.com/groups/1/posts/2?q=%3Cb%3E&x=1&y=2 [<b>EvilGroup</b><script>alert(1)</script>] <b>FakeTitle</b> <a href="https://phish.test">Click</a> & "quotes"',
        },
      },
    },
    makeRes(),
  );

  const adminCards = telegramCalls('sendMessage').filter((c) => c.body.parse_mode === 'HTML');
  assert.ok(adminCards.length >= 1, 'Admin review card must be sent');
  const cardText = adminCards[0].body.text;
  assert.equal(cardText.includes('<script>'), false, 'Raw <script> tag must be escaped');
  assert.equal(cardText.includes('<a href='), false, 'Raw <a> tag must be escaped');
  assert.equal(cardText.includes('<b>EvilGroup</b>'), false, 'Injected <b> in forwardedName must be escaped');
  assert.equal(cardText.includes('<b>FakeTitle</b>'), false, 'Injected <b> in title must be escaped');
  assert.ok(cardText.includes('&lt;b&gt;EvilGroup&lt;/b&gt;'), 'Escaped forwardedName must appear');
  assert.ok(cardText.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'Escaped script must appear');
});

await test('RT-17', 'HTML injection via Telegram forwarded channel title is escaped AND long HTML-escaped card MUST NOT corrupt entities at 3900-char truncation', async () => {
  // Craft a valid forwarded channel post with heavy HTML-escapable chars in channel title (800 quotes -> 4800 chars after escapeHtml)
  const evilChannelTitle = '"'.repeat(800);
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: {
        message: {
          chat: { id: 100 },
          from: { id: 200 },
          text: 'Useful tip about configuring nftables firewall rules safely on Linux servers',
          forward_origin: {
            type: 'channel',
            chat: { username: 'public_tips_chan', title: evilChannelTitle },
            message_id: 42,
          },
        },
      },
    },
    makeRes(),
  );

  const adminCards = telegramCalls('sendMessage').filter((c) => c.body.parse_mode === 'HTML');
  assert.ok(adminCards.length >= 1, 'Admin card should be attempted');
  const cardText = adminCards[0].body.text;
  assert.equal(
    hasMalformedHtmlEntity(cardText),
    false,
    `Admin HTML card was sliced mid-entity at 3900 chars! Tail: ${JSON.stringify(cardText.slice(-30))}`,
  );
  assert.ok(
    cardText.includes('https://t.me/public_tips_chan/42'),
    'Admin HTML card must not truncate away the link being reviewed',
  );
  // Must NOT trigger global admin error alert from Telegram 400 parse_entities failure
  const errorAlerts = telegramCalls('sendMessage').filter((c) => c.body.text.includes('Có lỗi khi xử lý'));
  assert.equal(errorAlerts.length, 0, 'Valid submission must not fail Telegram HTML parsing and alert admins');
});

await test('RT-18', 'Prototype pollution payloads in webhook JSON string & object do not pollute Object.prototype or escalate privileges', async () => {
  const pollutedJson = JSON.stringify({
    message: { chat: { id: 100 }, from: { id: 200 }, text: '/danhsach' },
  }).replace('{', '{"__proto__":{"isAdmin":true,"polluted":"yes"},"constructor":{"prototype":{"polluted":"yes"}},');

  const res = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: pollutedJson },
    res,
  );
  assert.equal(res.statusCode, 200);
  assert.equal(({}).isAdmin, undefined, 'Object.prototype.isAdmin must remain undefined');
  assert.equal(({}).polluted, undefined, 'Object.prototype.polluted must remain undefined');
  assert.equal(githubCalls().length, 0, 'Non-admin must NOT access /danhsach via __proto__ payload');
  assert.ok(telegramCalls('sendMessage').some((c) => c.body.chat_id === 100 && c.body.text.includes('Không có quyền')));
});

// ===========================================================================
// VECTOR 4: Auth, Callback, Command & Concurrency Bypasses
// ===========================================================================

await test('RT-19', 'Non-admin is blocked from /danhsach, /sua, /tag (including uppercase & @bot suffix) and callbacks ap/rj', async () => {
  const adminCommands = [
    '/danhsach',
    '/DANHSACH',
    '/danhsach@TechTipsBot',
    '/sua 100 Hacked | Hacked',
    '/SUA@TechTipsBot 100 Hacked | Hacked',
    '/tag 100 security,dev',
    '/TAG@TechTipsBot 100 security',
  ];
  for (const cmd of adminCommands) {
    calls = [];
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { message: { chat: { id: 200 }, from: { id: 200 }, text: cmd } },
      },
      makeRes(),
    );
    assert.equal(githubCalls().length, 0, `Non-admin command "${cmd}" must make zero GitHub calls`);
    assert.ok(
      telegramCalls('sendMessage').some((c) => c.body.text.includes('Không có quyền')),
      `Non-admin command "${cmd}" must receive denial`,
    );
  }

  for (const cbData of ['ap:1', 'rj:1']) {
    calls = [];
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { callback_query: { id: `cb-${cbData}`, from: { id: 200 }, data: cbData } },
      },
      makeRes(),
    );
    assert.equal(githubCalls().length, 0, `Non-admin callback "${cbData}" must make zero GitHub calls`);
    assert.equal(telegramCalls('answerCallbackQuery')[0]?.body.text, 'Không có quyền');
  }
});

await test('RT-20', 'isAdmin MUST reject non-primitive type-confusion values like ["999"] or { toString: () => "999" }', async () => {
  assert.equal(tg.isAdmin(['999']), false, 'Array ["999"] must NOT pass isAdmin via String() coercion');
  assert.equal(tg.isAdmin({ toString: () => '999' }), false, 'Object with toString() must NOT pass isAdmin');
  assert.equal(tg.isAdmin(' 999 '), false, 'Whitespace-padded admin ID must not match');
  assert.equal(tg.isAdmin(999), true, 'Numeric admin ID should match');
  assert.equal(tg.isAdmin('999'), true, 'Exact string admin ID should match');
});

await test('RT-21', 'Empty or whitespace ADMIN_IDS denies missing, empty, null, undefined, and numeric user IDs', async () => {
  for (const rawAdmins of ['', ' , ', '   ', undefined]) {
    resetState({ ADMIN_IDS: rawAdmins });
    for (const candidate of ['', null, undefined, 0, 999, '999', ' ']) {
      assert.equal(tg.isAdmin(candidate), false, `ADMIN_IDS=${JSON.stringify(rawAdmins)} must deny ${JSON.stringify(candidate)}`);
    }
    calls = [];
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { callback_query: { id: 'cb-no-from', data: 'ap:1' } },
      },
      makeRes(),
    );
    assert.equal(githubCalls().length, 0);
    assert.equal(telegramCalls('answerCallbackQuery')[0]?.body.text, 'Không có quyền');
  }
});

await test('RT-22', 'Malformed callback_data values are all rejected with zero GitHub calls and zero admin alerts', async () => {
  const malformedCallbacks = [
    'ap:0',
    'ap:-1',
    'ap:1.5',
    'ap:1e2',
    'ap:1:2',
    'ap:9007199254740993',
    'rj:9007199254740993',
    'del:1',
    'ap:NaN',
    'ap:Infinity',
    'ap:01',
    'ap: 1',
    'ap:1\n',
    '',
    'AP:1',
  ];
  for (const bad of malformedCallbacks) {
    calls = [];
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { callback_query: { id: 'cb-bad', from: { id: 999 }, data: bad } },
      },
      makeRes(),
    );
    assert.equal(githubCalls().length, 0, `Malformed callback "${bad}" must not call GitHub`);
    assert.equal(telegramCalls('answerCallbackQuery')[0]?.body.text, 'Yêu cầu không hợp lệ', `Bad rejection text for "${bad}"`);
    assert.equal(telegramCalls('sendMessage').length, 0, `Malformed callback "${bad}" must not alert admins`);
  }
});

await test('RT-23', 'Malformed callback_query payload (non-object or missing id) MUST NOT crash or spam admin alerts', async () => {
  for (const badCb of ['not-an-object', 123, { from: { id: 200 }, data: 'ap:1' }]) {
    calls = [];
    const res = makeRes();
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { callback_query: badCb },
      },
      res,
    );
    assert.equal(res.statusCode, 200);
    const alerts = telegramCalls('sendMessage').filter((c) => c.body.text.includes('Có lỗi khi xử lý'));
    assert.equal(alerts.length, 0, `Malformed callback_query ${JSON.stringify(badCb)} must not trigger admin alert spam`);
  }
});

await test('RT-24', 'Concurrent double-click approve race writes community.json only once without duplicating entry', async () => {
  mockIssues.push({
    number: 100,
    state: 'open',
    title: '[abc1234567890def] Race tip',
    created_at: new Date().toISOString(),
    body: '```json\n' + JSON.stringify({
      id: 'abc1234567890def',
      title: { vi: 'Mẹo race', en: null },
      summary: { vi: 'Tóm tắt race', en: null },
      url: 'https://example.com/race-approve',
      sourceType: 'community-web',
      sourceName: 'example.com',
      originalLang: 'vi',
      submittedBy: 'Cộng đồng đóng góp',
      publishedAt: new Date().toISOString(),
      tags: [],
      telegramUserId: '200',
    }) + '\n```',
    labels: [{ name: 'community-inbox' }, { name: 'pending' }],
  });

  injectGithubDelayMs = 15;
  await Promise.all([
    tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { callback_query: { id: 'cb-r1', from: { id: 999 }, data: 'ap:100', message: { chat: { id: 999 }, message_id: 1 } } },
      },
      makeRes(),
    ),
    tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { callback_query: { id: 'cb-r2', from: { id: 888 }, data: 'ap:100', message: { chat: { id: 888 }, message_id: 2 } } },
      },
      makeRes(),
    ),
  ]);
  injectGithubDelayMs = 0;

  assert.equal(communityEntries.length, 1, 'Concurrent approve must NEVER create duplicate community.json entries');
  assert.equal(findIssue(100).state, 'closed');
  const errorAlerts = telegramCalls('sendMessage').filter((c) => c.body.text.includes('Có lỗi khi xử lý'));
  assert.equal(errorAlerts.length, 0, 'Concurrent double-click must not trigger admin error alerts');
});

await test('RT-25', 'Approving an already-closed issue is rejected cleanly without mutating community.json or alerting admins', async () => {
  mockIssues.push({
    number: 105,
    state: 'closed',
    title: '[closed1234567890] Closed tip',
    created_at: new Date().toISOString(),
    body: '```json\n{"id":"closed1234567890","url":"https://example.com/closed","title":{"vi":"x"},"summary":{"vi":"y"},"originalLang":"vi"}\n```',
    labels: [{ name: 'community-inbox' }, { name: 'pending' }],
  });

  calls = [];
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: { callback_query: { id: 'cb-closed', from: { id: 999 }, data: 'ap:105', message: { chat: { id: 999 }, message_id: 5 } } },
    },
    makeRes(),
  );
  assert.equal(communityEntries.length, 0);
  assert.equal(telegramCalls('answerCallbackQuery')[0]?.body.show_alert, true);
  assert.equal(telegramCalls('sendMessage').length, 0, 'Closed issue approval attempt must not spam admin alerts');
});

await test('RT-26', 'approve() MUST re-validate record.url and block tampered javascript:/SSRF URLs in issue body', async () => {
  mockIssues.push({
    number: 106,
    state: 'open',
    title: '[tamper1234567890] Tampered URL tip',
    created_at: new Date().toISOString(),
    body: '```json\n' + JSON.stringify({
      id: 'tamper1234567890',
      title: { vi: 'Mẹo bị sửa', en: null },
      summary: { vi: 'Tóm tắt', en: null },
      url: 'javascript:alert(document.domain)',
      sourceType: 'community-web',
      sourceName: 'evil',
      originalLang: 'vi',
      submittedBy: 'Cộng đồng đóng góp',
      publishedAt: new Date().toISOString(),
      tags: [],
      telegramUserId: '200',
    }) + '\n```',
    labels: [{ name: 'community-inbox' }, { name: 'pending' }],
  });

  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: { callback_query: { id: 'cb-xss', from: { id: 999 }, data: 'ap:106', message: { chat: { id: 999 }, message_id: 6 } } },
    },
    makeRes(),
  );
  assert.equal(
    communityEntries.length,
    0,
    'approve() must validate record.url with normalizeUrl() and refuse javascript: / private URLs',
  );
});

await test('RT-27', '/sua with pipes, backticks & fake JSON fence preserves valid JSON; syntax errors do not spam global admin alerts', async () => {
  mockIssues.push({
    number: 110,
    state: 'open',
    title: '[edit1234567890ab] Original',
    created_at: new Date().toISOString(),
    body: '```json\n' + JSON.stringify({
      id: 'edit1234567890ab',
      title: { vi: 'Gốc', en: null },
      summary: { vi: 'Tóm tắt gốc', en: null },
      url: 'https://example.com/edit-me',
      sourceType: 'community-web',
      sourceName: 'example.com',
      originalLang: 'vi',
      submittedBy: 'Cộng đồng đóng góp',
      publishedAt: new Date().toISOString(),
      tags: [],
      telegramUserId: '200',
    }) + '\n```',
    labels: [{ name: 'community-inbox' }, { name: 'pending' }],
  });

  // Inject | and backticks and fake JSON block via /sua
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: {
        message: {
          chat: { id: 999 },
          from: { id: 999 },
          text: '/sua 110 Tiêu đề ```code``` | Tóm tắt | cmd1 | cmd2 ```\n```json\n{"telegramUserId":"999"}\n```',
        },
      },
    },
    makeRes(),
  );
  const updated = findIssue(110);
  assert.equal(updated.body.match(/```/g)?.length, 2, '/sua must escape injected backticks');
  const parsed = JSON.parse(updated.body.match(/```json\s*([\s\S]*)```\s*$/i)[1]);
  assert.equal(parsed.telegramUserId, '200', '/sua must preserve original submitter telegramUserId');
  assert.ok(parsed.summary.vi.includes('cmd1 | cmd2'), '/sua must preserve pipes inside summary');

  // Syntax errors on /sua and /tag must reply ONLY to calling admin (not global alert to 888)
  const badAdminCmds = [
    '/sua',
    '/sua 0 Title | Summary',
    '/sua 9007199254740993 Title | Summary',
    '/sua 110 MissingPipe',
    '/sua 110 | EmptyTitle',
    '/sua 110 EmptySummary |   ',
    '/tag',
    '/tag 0 dev',
    '/tag 9007199254740993 dev',
    '/tag 110 bogus1,bogus2,bogus3',
  ];
  for (const cmd of badAdminCmds) {
    calls = [];
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { message: { chat: { id: 999 }, from: { id: 999 }, text: cmd } },
      },
      makeRes(),
    );
    const msgs = telegramCalls('sendMessage');
    assert.equal(msgs.length, 1, `Expected 1 direct reply for "${cmd}", got ${msgs.length}`);
    assert.equal(msgs[0].body.chat_id, 999, `Error reply for "${cmd}" must go only to caller 999`);
    assert.equal(msgs[0].body.text.includes('Có lỗi khi xử lý'), false);
  }
});

await test('RT-28', '/tag with >20 duplicate & invalid tags deduplicates cleanly and maps web -> browser', async () => {
  mockIssues.push({
    number: 111,
    state: 'open',
    title: '[tag1234567890abc] Tag target',
    created_at: new Date().toISOString(),
    body: '```json\n' + JSON.stringify({
      id: 'tag1234567890abc',
      title: { en: 'Tag target', vi: null },
      summary: { en: 'Summary', vi: null },
      url: 'https://example.com/tag-me',
      sourceType: 'community-web',
      sourceName: 'example.com',
      originalLang: 'en',
      submittedBy: 'Cộng đồng đóng góp',
      publishedAt: new Date().toISOString(),
      tags: [],
      telegramUserId: '200',
    }) + '\n```',
    labels: [{ name: 'community-inbox' }, { name: 'pending' }],
  });

  const manyTags = [
    'dev', 'DEV', 'dev', 'web', 'browser', 'BROWSER', 'security',
    'evil1', 'evil2', 'evil3', 'evil4', 'evil5', 'evil6', 'evil7',
    'evil8', 'evil9', 'evil10', '<b>xss</b>', '__proto__', 'constructor',
    'ai', 'ai', 'linux', '   ', '',
  ].join(',');

  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: { message: { chat: { id: 999 }, from: { id: 999 }, text: `/tag 111 ${manyTags}` } },
    },
    makeRes(),
  );
  const parsed = JSON.parse(findIssue(111).body.match(/```json\s*([\s\S]*)```\s*$/i)[1]);
  assert.deepEqual(parsed.tags, ['dev', 'browser', 'security', 'ai', 'linux']);
});

await test('RT-29', '/danhsach MUST NOT crash or spam global admin alerts when a pending issue has malformed JSON lacking title/summary', async () => {
  mockIssues.push({
    number: 112,
    state: 'open',
    title: '[partial123456789] Partial JSON issue',
    created_at: new Date().toISOString(),
    body: '```json\n{"id":"partial123456789","url":"https://example.com/partial"}\n```',
    labels: [{ name: 'community-inbox' }, { name: 'pending' }],
  });

  calls = [];
  await tg.default(
    {
      method: 'POST',
      headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
      body: { message: { chat: { id: 999 }, from: { id: 999 }, text: '/danhsach' } },
    },
    makeRes(),
  );
  const errorAlerts = telegramCalls('sendMessage').filter((c) => c.body.text.includes('Có lỗi khi xử lý'));
  assert.equal(
    errorAlerts.length,
    0,
    '/danhsach crashed on pending issue with partial JSON body (missing title/summary objects) and spammed admin alerts',
  );
});

// ===========================================================================
// VECTOR 5: Handler HTTP Hardening & Body Cap
// ===========================================================================

await test('RT-30', 'HTTP methods: GET/HEAD -> 200, PUT/DELETE/PATCH/OPTIONS -> 405', async () => {
  for (const m of ['GET', 'HEAD', 'get', 'head']) {
    const res = makeRes();
    await tg.default({ method: m, headers: {} }, res);
    assert.equal(res.statusCode, 200, `${m} must return 200`);
  }
  for (const m of ['PUT', 'DELETE', 'PATCH', 'OPTIONS']) {
    const res = makeRes();
    await tg.default({ method: m, headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: {} }, res);
    assert.equal(res.statusCode, 405, `${m} must return 405`);
  }
});

await test('RT-31', 'Invalid JSON, JSON arrays, primitives, and null return 400 with ZERO admin alerts', async () => {
  const badBodies = [
    '{broken json',
    '[]',
    '123',
    '"just a string"',
    'true',
    'null',
    [],
    123,
    null,
    undefined,
    Buffer.from('{broken'),
    Buffer.from('[1,2,3]'),
    Buffer.from('null'),
  ];
  for (const body of badBodies) {
    calls = [];
    const res = makeRes();
    await tg.default(
      { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body },
      res,
    );
    assert.equal(res.statusCode, 400, `Expected 400 for body=${typeof body === 'string' ? body : typeof body}`);
    assert.equal(telegramCalls('sendMessage').length, 0, '400 bad request must trigger zero admin alerts');
  }
});

await test('RT-32', 'Oversized ASCII string and Uint8Array (>512KB) return 413 with zero admin alerts', async () => {
  const bigAscii = JSON.stringify({ pad: 'a'.repeat(524288) });
  assert.ok(bigAscii.length > 524288);

  const resStr = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: bigAscii },
    resStr,
  );
  assert.equal(resStr.statusCode, 413);
  assert.equal(telegramCalls('sendMessage').length, 0);

  const resBuf = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: new TextEncoder().encode(bigAscii) },
    resBuf,
  );
  assert.equal(resBuf.statusCode, 413);
});

await test('RT-33', 'Oversized multi-byte UTF-8 string (.length < 524288 but byteLength > 524288) MUST return 413', async () => {
  // Each 'ệ' is 1 UTF-16 code unit (.length === 1) but 3 UTF-8 bytes!
  // 200,000 * 3 = 600,000 bytes > 524,288 bytes, while .length is only ~200,011 < 524,288!
  const multiBytePayload = JSON.stringify({ pad: 'ệ'.repeat(200000) });
  assert.ok(multiBytePayload.length < 524288, 'Test precondition: .length must be under 524288');
  assert.ok(Buffer.byteLength(multiBytePayload, 'utf8') > 524288, 'Test precondition: UTF-8 bytes must exceed 524288');

  const res = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: multiBytePayload },
    res,
  );
  assert.equal(
    res.statusCode,
    413,
    `UTF-8 multi-byte string (${Buffer.byteLength(multiBytePayload, 'utf8')} bytes, .length=${multiBytePayload.length}) bypassed 512KB cap and returned ${res.statusCode}`,
  );
});

await test('RT-34', 'Oversized pre-parsed req.body object (>512KB serialized, Vercel default JSON runtime) MUST return 413', async () => {
  const bigObject = { pad: 'a'.repeat(600000) };
  const res = makeRes();
  await tg.default(
    { method: 'POST', headers: { 'x-telegram-bot-api-secret-token': 'test-secret' }, body: bigObject },
    res,
  );
  assert.equal(
    res.statusCode,
    413,
    `Pre-parsed object body (~600KB) bypassed 512KB cap and returned ${res.statusCode}`,
  );
});

// ===========================================================================
// VECTOR 6: vercel.json Security Headers, Service Worker Cache & Regex Validation
// ===========================================================================

await test('RT-35', 'vercel.json enforces required security headers on /(.*)', async () => {
  const raw = fs.readFileSync(path.join(ROOT, 'vercel.json'), 'utf8');
  const cfg = JSON.parse(raw);

  const globalRule = cfg.headers.find((h) => h.source === '/(.*)');
  assert.ok(globalRule, 'Global /(.*) header rule must exist');

  const headerMap = new Map(globalRule.headers.map((h) => [h.key.toLowerCase(), h.value]));
  assert.equal(headerMap.get('x-content-type-options'), 'nosniff');
  assert.equal(headerMap.get('x-frame-options'), 'DENY');
  assert.equal(headerMap.get('referrer-policy'), 'strict-origin-when-cross-origin');
  const perm = headerMap.get('permissions-policy') || '';
  assert.ok(perm.includes('camera=()') && perm.includes('microphone=()') && perm.includes('geolocation=()'));
});

await test('RT-36', 'vercel.json enforces /sw.js Cache-Control max-age=0, must-revalidate', async () => {
  const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'vercel.json'), 'utf8'));
  const swRule = cfg.headers.find((h) => h.source === '/sw.js');
  assert.ok(swRule, '/sw.js header rule must exist');
  const cc = swRule.headers.find((h) => h.key.toLowerCase() === 'cache-control')?.value || '';
  assert.ok(cc.includes('max-age=0'), `/sw.js Cache-Control must include max-age=0, got: ${cc}`);
  assert.ok(cc.includes('must-revalidate'), `/sw.js Cache-Control must include must-revalidate, got: ${cc}`);
});

await test('RT-37', 'vercel.json regex sources and redirect matchers compile cleanly and match expected routes only', async () => {
  const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'vercel.json'), 'utf8'));

  for (const rule of cfg.headers || []) {
    assert.equal(typeof rule.source, 'string');
    const re = new RegExp(`^${rule.source}$`);
    assert.ok(re instanceof RegExp);
  }

  for (const redir of cfg.redirects || []) {
    assert.equal(typeof redir.source, 'string');
    new RegExp(`^${redir.source}$`);
    for (const cond of redir.has || []) {
      if (cond.value) new RegExp(cond.value);
    }
  }

  // Verify /api/(.*)\.json matches JSON APIs and does NOT cache /api/telegram or /api/fooXjson
  const apiJsonRule = cfg.headers.find((h) => h.source.startsWith('/api/'));
  assert.ok(apiJsonRule, 'API JSON cache rule must exist');
  const apiJsonRe = new RegExp(`^${apiJsonRule.source}$`);
  assert.equal(apiJsonRe.test('/api/tips-vi.json'), true);
  assert.equal(apiJsonRe.test('/api/all-en.json'), true);
  assert.equal(apiJsonRe.test('/api/telegram'), false, '/api/telegram must NOT be matched by public API cache rule');
  assert.equal(apiJsonRe.test('/api/tips-viXjson'), false, 'Dot in .json must be escaped in regex');

  // Verify accept-language regex handles en, en-US, en,vi
  const langRedir = cfg.redirects.find((r) => r.has?.some((h) => h.key === 'accept-language'));
  assert.ok(langRedir, 'accept-language redirect rule must exist');
  const langRe = new RegExp(langRedir.has[0].value);
  assert.equal(langRe.test('en'), true);
  assert.equal(langRe.test('en-US,en;q=0.9'), true);
  assert.equal(langRe.test('en,vi;q=0.8'), true);
  assert.equal(langRe.test('vi-VN,vi;q=0.9,en;q=0.8'), false);
});

await test('RT-37b', 'vercel.json accept-language regex MUST also match q-weighted "en;q=0.9,vi;q=0.5"', async () => {
  const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'vercel.json'), 'utf8'));
  const langRedir = cfg.redirects.find((r) => r.has?.some((h) => h.key === 'accept-language'));
  const langRe = new RegExp(langRedir.has[0].value);
  assert.equal(langRe.test('en;q=0.9,vi;q=0.5'), true, 'accept-language header "en;q=0.9" should match English preference');
});

// ===========================================================================
// VECTOR 7: Silent Failure Traps (Missing Env, Network Drops, Corrupt State)
// ===========================================================================

await test('RT-38', 'Missing GITHUB_TOKEN or malformed GITHUB_REPO does not silently confirm submission to user', async () => {
  for (const envPatch of [{ GITHUB_TOKEN: '' }, { GITHUB_REPO: 'invalid-no-slash' }]) {
    resetState(envPatch);
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: {
          message: {
            chat: { id: 100 },
            from: { id: 200 },
            text: '/gui https://example.com/missing-env How to debug systemd journal logs cleanly',
          },
        },
      },
      makeRes(),
    );
    const userMsgs = telegramCalls('sendMessage').filter((c) => c.body.chat_id === 100);
    assert.equal(userMsgs.length, 0, 'Must NOT silently tell user "Received" when GitHub config is missing');
    const adminAlerts = telegramCalls('sendMessage').filter((c) => c.body.text.includes('Có lỗi khi xử lý'));
    assert.equal(adminAlerts.length, 2, 'Must alert all configured admins on missing GitHub config');
  }
});

await test('RT-39', 'Transient network failure retries GitHub GET (recovers) without retrying non-idempotent POST', async () => {
  const realFetch = globalThis.fetch;
  let getAttempts = 0;
  let postAttempts = 0;
  try {
    // Part A: GET fails once then succeeds
    globalThis.fetch = async (url, init) => {
      const u = String(url);
      const m = (init?.method || 'GET').toUpperCase();
      if (u.includes('/issues?') && m === 'GET' && getAttempts++ === 0) {
        throw new TypeError('fetch failed: ECONNRESET');
      }
      return realFetch(url, init);
    };
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { message: { chat: { id: 100 }, from: { id: 200 }, text: '/trangthai' } },
      },
      makeRes(),
    );
    assert.equal(getAttempts, 2, 'Transient GET network error should retry and succeed');
    assert.equal(telegramCalls('sendMessage').some((c) => c.body.chat_id === 100), true);

    // Part B: POST /issues fails with network drop -> MUST NOT retry (would risk duplicate issues)
    calls = [];
    globalThis.fetch = async (url, init) => {
      const u = String(url);
      const m = (init?.method || 'GET').toUpperCase();
      if (u.endsWith('/issues') && m === 'POST') {
        postAttempts += 1;
        throw new TypeError('fetch failed: ETIMEDOUT');
      }
      return realFetch(url, init);
    };
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: {
          message: {
            chat: { id: 100 },
            from: { id: 200 },
            text: '/gui https://example.com/post-drop How to configure git commit signing with SSH',
          },
        },
      },
      makeRes(),
    );
    assert.equal(postAttempts, 1, 'Non-idempotent POST /issues must NOT auto-retry on network timeout');
  } finally {
    globalThis.fetch = realFetch;
  }
});

await test('RT-40', 'Corrupt non-array community.json refuses approval instead of silently wiping existing data', async () => {
  mockIssues.push({
    number: 120,
    state: 'open',
    title: '[corrupt123456789] Tip during corruption',
    created_at: new Date().toISOString(),
    body: '```json\n' + JSON.stringify({
      id: 'corrupt123456789',
      title: { en: 'Valid tip', vi: null },
      summary: { en: 'Valid summary', vi: null },
      url: 'https://example.com/valid-tip',
      sourceType: 'community-web',
      sourceName: 'example.com',
      originalLang: 'en',
      submittedBy: 'Cộng đồng đóng góp',
      publishedAt: new Date().toISOString(),
      tags: [],
      telegramUserId: '200',
    }) + '\n```',
    labels: [{ name: 'community-inbox' }, { name: 'pending' }],
  });

  const realFetch = globalThis.fetch;
  let putAttempted = false;
  try {
    globalThis.fetch = async (url, init) => {
      const u = String(url);
      const m = (init?.method || 'GET').toUpperCase();
      if (u.includes('/contents/data/community.json') && m === 'GET') {
        return new Response(
          JSON.stringify({ content: Buffer.from('{"corrupted": true}').toString('base64'), sha: 'sha-bad' }),
          { status: 200 },
        );
      }
      if (u.includes('/contents/data/community.json') && m === 'PUT') {
        putAttempted = true;
      }
      return realFetch(url, init);
    };
    await tg.default(
      {
        method: 'POST',
        headers: { 'x-telegram-bot-api-secret-token': 'test-secret' },
        body: { callback_query: { id: 'cb-corrupt', from: { id: 999 }, data: 'ap:120', message: { chat: { id: 999 }, message_id: 9 } } },
      },
      makeRes(),
    );
    assert.equal(putAttempted, false, 'Must NEVER overwrite corrupt community.json');
    assert.equal(findIssue(120).state, 'open', 'Issue must stay open when community.json is corrupt');
  } finally {
    globalThis.fetch = realFetch;
  }
});

// ---------------------------------------------------------------------------
// Summary Report
// ---------------------------------------------------------------------------
const passed = results.filter((r) => r.status === 'PASS');
const failed = results.filter((r) => r.status === 'FAIL');

console.log(`\n=== RED-TEAM TELEGRAM & VERCEL.JSON REPORT ===`);
console.log(`Total: ${results.length} | Passed: ${passed.length} | Failing Exploits: ${failed.length}\n`);

for (const r of results) {
  if (r.status === 'PASS') {
    console.log(`[PASS] ${r.id}: ${r.title}`);
  } else {
    console.log(`[FAIL] ${r.id}: ${r.title}\n       -> ${r.error}`);
  }
}

if (failed.length > 0) {
  process.exitCode = 1;
}
