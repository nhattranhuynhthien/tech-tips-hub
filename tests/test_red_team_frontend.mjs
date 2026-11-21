import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const ROOT = process.cwd();
const DIST_DIR = path.join(ROOT, 'dist');

// ============================================================================
// Lightweight Zero-Dependency DOM + Browser Sandbox for Executing Real Client JS
// ============================================================================

class MockClassList {
  constructor(el) {
    this._el = el;
    this._set = new Set();
  }
  _syncFromAttr(str) {
    this._set = new Set(String(str || '').trim().split(/\s+/).filter(Boolean));
  }
  _syncToAttr() {
    this._el._attrs.set('class', Array.from(this._set).join(' '));
  }
  add(...tokens) {
    for (const t of tokens) if (t) this._set.add(t);
    this._syncToAttr();
  }
  remove(...tokens) {
    for (const t of tokens) this._set.delete(t);
    this._syncToAttr();
  }
  toggle(token, force) {
    if (force === true) {
      this._set.add(token);
      this._syncToAttr();
      return true;
    }
    if (force === false) {
      this._set.delete(token);
      this._syncToAttr();
      return false;
    }
    if (this._set.has(token)) {
      this._set.delete(token);
      this._syncToAttr();
      return false;
    }
    this._set.add(token);
    this._syncToAttr();
    return true;
  }
  contains(token) {
    return this._set.has(token);
  }
}

class MockNode {
  constructor(nodeType, nodeName) {
    this.nodeType = nodeType;
    this.nodeName = nodeName;
    this.parentNode = null;
    this.childNodes = [];
    this._listeners = new Map();
  }
  appendChild(child) {
    if (!child) return child;
    if (child.nodeType === 11) {
      const items = [...child.childNodes];
      child.childNodes = [];
      for (const item of items) this.appendChild(item);
      return child;
    }
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  append(...nodes) {
    for (const n of nodes) {
      if (typeof n === 'string') {
        this.appendChild(new MockText(n));
      } else if (n) {
        this.appendChild(n);
      }
    }
  }
  removeChild(child) {
    const idx = this.childNodes.indexOf(child);
    if (idx !== -1) {
      this.childNodes.splice(idx, 1);
      child.parentNode = null;
    }
    return child;
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
  addEventListener(type, fn, capture = false) {
    const key = `${type}:${capture ? '1' : '0'}`;
    if (!this._listeners.has(key)) this._listeners.set(key, []);
    this._listeners.get(key).push(fn);
  }
  dispatchEvent(event) {
    if (!event.target) event.target = this;
    const chain = [];
    let cur = this;
    while (cur) {
      chain.push(cur);
      cur = cur.parentNode;
    }
    // Capture phase
    for (let i = chain.length - 1; i >= 0; i--) {
      const handlers = chain[i]._listeners.get(`${event.type}:1`) || [];
      for (const fn of [...handlers]) fn(event);
      if (event._stopped) return !event.defaultPrevented;
    }
    // Bubble phase
    for (let i = 0; i < chain.length; i++) {
      const handlers = chain[i]._listeners.get(`${event.type}:0`) || [];
      for (const fn of [...handlers]) fn(event);
      if (event._stopped) return !event.defaultPrevented;
    }
    return !event.defaultPrevented;
  }
  get textContent() {
    return this.childNodes.map((c) => c.textContent).join('');
  }
  set textContent(val) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = [];
    const str = String(val ?? '');
    if (str.length > 0) this.appendChild(new MockText(str));
  }
}

class MockText extends MockNode {
  constructor(text) {
    super(3, '#text');
    this._text = String(text ?? '');
  }
  get textContent() {
    return this._text;
  }
  set textContent(val) {
    this._text = String(val ?? '');
  }
}

class MockDocumentFragment extends MockNode {
  constructor() {
    super(11, '#document-fragment');
  }
}

function escapeHtmlAttr(v) {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeHtmlText(v) {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function camelToDataAttr(prop) {
  return 'data-' + prop.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase());
}

class MockElement extends MockNode {
  constructor(tagName, ownerDocument) {
    super(1, tagName.toUpperCase());
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this._attrs = new Map();
    this.classList = new MockClassList(this);
    this.style = {};
    this.value = '';
    this.disabled = false;
    this.files = [];
    this.options = [];
    this.isContentEditable = false;
    this._innerHtmlUsed = false;
    this.dataset = new Proxy(
      {},
      {
        get: (_, prop) => {
          if (typeof prop !== 'string') return undefined;
          return this._attrs.get(camelToDataAttr(prop));
        },
        set: (_, prop, val) => {
          if (typeof prop === 'string') {
            this._attrs.set(camelToDataAttr(prop), String(val));
          }
          return true;
        },
      },
    );
  }
  get id() {
    return this._attrs.get('id') || '';
  }
  set id(v) {
    this._attrs.set('id', String(v));
  }
  get className() {
    return this._attrs.get('class') || '';
  }
  set className(v) {
    this._attrs.set('class', String(v));
    this.classList._syncFromAttr(v);
  }
  get href() {
    return this._attrs.get('href') || '';
  }
  set href(v) {
    this._attrs.set('href', String(v));
  }
  get target() {
    return this._attrs.get('target') || '';
  }
  set target(v) {
    this._attrs.set('target', String(v));
  }
  get rel() {
    return this._attrs.get('rel') || '';
  }
  set rel(v) {
    this._attrs.set('rel', String(v));
  }
  get alt() {
    return this._attrs.get('alt') || '';
  }
  set alt(v) {
    this._attrs.set('alt', String(v));
  }
  get src() {
    return this._attrs.get('src') || '';
  }
  set src(v) {
    this._attrs.set('src', String(v));
  }
  get type() {
    return this._attrs.get('type') || '';
  }
  set type(v) {
    this._attrs.set('type', String(v));
  }
  get title() {
    return this._attrs.get('title') || '';
  }
  set title(v) {
    this._attrs.set('title', String(v));
  }
  get lang() {
    return this._attrs.get('lang') || '';
  }
  set lang(v) {
    this._attrs.set('lang', String(v));
  }
  get innerHTML() {
    return this.childNodes
      .map((c) => {
        if (c.nodeType === 3) return escapeHtmlText(c.textContent);
        if (c.nodeType === 1) {
          const attrs = Array.from(c._attrs.entries())
            .map(([k, v]) => ` ${k}="${escapeHtmlAttr(v)}"`)
            .join('');
          const tag = c.tagName.toLowerCase();
          return `<${tag}${attrs}>${c.innerHTML}</${tag}>`;
        }
        return '';
      })
      .join('');
  }
  set innerHTML(v) {
    this._innerHtmlUsed = true;
    this.textContent = v;
  }
  setAttribute(name, value) {
    const key = String(name).toLowerCase();
    const val = String(value);
    this._attrs.set(key, val);
    if (key === 'class') this.classList._syncFromAttr(val);
  }
  getAttribute(name) {
    const key = String(name).toLowerCase();
    return this._attrs.has(key) ? this._attrs.get(key) : null;
  }
  removeAttribute(name) {
    const key = String(name).toLowerCase();
    this._attrs.delete(key);
    if (key === 'class') this.classList._syncFromAttr('');
  }
  hasAttribute(name) {
    return this._attrs.has(String(name).toLowerCase());
  }
  focus() {
    if (this.ownerDocument) this.ownerDocument.activeElement = this;
  }
  select() {}
  scrollIntoView() {}
  click() {
    this.dispatchEvent(new MockEvent('click', { bubbles: true }));
  }
  matches(selector) {
    const parts = selector.split(',').map((s) => s.trim()).filter(Boolean);
    return parts.some((sel) => this._matchesSingle(sel));
  }
  _matchesSingle(sel) {
    // Handle descendant selector like ".tip-card a[href]"
    if (/\s+/.test(sel)) {
      const segs = sel.split(/\s+/);
      const last = segs[segs.length - 1];
      if (!this._matchesSimple(last)) return false;
      let ancestor = this.parentNode;
      let idx = segs.length - 2;
      while (ancestor && ancestor.nodeType === 1 && idx >= 0) {
        if (ancestor._matchesSimple(segs[idx])) idx--;
        ancestor = ancestor.parentNode;
      }
      return idx < 0;
    }
    return this._matchesSimple(sel);
  }
  _matchesSimple(sel) {
    let rest = sel;
    // tag prefix
    const tagMatch = rest.match(/^([a-zA-Z0-9_-]+)/);
    if (tagMatch) {
      if (this.tagName !== tagMatch[1].toUpperCase()) return false;
      rest = rest.slice(tagMatch[0].length);
    }
    // #id
    for (const m of rest.matchAll(/#([a-zA-Z0-9_-]+)/g)) {
      if (this.id !== m[1]) return false;
    }
    // .class
    for (const m of rest.matchAll(/\.([a-zA-Z0-9_-]+)/g)) {
      if (!this.classList.contains(m[1])) return false;
    }
    // [attr] or [attr="val"]
    for (const m of rest.matchAll(/\[([a-zA-Z0-9_-]+)(?:=["']?([^"'\]]+)["']?)?\]/g)) {
      if (!this.hasAttribute(m[1])) return false;
      if (m[2] !== undefined && this.getAttribute(m[1]) !== m[2]) return false;
    }
    return true;
  }
  closest(selector) {
    let cur = this;
    while (cur && cur.nodeType === 1) {
      if (cur.matches(selector)) return cur;
      cur = cur.parentNode;
    }
    return null;
  }
  querySelectorAll(selector) {
    const results = [];
    const visit = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 1) {
          if (child.matches(selector)) results.push(child);
          visit(child);
        }
      }
    };
    visit(this);
    return results;
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

class MockEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = init.bubbles !== false;
    this.defaultPrevented = false;
    this._stopped = false;
    this.target = init.target || null;
    this.key = init.key || '';
    this.ctrlKey = Boolean(init.ctrlKey);
    this.metaKey = Boolean(init.metaKey);
    this.detail = init.detail;
  }
  preventDefault() {
    this.defaultPrevented = true;
  }
  stopPropagation() {
    this._stopped = true;
  }
}

function createBrowserSandbox(options = {}) {
  const {
    lang = 'vi',
    pathname = '/vi',
    search = '',
    throwStorage = false,
    throwCookie = false,
    initialStorage = {},
    fetchImpl = async () => new Response('[]', { status: 200 }),
  } = options;

  const store = new Map(Object.entries(initialStorage));
  const localStorage = {
    getItem(k) {
      if (throwStorage) throw new DOMException('SecurityError: storage disabled', 'SecurityError');
      return store.has(k) ? store.get(k) : null;
    },
    setItem(k, v) {
      if (throwStorage) throw new DOMException('QuotaExceededError: storage blocked', 'QuotaExceededError');
      store.set(String(k), String(v));
    },
    removeItem(k) {
      if (throwStorage) throw new DOMException('SecurityError', 'SecurityError');
      store.delete(String(k));
    },
    clear() {
      store.clear();
    },
    _raw: store,
  };

  let cookieJar = '';
  const doc = new MockNode(9, '#document');
  const htmlEl = new MockElement('html', doc);
  htmlEl.setAttribute('lang', lang);
  const headEl = new MockElement('head', doc);
  const bodyEl = new MockElement('body', doc);
  const themeMeta = new MockElement('meta', doc);
  themeMeta.setAttribute('name', 'theme-color');
  themeMeta.setAttribute('content', '#0F1114');
  headEl.appendChild(themeMeta);
  htmlEl.appendChild(headEl);
  htmlEl.appendChild(bodyEl);
  doc.appendChild(htmlEl);

  doc.documentElement = htmlEl;
  doc.head = headEl;
  doc.body = bodyEl;
  doc.readyState = 'complete';
  doc.title = '';
  doc.activeElement = bodyEl;
  doc.createElement = (tag) => new MockElement(tag, doc);
  doc.createElementNS = (_, tag) => new MockElement(tag, doc);
  doc.createTextNode = (txt) => new MockText(txt);
  doc.createDocumentFragment = () => new MockDocumentFragment();
  doc.getElementById = (id) => htmlEl.querySelector(`#${id}`);
  doc.querySelector = (sel) => htmlEl.querySelector(sel);
  doc.querySelectorAll = (sel) => htmlEl.querySelectorAll(sel);
  doc.execCommand = () => false;

  Object.defineProperty(doc, 'cookie', {
    get() {
      if (throwCookie) throw new DOMException('SecurityError: cookie access denied', 'SecurityError');
      return cookieJar;
    },
    set(val) {
      if (throwCookie) throw new DOMException('SecurityError: cookie write denied', 'SecurityError');
      cookieJar = String(val);
    },
  });

  const historyCalls = [];
  const locationObj = {
    pathname,
    search,
    href: `https://meocongnghe.vercel.app${pathname}${search}`,
    origin: 'https://meocongnghe.vercel.app',
    replacedTo: null,
    reloaded: false,
    replace(url) {
      this.replacedTo = url;
    },
    reload() {
      this.reloaded = true;
    },
  };

  const windowListeners = new Map();
  const timers = [];

  const win = {
    document: doc,
    localStorage,
    location: locationObj,
    history: {
      replaceState(_state, _title, url) {
        historyCalls.push(url);
        const parsed = new URL(url, 'https://meocongnghe.vercel.app');
        locationObj.pathname = parsed.pathname;
        locationObj.search = parsed.search;
        locationObj.href = parsed.toString();
      },
    },
    navigator: {
      clipboard: { writeText: async () => {} },
    },
    innerWidth: 1280,
    scrollTo() {},
    matchMedia: () => ({ matches: false }),
    fetch: fetchImpl,
    URL,
    URLSearchParams,
    Blob,
    Response,
    Headers,
    Request,
    Intl,
    CustomEvent: MockEvent,
    Event: MockEvent,
    Element: MockElement,
    Node: MockNode,
    console: { log() {}, warn() {}, error() {} },
    setTimeout(fn, ms) {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearTimeout() {},
    addEventListener(type, fn) {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push(fn);
    },
    dispatchEvent(event) {
      const fns = windowListeners.get(event.type) || [];
      for (const fn of [...fns]) fn(event);
      return true;
    },
  };
  win.window = win;
  win.self = win;
  win.globalThis = win;

  const ctx = vm.createContext(win);
  return {
    win,
    doc,
    ctx,
    localStorage,
    historyCalls,
    timers,
    runScript(code, filename = 'inline.js') {
      return vm.runInContext(code, ctx, { filename });
    },
    runFile(relPath) {
      const full = path.join(ROOT, relPath);
      const code = fs.readFileSync(full, 'utf8');
      return vm.runInContext(code, ctx, { filename: relPath });
    },
  };
}

function extractInlineScripts(html) {
  const scripts = [];
  for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    const attrs = m[1];
    if (/\bsrc\s*=/.test(attrs) || /application\/ld\+json/i.test(attrs)) continue;
    scripts.push(m[2]);
  }
  return scripts;
}

function walkFiles(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walkFiles(full, out);
    else out.push(full);
  }
  return out;
}

function hexToRgb(hex) {
  const h = hex.replace('#', '').trim();
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function blendColor(colorStr, baseHex) {
  if (colorStr.startsWith('#')) return hexToRgb(colorStr);
  const m = colorStr.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)/i);
  if (!m) throw new Error(`Unsupported color format: ${colorStr}`);
  const [r, g, b, a] = [Number(m[1]), Number(m[2]), Number(m[3]), m[4] !== undefined ? Number(m[4]) : 1];
  const [br, bg, bb] = hexToRgb(baseHex);
  return [r * a + br * (1 - a), g * a + bg * (1 - a), b * a + bb * (1 - a)];
}

function relativeLuminance([r, g, b]) {
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrastRatio(fgRgb, bgRgb) {
  const l1 = relativeLuminance(fgRgb);
  const l2 = relativeLuminance(bgRgb);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

// ============================================================================
// Test Runner Harness (runs ALL tests, never stops on first failure)
// ============================================================================

const results = [];

async function test(id, vector, name, fn) {
  try {
    await fn();
    results.push({ id, vector, name, status: 'PASS' });
    console.log(`[PASS] ${id} (${vector}): ${name}`);
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    results.push({ id, vector, name, status: 'FAIL', error: message });
    console.error(`[FAIL] ${id} (${vector}): ${name}\n       -> ${message}`);
  }
}

const DEFAULT_LABELS = {
  difficulty: { easy: 'Dễ', medium: 'Vừa', advanced: 'Nâng cao' },
  contentTypes: { community: 'Cộng đồng', video: 'Video', vendor: 'Hãng công nghệ', article: 'Bài viết' },
  notTranslated: 'Chưa dịch',
  machineTranslated: 'Bản dịch tự động',
  community: 'Cộng đồng',
  moreSources: 'nguồn khác',
  updated: 'cập nhật',
  readOriginal: 'Đọc bài gốc',
  original: 'Bài gốc',
};

// ============================================================================
// VECTOR 1: DOM XSS, Protocol Injection & Parser / Unicode Traps
// ============================================================================

await test(
  'T01',
  'DOM XSS',
  'public/js/tip-card.js MUST block javascript:, data:, vbscript: protocols in tip.url',
  () => {
    const sb = createBrowserSandbox({ lang: 'vi' });
    sb.runFile('public/js/tip-card.js');
    const dangerousUrls = [
      'javascript:alert(1)',
      'JAVASCRIPT:alert(document.domain)',
      '   javascript:alert(1)',
      '\tjavascript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
    ];
    for (const badUrl of dangerousUrls) {
      const card = sb.win.TipCardRenderer.create(
        {
          id: 'xss-url-1',
          slug: 'xss-url-1',
          url: badUrl,
          title: { vi: 'Safe Title', en: 'Safe Title' },
          summary: { vi: 'Safe Summary', en: 'Safe Summary' },
          source: { id: 'devto', name: 'Dev.to', content_type: 'article' },
          categories: ['security'],
          original_lang: 'en',
          published_at: '2026-11-20T10:00:00Z',
          fetched_at: '2026-11-20T10:05:00Z',
          score: 50,
        },
        'vi',
        DEFAULT_LABELS,
      );
      const links = card.querySelectorAll('a');
      const externalLink = links.find((a) => a.getAttribute('target') === '_blank');
      assert.ok(externalLink, 'External link should exist');
      const renderedHref = externalLink.getAttribute('href') || '';
      assert.ok(
        !/^\s*(javascript|data|vbscript):/i.test(renderedHref),
        `Unsafe protocol rendered verbatim in public/js/tip-card.js:245 -> href="${renderedHref}" for input "${badUrl}"`,
      );
    }
  },
);

await test(
  'T02',
  'SSR XSS',
  'TipCard.astro, TrickOfTheDay.astro, and TipDetailPage.astro MUST validate http(s) protocol on external tip.url & alsoFrom.url',
  () => {
    const targets = [
      { file: 'src/components/TipCard.astro', pattern: /href=\{tip\.url\}/ },
      { file: 'src/components/TrickOfTheDay.astro', pattern: /href=\{tip\.url\}/ },
      { file: 'src/components/pages/TipDetailPage.astro', pattern: /href=\{tip\.url\}/ },
      { file: 'src/components/pages/TipDetailPage.astro', pattern: /href=\{source\.url\}/ },
    ];
    const vulnerable = [];
    for (const t of targets) {
      const src = fs.readFileSync(path.join(ROOT, t.file), 'utf8');
      if (t.pattern.test(src)) {
        vulnerable.push(`${t.file} binds raw unsanitized ${t.pattern}`);
      }
    }
    assert.equal(
      vulnerable.length,
      0,
      `Raw unsanitized external href bindings allow javascript:/data: XSS: ${vulnerable.join('; ')}`,
    );
  },
);

await test(
  'T03',
  'DOM XSS',
  'public/js/tip-card.js MUST neutralize HTML/script payloads in title, summary, source.name, source.id, slug, categories',
  () => {
    const sb = createBrowserSandbox({ lang: 'vi' });
    sb.runFile('public/js/tip-card.js');
    const payload = '<img src=x onerror=alert(1)></script><script>alert(1)</script>" onclick="alert(1)';
    const card = sb.win.TipCardRenderer.create(
      {
        id: 'xss-fields-1',
        slug: '../../<script>alert(1)</script>',
        url: 'https://example.com/safe',
        title: { vi: payload, en: payload },
        summary: { vi: payload, en: payload },
        source: { id: '../evil"onerror=1', name: payload, content_type: payload },
        categories: [payload],
        original_lang: 'en',
        published_at: '2026-11-20T10:00:00Z',
        fetched_at: '2026-11-20T10:05:00Z',
        score: 10,
      },
      'vi',
      DEFAULT_LABELS,
    );
    assert.equal(card.querySelectorAll('script').length, 0, 'No injected <script> nodes allowed');
    assert.equal(card.querySelectorAll('img').length, 1, 'Only the single favicon <img> is allowed');
    const favicon = card.querySelector('img');
    assert.ok(!favicon.hasAttribute('onerror'), 'Favicon must not have inline onerror');
    assert.ok(favicon.src.includes('%2F'), 'source.id path traversal characters must be URI-encoded');
    const titleLink = card.querySelector('h3 a');
    assert.equal(titleLink.textContent, payload, 'Title must render literally as text');
    assert.ok(titleLink.href.startsWith('/vi/tip/') && !titleLink.href.includes('<script>'), 'Slug must be URI-encoded');
  },
);

await test(
  'T04',
  'DOM XSS & Regex Trap',
  'public/js/search.js MUST neutralize XSS payloads and regex metacharacters in titles and search queries',
  async () => {
    const xssTitle = 'Guide <img src=x onerror=alert(1)> [a-z]+ (.*) \\ $1 ^test$';
    const sb = createBrowserSandbox({
      lang: 'vi',
      fetchImpl: async () =>
        new Response(
          JSON.stringify([
            {
              id: 'tip-regex-1',
              slug: 'tip-regex-1',
              title: { vi: xssTitle, en: xssTitle },
              summary: { vi: '</script><script>alert(1)</script>', en: 'summary' },
              source: { id: 'src1', name: '" onclick="alert(1)' },
              categories: ['<svg onload=alert(1)>'],
              tags: ['[a-z]+', '(.*)'],
              original_lang: 'vi',
            },
          ]),
          { status: 200 },
        ),
    });

    const modal = sb.doc.createElement('div');
    modal.id = 'search-modal';
    modal.className = 'hidden';
    const input = sb.doc.createElement('input');
    input.id = 'search-input';
    const resultsEl = sb.doc.createElement('div');
    resultsEl.id = 'search-results';
    modal.append(input, resultsEl);
    sb.doc.body.appendChild(modal);

    sb.runFile('public/js/search.js');
    sb.win.openTechTipsSearch();
    await new Promise((r) => setTimeout(r, 10));

    for (const q of ['<img src=x onerror=alert(1)>', '[a-z]+', '(.*)', '\\', '^test$', '</script>']) {
      input.value = q;
      input.dispatchEvent(new MockEvent('input'));
      assert.equal(resultsEl.querySelectorAll('script').length, 0, `No <script> injected for query ${q}`);
      assert.equal(resultsEl.querySelectorAll('img').length, 0, `No <img> injected for query ${q}`);
      assert.equal(resultsEl.querySelectorAll('svg').length, 0, `No <svg> injected for query ${q}`);
    }
    input.value = '[a-z]+';
    input.dispatchEvent(new MockEvent('input'));
    const marks = resultsEl.querySelectorAll('mark');
    assert.equal(marks.length, 1, 'Literal regex metacharacter query must highlight cleanly');
    assert.equal(marks[0].textContent, '[a-z]+');
  },
);

await test(
  'T05',
  'Unicode / Parser Trap',
  'public/js/search.js highlighting MUST NOT tear Vietnamese NFD combining diacritics away from their base vowel across <mark>',
  async () => {
    // NFD decomposed Vietnamese: "Thủ thuật" -> "Thu\u0309 thua\u0302\u0323t"
    const nfdTitle = 'Thủ thuật đổi mật khẩu 🚀'.normalize('NFD');
    const sb = createBrowserSandbox({
      lang: 'vi',
      fetchImpl: async () =>
        new Response(
          JSON.stringify([
            {
              id: 'tip-nfd-1',
              slug: 'tip-nfd-1',
              title: { vi: nfdTitle },
              summary: { vi: 'Tóm tắt' },
              source: { id: 's', name: 'Src' },
              categories: ['security'],
              tags: [],
              original_lang: 'vi',
            },
          ]),
          { status: 200 },
        ),
    });

    const modal = sb.doc.createElement('div');
    modal.id = 'search-modal';
    modal.className = 'hidden';
    const input = sb.doc.createElement('input');
    input.id = 'search-input';
    const resultsEl = sb.doc.createElement('div');
    resultsEl.id = 'search-results';
    modal.append(input, resultsEl);
    sb.doc.body.appendChild(modal);

    sb.runFile('public/js/search.js');
    sb.win.openTechTipsSearch();
    await new Promise((r) => setTimeout(r, 10));

    input.value = 'thu';
    input.dispatchEvent(new MockEvent('input'));

    const heading = resultsEl.querySelector('h4');
    assert.ok(heading, 'Heading should be rendered');
    assert.equal(heading.textContent, nfdTitle, 'Full text content must remain lossless');
    const marks = heading.querySelectorAll('mark');
    assert.ok(marks.length >= 1, 'Must highlight "Thu"');
    // Check that the first <mark> includes the combining hook \u0309 (not torn off into the next text node!)
    assert.equal(
      marks[0].textContent.normalize('NFC'),
      'Thủ',
      `Combining mark was severed from base character! First <mark> got ${JSON.stringify(marks[0].textContent)} instead of "Thu\\u0309"`,
    );
    // Also check no text node starts with an orphaned combining diacritical mark
    for (const child of heading.childNodes) {
      if (child.nodeType === 3) {
        assert.ok(
          !/^[\u0300-\u036f]/.test(child.textContent),
          `Orphaned combining mark leaked into text node outside <mark>: ${JSON.stringify(child.textContent)}`,
        );
      }
    }
  },
);

await test(
  'T06',
  'Unicode / Evasion Trap',
  'Combining-diacritic-only query ("\\u0301") MUST NOT match every unrelated tip in search.js',
  async () => {
    const sb = createBrowserSandbox({
      lang: 'vi',
      fetchImpl: async () =>
        new Response(
          JSON.stringify([
            {
              id: 'tip-plain-1',
              slug: 'tip-plain-1',
              title: { vi: 'Docker Compose networking basics' },
              summary: { vi: 'ASCII only summary' },
              source: { id: 's', name: 'Src' },
              categories: ['dev'],
              tags: ['docker'],
              original_lang: 'en',
            },
          ]),
          { status: 200 },
        ),
    });

    const modal = sb.doc.createElement('div');
    modal.id = 'search-modal';
    modal.className = 'hidden';
    const input = sb.doc.createElement('input');
    input.id = 'search-input';
    const resultsEl = sb.doc.createElement('div');
    resultsEl.id = 'search-results';
    modal.append(input, resultsEl);
    sb.doc.body.appendChild(modal);

    sb.runFile('public/js/search.js');
    sb.win.openTechTipsSearch();
    await new Promise((r) => setTimeout(r, 10));

    input.value = '\u0301'; // standalone combining acute accent
    input.dispatchEvent(new MockEvent('input'));

    const matchedLinks = resultsEl.querySelectorAll('[data-search-result]');
    assert.equal(
      matchedLinks.length,
      0,
      'Combining-mark-only query collapsed qNorm to "" and matched every ASCII tip via .includes("")!',
    );
  },
);

await test(
  'T07',
  'Parser / JSON-LD Escaping',
  'Layout.astro JSON-LD serialization MUST escape </script>, <!--, -->, \\u2028, and \\u2029',
  () => {
    const layoutSrc = fs.readFileSync(path.join(ROOT, 'src/layouts/Layout.astro'), 'utf8');
    const exprMatch = layoutSrc.match(/type="application\/ld\+json"\s+set:html=\{([^}]+)\}/);
    assert.ok(exprMatch, 'Could not locate JSON-LD set:html expression in src/layouts/Layout.astro');
    const serializerExpr = exprMatch[1];

    const hostileSchema = {
      '@context': 'https://schema.org',
      '@type': 'TechArticle',
      headline: '</script><script>alert(1)</script> <!-- comment --> line\u2028para\u2029',
    };
    const serialized = vm.runInNewContext(serializerExpr, { schema: hostileSchema });

    assert.ok(!serialized.includes('</script'), 'Must escape </script');
    assert.ok(!serialized.includes('<!--'), 'Must escape <!--');
    assert.ok(!serialized.includes('-->'), `Layout.astro:115 fails to escape HTML comment close "-->" in JSON-LD: ${serialized}`);
    assert.ok(!serialized.includes('\u2028'), 'Layout.astro:115 fails to escape U+2028 Line Separator in JSON-LD');
    assert.ok(!serialized.includes('\u2029'), 'Layout.astro:115 fails to escape U+2029 Paragraph Separator in JSON-LD');
    assert.deepEqual(JSON.parse(serialized), hostileSchema, 'Escaped JSON-LD must still JSON.parse losslessly');
  },
);

await test(
  'T08',
  'DOM XSS',
  'SavedPage.astro MUST safely escape XSS payloads in bookmarked tip fields',
  async () => {
    const savedHtml = fs.readFileSync(path.join(DIST_DIR, 'vi/saved/index.html'), 'utf8');
    const scripts = extractInlineScripts(savedHtml);
    const savedScript = scripts.find((s) => s.includes('SAVED_KEY') && s.includes('renderSaved'));
    assert.ok(savedScript, 'Could not locate SavedPage inline script');

    const payload = '<img src=x onerror=alert(1)><script>alert(1)</script>';
    const sb = createBrowserSandbox({
      lang: 'vi',
      pathname: '/vi/saved',
      initialStorage: { techtips_saved: JSON.stringify(['xss-saved-1']) },
      fetchImpl: async () =>
        new Response(
          JSON.stringify([
            {
              id: 'xss-saved-1',
              slug: '../<script>alert(1)</script>',
              title: { vi: payload },
              summary: { vi: payload },
              source: { id: 's', name: payload },
              categories: [payload],
              tags: [payload],
            },
          ]),
          { status: 200 },
        ),
    });

    for (const [id, tag] of [
      ['saved-stream', 'div'],
      ['saved-empty-state', 'div'],
      ['saved-no-match', 'div'],
      ['saved-counter', 'p'],
      ['saved-search-wrap', 'div'],
      ['saved-search-input', 'input'],
      ['saved-stale-banner', 'div'],
      ['saved-stale-text', 'span'],
      ['clean-stale-btn', 'button'],
      ['export-bookmarks-btn', 'button'],
      ['import-bookmarks-btn', 'button'],
      ['import-bookmarks-input', 'input'],
    ]) {
      const el = sb.doc.createElement(tag);
      el.id = id;
      sb.doc.body.appendChild(el);
    }

    sb.runScript(savedScript, 'SavedPage.inline.js');
    await new Promise((r) => setTimeout(r, 20));

    const stream = sb.doc.getElementById('saved-stream');
    assert.equal(stream.querySelectorAll('script').length, 0);
    assert.equal(stream.querySelectorAll('img').length, 0);
    const cardLink = stream.querySelector('h2 a');
    assert.ok(cardLink, 'Saved card link should render');
    assert.equal(cardLink.textContent, payload);
    assert.ok(!cardLink.href.includes('<script>'), 'Saved card href must URI-encode slug');
  },
);

await test(
  'T09',
  'DOM XSS',
  'public/js/actions.js showToast MUST render XSS payload safely as textContent',
  () => {
    const sb = createBrowserSandbox({ lang: 'en' });
    sb.runFile('public/js/actions.js');
    const payload = '<img src=x onerror=alert(1)><script>alert(2)</script>';
    sb.win.TechTipsActions.showToast(payload, 'error');
    const toast = sb.doc.getElementById('techtips-toast');
    assert.ok(toast, 'Toast element should exist');
    assert.equal(toast.querySelectorAll('img').length, 0);
    assert.equal(toast.querySelectorAll('script').length, 0);
    assert.equal(toast.querySelector('span').textContent, payload);
  },
);

await test(
  'T10',
  'Malformed Data Fuzzing',
  'public/js/search.js MUST NOT crash on non-array tags/categories or emit /vi/tip/undefined on missing id/slug',
  async () => {
    const sb = createBrowserSandbox({
      lang: 'vi',
      fetchImpl: async () =>
        new Response(
          JSON.stringify([
            {
              // Missing both slug & id, non-array tags & categories
              title: { vi: 'Malformed Docker tip' },
              summary: { vi: 'Summary' },
              source: { id: 'src', name: 'Src' },
              categories: 'dev',
              tags: 'docker',
              original_lang: 'vi',
            },
          ]),
          { status: 200 },
        ),
    });

    const modal = sb.doc.createElement('div');
    modal.id = 'search-modal';
    modal.className = 'hidden';
    const input = sb.doc.createElement('input');
    input.id = 'search-input';
    const resultsEl = sb.doc.createElement('div');
    resultsEl.id = 'search-results';
    modal.append(input, resultsEl);
    sb.doc.body.appendChild(modal);

    sb.runFile('public/js/search.js');
    sb.win.openTechTipsSearch();
    await new Promise((r) => setTimeout(r, 10));

    input.value = 'docker';
    assert.doesNotThrow(
      () => input.dispatchEvent(new MockEvent('input')),
      'Non-array tags/categories crashed search.js with TypeError',
    );
    const links = resultsEl.querySelectorAll('a');
    for (const a of links) {
      assert.ok(!a.href.endsWith('/undefined'), `Broken link emitted for missing slug/id: ${a.href}`);
    }
  },
);

// ============================================================================
// VECTOR 2: Client State, LocalStorage Attacks, Storage Errors & Concurrency
// ============================================================================

await test(
  'T11',
  'Storage Failure Resilience',
  'Anti-FOUC, root redirect, 404, offline.html, and actions.js init MUST survive localStorage SecurityError/QuotaExceededError',
  () => {
    const pages = [
      { name: 'Layout anti-FOUC (dist/vi/index.html)', file: 'dist/vi/index.html', match: 'techtips_theme' },
      { name: 'Root redirect (dist/index.html)', file: 'dist/index.html', match: 'techtips_lang' },
      { name: '404 locale script (dist/404.html)', file: 'dist/404.html', match: 'error-title' },
      { name: 'Offline script (public/offline.html)', file: 'public/offline.html', match: 'offline-title' },
    ];
    for (const p of pages) {
      const html = fs.readFileSync(path.join(ROOT, p.file), 'utf8');
      const scripts = extractInlineScripts(html).filter((s) => s.includes(p.match));
      assert.ok(scripts.length >= 1, `Expected inline script in ${p.file}`);
      const sb = createBrowserSandbox({ lang: 'vi', throwStorage: true });
      for (const s of scripts) {
        assert.doesNotThrow(() => sb.runScript(s, p.name), `${p.name} threw when localStorage is blocked`);
      }
    }
    const sbActions = createBrowserSandbox({ lang: 'vi', throwStorage: true });
    assert.doesNotThrow(() => sbActions.runFile('public/js/actions.js'), 'actions.js init threw when localStorage is blocked');
  },
);

await test(
  'T12a',
  'Storage/Cookie Crash',
  'public/js/actions.js MUST survive document.cookie SecurityError when clicking language switcher',
  () => {
    const sb = createBrowserSandbox({ lang: 'vi', throwStorage: true, throwCookie: true });
    const langLink = sb.doc.createElement('a');
    langLink.setAttribute('data-set-lang', 'en');
    sb.doc.body.appendChild(langLink);
    sb.runFile('public/js/actions.js');

    assert.doesNotThrow(
      () => langLink.click(),
      'public/js/actions.js:227 throws uncaught SecurityError when document.cookie write is blocked!',
    );
  },
);

await test(
  'T12b',
  'DOM Event Target Crash',
  'public/js/actions.js MUST NOT crash when click event target is a Text node (no .closest method)',
  () => {
    const sb = createBrowserSandbox({ lang: 'vi' });
    sb.runFile('public/js/actions.js');

    const textNode = sb.doc.createTextNode('hello');
    sb.doc.body.appendChild(textNode);
    assert.doesNotThrow(
      () => textNode.dispatchEvent(new MockEvent('click', { bubbles: true, target: textNode })),
      'public/js/actions.js:207 throws TypeError when click event target is a Text node without .closest()!',
    );
  },
);

await test(
  'T13a',
  'LocalStorage Hygiene',
  'public/js/actions.js MUST sanitize non-string/empty localStorage entries in techtips_saved',
  () => {
    const sbDirty = createBrowserSandbox({
      lang: 'en',
      initialStorage: {
        techtips_saved: JSON.stringify([null, 123, { __proto__: { x: 1 } }, '', '   ', 'keep-me']),
      },
    });
    const btn = sbDirty.doc.createElement('button');
    btn.className = 'bookmark-btn';
    btn.setAttribute('data-id', 'new-tip');
    sbDirty.doc.body.appendChild(btn);
    sbDirty.runFile('public/js/actions.js');
    btn.click();

    const storedAfter = JSON.parse(sbDirty.localStorage.getItem('techtips_saved'));
    assert.ok(
      storedAfter.every((x) => typeof x === 'string' && x.trim().length > 0),
      `public/js/actions.js:42-49 preserved garbage non-string/empty entries in techtips_saved: ${JSON.stringify(storedAfter)}`,
    );
  },
);

await test(
  'T13b',
  'Silent Storage Failure',
  'public/js/actions.js MUST NOT display a success toast when bookmark save fails with QuotaExceededError',
  () => {
    const sbFull = createBrowserSandbox({ lang: 'en', throwStorage: true });
    const btn2 = sbFull.doc.createElement('button');
    btn2.className = 'bookmark-btn';
    btn2.setAttribute('data-id', 'tip-fail-save');
    sbFull.doc.body.appendChild(btn2);
    sbFull.runFile('public/js/actions.js');
    btn2.click();

    const toast = sbFull.doc.getElementById('techtips-toast');
    if (toast) {
      assert.notEqual(
        toast.getAttribute('role'),
        'status',
        `public/js/actions.js:240-249 showed false-positive success toast "${toast.textContent}" despite QuotaExceededError on localStorage.setItem!`,
      );
    }
  },
);

function createSavedPageHarness(options = {}) {
  const savedHtml = fs.readFileSync(path.join(DIST_DIR, 'vi/saved/index.html'), 'utf8');
  const savedScript = extractInlineScripts(savedHtml).find((s) => s.includes('handleImportFile'));
  assert.ok(savedScript, 'Could not find SavedPage inline script');

  const toasts = [];
  const sb = createBrowserSandbox({ lang: 'vi', pathname: '/vi/saved', ...options });
  sb.win.TechTipsActions = {
    showToast(msg, variant) {
      toasts.push({ msg, variant });
    },
    updateCardsUI() {},
  };

  for (const [id, tag] of [
    ['saved-stream', 'div'],
    ['saved-empty-state', 'div'],
    ['saved-no-match', 'div'],
    ['saved-counter', 'p'],
    ['saved-search-wrap', 'div'],
    ['saved-search-input', 'input'],
    ['saved-stale-banner', 'div'],
    ['saved-stale-text', 'span'],
    ['clean-stale-btn', 'button'],
    ['export-bookmarks-btn', 'button'],
    ['import-bookmarks-btn', 'button'],
    ['import-bookmarks-input', 'input'],
  ]) {
    const el = sb.doc.createElement(tag);
    el.id = id;
    sb.doc.body.appendChild(el);
  }

  sb.runScript(savedScript, 'SavedPage.inline.js');
  return { sb, toasts };
}

async function triggerImport(sb, content, overrideSize) {
  const input = sb.doc.getElementById('import-bookmarks-input');
  const raw = typeof content === 'string' ? content : JSON.stringify(content);
  const file = {
    size: overrideSize !== undefined ? overrideSize : Buffer.byteLength(raw, 'utf8'),
    async text() {
      return raw;
    },
  };
  input.files = [file];
  input.dispatchEvent(new MockEvent('change', { target: input }));
  await new Promise((r) => setTimeout(r, 25));
}

await test(
  'T14',
  'Import Fuzzing',
  'SavedPage.astro MUST reject corrupted JSON, non-object roots, version: 2, wrong field types, and > 5MB files',
  async () => {
    const { sb, toasts } = createSavedPageHarness({
      initialStorage: { techtips_saved: JSON.stringify(['orig-1']) },
      fetchImpl: async () => new Response('[]', { status: 200 }),
    });
    await new Promise((r) => setTimeout(r, 20));

    const badPayloads = [
      { label: 'broken JSON', content: '{not-valid-json' },
      { label: 'array root', content: JSON.stringify(['a', 'b']) },
      { label: 'primitive root', content: '12345' },
      { label: 'null root', content: 'null' },
      { label: 'version 2', content: JSON.stringify({ version: 2, saved: ['x'] }) },
      { label: 'missing saved & read', content: JSON.stringify({ version: 1, other: [] }) },
      { label: 'non-array saved', content: JSON.stringify({ version: 1, saved: 'not-array' }) },
      { label: 'non-array read', content: JSON.stringify({ version: 1, read: { a: 1 } }) },
      { label: '> 5MB file', content: '{"version":1,"saved":["x"]}', size: 5 * 1024 * 1024 + 1 },
    ];

    for (const bp of badPayloads) {
      const before = toasts.length;
      await triggerImport(sb, bp.content, bp.size);
      assert.ok(toasts.length > before, `Expected error toast for ${bp.label}`);
      assert.equal(toasts[toasts.length - 1].variant, 'error', `Expected error variant toast for ${bp.label}`);
      assert.deepEqual(JSON.parse(sb.localStorage.getItem('techtips_saved')), ['orig-1']);
    }
  },
);

await test(
  'T15',
  'Prototype Pollution & Sanitization',
  'SavedPage.astro import MUST NOT pollute Object.prototype and MUST strip empty/whitespace/oversized/non-string/duplicate IDs',
  async () => {
    const { sb } = createSavedPageHarness({
      fetchImpl: async () => new Response('[]', { status: 200 }),
    });
    await new Promise((r) => setTimeout(r, 20));

    const hostileJson =
      '{"version":1,"__proto__":{"redteam_polluted":true},"constructor":{"prototype":{"redteam_polluted2":true}},"saved":["","   ","  tip-clean  ","tip-clean",123,null,false,{},"' +
      'x'.repeat(200) +
      '","__proto__"]}';
    await triggerImport(sb, hostileJson);

    assert.equal(({}).redteam_polluted, undefined, 'Object.prototype must not be polluted');
    assert.equal(({}).redteam_polluted2, undefined, 'Object.prototype must not be polluted via constructor');
    const saved = JSON.parse(sb.localStorage.getItem('techtips_saved'));
    assert.ok(saved.includes('tip-clean'));
    assert.ok(!saved.includes(''), 'Empty ID must be rejected');
    assert.ok(!saved.includes('   '), 'Whitespace ID must be rejected');
    assert.ok(!saved.includes('x'.repeat(200)), 'Oversized >128 char ID must be rejected');
    assert.equal(saved.filter((x) => x === 'tip-clean').length, 1, 'Duplicates must be deduplicated');
  },
);

await test(
  'T16',
  'Resource Exhaustion / DoS',
  'SavedPage.astro import MUST cap merged saved IDs instead of accepting unbounded 10,000+ entries',
  async () => {
    const { sb } = createSavedPageHarness({
      fetchImpl: async () => new Response('[]', { status: 200 }),
    });
    await new Promise((r) => setTimeout(r, 20));

    const hugeSaved = Array.from({ length: 10000 }, (_, i) => `fake-id-${i}`);
    const payload = JSON.stringify({ version: 1, saved: hugeSaved, read: hugeSaved });
    assert.ok(Buffer.byteLength(payload, 'utf8') < 5 * 1024 * 1024, 'Payload is under 5MB byte cap');

    await triggerImport(sb, payload);

    const storedRead = JSON.parse(sb.localStorage.getItem('techtips_read'));
    const storedSaved = JSON.parse(sb.localStorage.getItem('techtips_saved'));
    assert.ok(storedRead.length <= 500, 'read list is capped at 500');
    assert.ok(
      storedSaved.length <= 2000,
      `SavedPage.astro:443 accepted all ${storedSaved.length} imported saved IDs with ZERO cap (localStorage bloat & O(N*M) UI lag DoS)!`,
    );
  },
);

await test(
  'T17',
  'Stale Cleanup & Storage Throw',
  'SavedPage.astro MUST detect/clean stale IDs AND survive localStorage SecurityError during cleanStaleBookmarks()',
  async () => {
    let blockWrites = false;
    const { sb } = createSavedPageHarness({
      initialStorage: { techtips_saved: JSON.stringify(['live-1', 'stale-dead-1', 'stale-dead-2']) },
      fetchImpl: async () =>
        new Response(
          JSON.stringify([
            {
              id: 'live-1',
              slug: 'live-1',
              title: { vi: 'Live Tip' },
              summary: { vi: 'Still here' },
              source: { id: 's', name: 'Src' },
              categories: ['dev'],
              tags: [],
            },
          ]),
          { status: 200 },
        ),
    });
    await new Promise((r) => setTimeout(r, 25));

    const staleBanner = sb.doc.getElementById('saved-stale-banner');
    assert.ok(!staleBanner.classList.contains('hidden'), 'Stale banner must be visible for 2 stale IDs');

    // Now make localStorage.setItem throw QuotaExceededError/SecurityError right before clicking Clean!
    const origSet = sb.localStorage.setItem;
    sb.localStorage.setItem = (...args) => {
      if (blockWrites) throw new DOMException('SecurityError: storage read-only', 'SecurityError');
      return origSet.apply(sb.localStorage, args);
    };
    blockWrites = true;

    const cleanBtn = sb.doc.getElementById('clean-stale-btn');
    assert.doesNotThrow(
      () => cleanBtn.click(),
      'SavedPage.astro:366 cleanStaleBookmarks() calls setStoredIds() without try/catch and throws uncaught SecurityError!',
    );
  },
);

await test(
  'T18',
  'Concurrency Race Condition',
  'SavedPage.astro concurrent renderSaved() calls while fetch is pending MUST NOT render duplicate tip cards',
  async () => {
    const resolvers = [];
    const { sb } = createSavedPageHarness({
      initialStorage: { techtips_saved: JSON.stringify(['race-1']) },
      fetchImpl: () =>
        new Promise((res) => {
          resolvers.push(res);
        }),
    });

    // While initial renderSaved() is awaiting loadTips(), trigger a second renderSaved() via search input
    const searchInput = sb.doc.getElementById('saved-search-input');
    searchInput.value = 'Race';
    searchInput.dispatchEvent(new MockEvent('input'));

    const payloadStr = JSON.stringify([
      {
        id: 'race-1',
        slug: 'race-1',
        title: { vi: 'Race Condition Tip' },
        summary: { vi: 'Details' },
        source: { id: 's', name: 'Src' },
        categories: ['dev'],
        tags: [],
      },
    ]);
    for (const resolve of resolvers) {
      resolve(new Response(payloadStr, { status: 200 }));
    }
    await new Promise((r) => setTimeout(r, 30));

    const cards = sb.doc.getElementById('saved-stream').querySelectorAll('article');
    assert.equal(
      cards.length,
      1,
      `SavedPage.astro:290-358 async race rendered ${cards.length} duplicate cards instead of 1 (stream cleared before await loadTips() with no renderToken or loadPromise dedupe)!`,
    );
  },
);

await test(
  'T19',
  'Event Listener Leak',
  'public/js/search.js MUST NOT stack duplicate document keydown listeners across astro:page-load re-inits',
  () => {
    const sb = createBrowserSandbox({ lang: 'vi', fetchImpl: async () => new Response('[]', { status: 200 }) });

    function mountModal() {
      sb.doc.body.replaceChildren();
      const modal = sb.doc.createElement('div');
      modal.id = 'search-modal';
      modal.className = 'hidden';
      const input = sb.doc.createElement('input');
      input.id = 'search-input';
      const resultsEl = sb.doc.createElement('div');
      resultsEl.id = 'search-results';
      modal.append(input, resultsEl);
      sb.doc.body.appendChild(modal);
    }

    mountModal();
    sb.runFile('public/js/search.js');
    const countAfterFirst = (sb.doc._listeners.get('keydown:0') || []).length;

    // Simulate 3 Astro client-side page navigations replacing the DOM
    for (let i = 0; i < 3; i++) {
      mountModal();
      sb.doc.dispatchEvent(new MockEvent('astro:page-load'));
    }
    const countAfterNavs = (sb.doc._listeners.get('keydown:0') || []).length;
    assert.equal(
      countAfterNavs,
      countAfterFirst,
      `public/js/search.js:295 leaked ${countAfterNavs - countAfterFirst} duplicate document keydown listeners on astro:page-load!`,
    );
  },
);

// ============================================================================
// VECTOR 3: Query Param Parsing, Silent Failure Traps & Routing Edge Cases
// ============================================================================

function createHomeFeedHarness(search) {
  const homeHtml = fs.readFileSync(path.join(DIST_DIR, 'vi/index.html'), 'utf8');
  const homeScript = extractInlineScripts(homeHtml).find((s) => s.includes('ITEMS_PER_PAGE'));
  assert.ok(homeScript, 'Could not find HomeFeedPage inline script');

  let fetchCalls = 0;
  const sb = createBrowserSandbox({
    lang: 'vi',
    pathname: '/vi',
    search,
    fetchImpl: async () => {
      fetchCalls++;
      return new Response(
        JSON.stringify([
          {
            id: 'tip-1',
            slug: 'tip-1',
            url: 'https://example.com/1',
            title: { vi: 'Thủ thuật Windows 11', en: 'Windows 11 Tip' },
            summary: { vi: 'Tóm tắt hữu ích', en: 'Useful summary' },
            source: { id: 'genk', name: 'GenK', content_type: 'article', kind: 'tips' },
            categories: ['windows'],
            tags: ['win11'],
            difficulty: 'easy',
            original_lang: 'vi',
            published_at: '2026-11-20T10:00:00Z',
            fetched_at: '2026-11-20T10:05:00Z',
            score: 80,
          },
        ]),
        { status: 200 },
      );
    },
  });

  // Mount required DOM nodes matching HomeFeedPage.astro
  const makeSelect = (id, values) => {
    const sel = sb.doc.createElement('select');
    sel.id = id;
    sel.value = 'all';
    sel.options = values.map((v) => ({ value: v }));
    return sel;
  };
  for (const [id, tag] of [
    ['tips-stream', 'div'],
    ['empty-stream-msg', 'div'],
    ['reset-filter-btn', 'button'],
    ['static-pagination', 'div'],
    ['dynamic-pagination', 'nav'],
    ['active-query-bar', 'div'],
    ['active-query-value', 'strong'],
    ['clear-query-btn', 'button'],
    ['mobile-search-input', 'input'],
    ['page-prev-btn', 'button'],
    ['page-next-btn', 'button'],
    ['page-numbers', 'div'],
    ['pagination-subtext', 'div'],
  ]) {
    const el = sb.doc.createElement(tag);
    el.id = id;
    sb.doc.body.appendChild(el);
  }
  sb.doc.body.appendChild(makeSelect('source-filter', ['all', 'community', 'genk']));
  sb.doc.body.appendChild(makeSelect('content-type-filter', ['all', 'article', 'community', 'video', 'vendor']));
  sb.doc.body.appendChild(makeSelect('language-filter', ['all', 'vi', 'en', 'zh-CN']));

  for (const cat of ['all', 'windows', 'macos', 'linux', 'android', 'ios', 'security', 'dev', 'hardware', 'browser', 'office', 'ai']) {
    const b = sb.doc.createElement('button');
    b.className = 'desktop-cat-btn';
    b.setAttribute('data-category', cat);
    sb.doc.body.appendChild(b);
  }
  for (const diff of ['all', 'easy', 'medium', 'advanced']) {
    const b = sb.doc.createElement('button');
    b.className = 'diff-pill-btn';
    b.setAttribute('data-diff', diff);
    sb.doc.body.appendChild(b);
  }
  for (const sort of ['best', 'newest']) {
    const b = sb.doc.createElement('button');
    b.className = 'sort-pill-btn';
    b.setAttribute('data-sort', sort);
    sb.doc.body.appendChild(b);
  }

  sb.runFile('public/js/tip-card.js');
  sb.runScript(homeScript, 'HomeFeedPage.inline.js');
  return { sb, getFetchCalls: () => fetchCalls };
}

await test(
  'T20',
  'Query Param Fuzzing',
  'HomeFeedPage.astro MUST validate ?cat= against known categories (rejecting ?cat=__proto__ / ?cat=<script>...)',
  async () => {
    const { sb } = createHomeFeedHarness('?cat=__proto__&page=-5&sort=evil&diff=invalid');
    await new Promise((r) => setTimeout(r, 25));

    const emptyMsg = sb.doc.getElementById('empty-stream-msg');
    const urlAfter = sb.win.location.search;
    assert.ok(
      !urlAfter.includes('cat=__proto__'),
      `HomeFeedPage.astro:805 accepted unvalidated ?cat=__proto__ without checking valid categories! URL stayed "${urlAfter}", empty-state hidden=${emptyMsg.classList.contains('hidden')}`,
    );
  },
);

await test(
  'T21',
  'Query Param Fuzzing',
  'HomeFeedPage.astro MUST render ?q=<script>alert(1)</script>&page=999999 safely without XSS and clamp huge page numbers',
  async () => {
    const { sb } = createHomeFeedHarness('?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E&page=999999&sort=evil&diff=invalid');
    await new Promise((r) => setTimeout(r, 25));

    const queryVal = sb.doc.getElementById('active-query-value');
    assert.equal(queryVal.textContent, '<script>alert(1)</script>');
    assert.equal(queryVal.querySelectorAll('script').length, 0, 'Query chip must not interpret HTML');
    assert.ok(!sb.win.location.search.includes('page=999999'), 'Out-of-bounds page must be clamped back to 1');
    assert.ok(!sb.win.location.search.includes('sort=evil'), 'Invalid sort must be dropped');
    assert.ok(!sb.win.location.search.includes('diff=invalid'), 'Invalid diff must be dropped');
  },
);

function setupNewsFeedDom(sb) {
  const makeSelect = (id, values) => {
    const sel = sb.doc.createElement('select');
    sel.id = id;
    sel.value = 'all';
    sel.options = values.map((v) => ({ value: v }));
    return sel;
  };
  sb.doc.body.appendChild(makeSelect('news-source', ['all', 'tinhte']));
  sb.doc.body.appendChild(makeSelect('news-type', ['all', 'article']));
  sb.doc.body.appendChild(makeSelect('news-category', ['all', 'ai']));
  sb.doc.body.appendChild(makeSelect('news-language', ['all', 'vi', 'en']));
  for (const [id, tag] of [
    ['news-search', 'input'],
    ['news-stream', 'div'],
    ['news-count', 'p'],
    ['news-empty', 'div'],
    ['news-reset', 'button'],
    ['news-prev', 'button'],
    ['news-next', 'button'],
    ['news-page', 'span'],
    ['news-pagination', 'nav'],
  ]) {
    const el = sb.doc.createElement(tag);
    el.id = id;
    sb.doc.body.appendChild(el);
  }
}

await test(
  'T22a',
  'Silent Failure Traps',
  'NewsFeed.astro MUST handle API HTTP 500 without UnhandledPromiseRejection',
  async () => {
    const newsHtml = fs.readFileSync(path.join(DIST_DIR, 'vi/news/index.html'), 'utf8');
    const newsScript = extractInlineScripts(newsHtml).find((s) => s.includes('news-stream'));
    assert.ok(newsScript, 'Could not find NewsFeed inline script');

    const unhandled = [];
    const onUnhandled = (reason) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    try {
      const sb = createBrowserSandbox({
        lang: 'vi',
        pathname: '/vi/news',
        search: '?q=ai&page=-5&sort=evil',
        fetchImpl: async () => new Response('Server Error', { status: 500 }),
      });
      setupNewsFeedDom(sb);
      sb.runScript(newsScript, 'NewsFeed.inline.js');
      await new Promise((r) => setTimeout(r, 30));

      assert.equal(
        unhandled.length,
        0,
        `NewsFeed.astro caused ${unhandled.length} UnhandledPromiseRejection(s) on API 500 (missing .catch() on load().then(...) calls at lines 274,280,288,301,307,313,358)!`,
      );
    } finally {
      process.off('unhandledRejection', onUnhandled);
    }
  },
);

await test(
  'T22b',
  'Silent Failure Traps',
  'NewsFeed.astro MUST guard against missing window.TipCardRenderer (partial network drop of /js/tip-card.js)',
  async () => {
    const newsHtml = fs.readFileSync(path.join(DIST_DIR, 'vi/news/index.html'), 'utf8');
    const newsScript = extractInlineScripts(newsHtml).find((s) => s.includes('news-stream'));
    assert.ok(newsScript, 'Could not find NewsFeed inline script');

    const unhandled = [];
    const onUnhandled = (reason) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    try {
      const sbNoRenderer = createBrowserSandbox({
        lang: 'vi',
        pathname: '/vi/news',
        search: '?q=ai',
        fetchImpl: async () =>
          new Response(
            JSON.stringify([
              {
                id: 'n1',
                slug: 'n1',
                url: 'https://example.com/n1',
                title: { vi: 'AI News' },
                summary: { vi: 'Summary' },
                source: { id: 'tinhte', name: 'Tinhte', kind: 'news', content_type: 'article' },
                categories: ['ai'],
                tags: [],
                original_lang: 'vi',
                published_at: '2026-11-20T10:00:00Z',
                fetched_at: '2026-11-20T10:05:00Z',
                score: 10,
              },
            ]),
            { status: 200 },
          ),
      });
      setupNewsFeedDom(sbNoRenderer);
      sbNoRenderer.runScript(newsScript, 'NewsFeed.no-renderer.js');
      await new Promise((r) => setTimeout(r, 30));

      assert.equal(
        unhandled.length,
        0,
        `NewsFeed.astro:255 crashed with TypeError when window.TipCardRenderer was undefined: ${unhandled[0]}`,
      );
    } finally {
      process.off('unhandledRejection', onUnhandled);
    }
  },
);

await test(
  'T23a',
  'Fallback Edge Case',
  'TipDetailPage.astro related tips title MUST fall back to Object.values(r.title)[0] when lang & en are absent',
  () => {
    const detailSrc = fs.readFileSync(path.join(ROOT, 'src/components/pages/TipDetailPage.astro'), 'utf8');
    assert.ok(
      !/\{r\.title\[lang\]\s*\|\|\s*r\.title\['en'\]\}/.test(detailSrc),
      'TipDetailPage.astro:414 renders {r.title[lang] || r.title[\'en\']} without Object.values(r.title)[0] fallback!',
    );
  },
);

await test(
  'T23b',
  'Malformed Date Trap',
  'src/pages/{vi,en}/rss.xml.ts MUST guard against invalid dates instead of emitting <pubDate>Invalid Date</pubDate>',
  () => {
    for (const rssFile of ['src/pages/vi/rss.xml.ts', 'src/pages/en/rss.xml.ts']) {
      const rssSrc = fs.readFileSync(path.join(ROOT, rssFile), 'utf8');
      assert.ok(
        !/const pubDate = new Date\(tip\.published_at \|\| tip\.fetched_at\)\.toUTCString\(\);/.test(rssSrc),
        `${rssFile}:20 calls .toUTCString() without checking Number.isNaN(date.getTime()), risking <pubDate>Invalid Date</pubDate>!`,
      );
    }
  },
);

await test(
  'T24',
  '404 Routing & Localization',
  'dist/404.html MUST localize to English on /en/* paths AND Layout VI button on /404 MUST link to /vi (not loop to /404)',
  () => {
    const html404 = fs.readFileSync(path.join(DIST_DIR, '404.html'), 'utf8');
    const script404 = extractInlineScripts(html404).find((s) => s.includes('error-title'));
    assert.ok(script404, '404 localization script should exist');

    const sb = createBrowserSandbox({ lang: 'vi', pathname: '/en/nonexistent' });
    for (const [id, tag] of [
      ['error-title', 'h1'],
      ['error-desc', 'p'],
      ['error-hint-prefix', 'span'],
      ['error-hint-suffix', 'span'],
      ['error-home-link', 'a'],
      ['error-home-text', 'span'],
    ]) {
      const el = sb.doc.createElement(tag);
      el.id = id;
      sb.doc.body.appendChild(el);
    }
    sb.runScript(script404, '404.inline.js');
    assert.equal(sb.doc.documentElement.lang, 'en');
    assert.equal(sb.doc.getElementById('error-home-link').getAttribute('href'), '/en');

    // Check VI language switcher button in dist/404.html does not point to /404
    const viBtnMatch = html404.match(/<a[^>]*data-set-lang="vi"[^>]*>/i);
    assert.ok(viBtnMatch, 'VI language switcher must exist on 404.html');
    const viHref = (viBtnMatch[0].match(/href="([^"]+)"/i) || [])[1];
    assert.equal(
      viHref,
      '/vi',
      `Layout.astro:236 links the VI button on 404.html to "${viHref}" instead of "/vi"!`,
    );
  },
);

// ============================================================================
// VECTOR 4: Built dist/ SEO, Output Integrity, Guardrails & SSR/CSR Parity
// ============================================================================

const allDistFiles = walkFiles(DIST_DIR);
const allDistHtml = allDistFiles.filter((f) => f.endsWith('.html'));
const allDistXml = allDistFiles.filter((f) => f.endsWith('.xml'));

await test(
  'T25',
  'SEO Contract',
  'EVERY built dist/ HTML page with hreflang="x-default" MUST point to exact /vi/... counterpart',
  () => {
    const bad = [];
    for (const file of allDistHtml) {
      const html = fs.readFileSync(file, 'utf8');
      const xDef = html.match(/<link[^>]*hreflang="x-default"[^>]*>/i);
      if (!xDef) continue;
      const href = (xDef[0].match(/href="([^"]+)"/i) || [])[1] || '';
      const canonTag = html.match(/<link[^>]*rel="canonical"[^>]*>/i);
      const canon = canonTag ? (canonTag[0].match(/href="([^"]+)"/i) || [])[1] || '' : '';
      const expected = canon.replace(/\/en(\/|$)/, '/vi$1');
      if (!href.startsWith('https://') || href !== expected) {
        bad.push(`${path.relative(DIST_DIR, file)}: got "${href}", expected "${expected}"`);
      }
    }
    assert.equal(bad.length, 0, `Invalid hreflang="x-default": ${bad.slice(0, 5).join('; ')}`);
  },
);

await test(
  'T26',
  'SEO Contract',
  'EVERY <link rel="prev"> and <link rel="next"> in dist/ MUST be an absolute https:// URL',
  () => {
    let checked = 0;
    const bad = [];
    for (const file of allDistHtml) {
      const html = fs.readFileSync(file, 'utf8');
      for (const m of html.matchAll(/<link[^>]*rel="(prev|next)"[^>]*>/gi)) {
        checked++;
        const href = (m[0].match(/href="([^"]+)"/i) || [])[1] || '';
        if (!href.startsWith('https://')) {
          bad.push(`${path.relative(DIST_DIR, file)}: ${m[0]}`);
        }
      }
    }
    assert.ok(checked > 0, 'Expected at least one paginated rel=prev/next link in dist/');
    assert.equal(bad.length, 0, `Non-absolute rel=prev/next URLs: ${bad.slice(0, 5).join('; ')}`);
  },
);

await test(
  'T27',
  'SEO Contract',
  'EVERY <script type="application/ld+json"> across home, category, news, and tip pages in dist/ MUST be valid JSON-LD',
  () => {
    const sampleFiles = [
      path.join(DIST_DIR, 'vi/index.html'),
      path.join(DIST_DIR, 'en/index.html'),
      path.join(DIST_DIR, 'vi/news/index.html'),
      path.join(DIST_DIR, 'en/news/index.html'),
      ...allDistHtml.filter((f) => /[\\/](vi|en)[\\/]category[\\/]/.test(f)),
      ...allDistHtml.filter((f) => /[\\/](vi|en)[\\/]tip[\\/]/.test(f)).slice(0, 60),
    ];
    let parsedCount = 0;
    const errors = [];
    for (const file of sampleFiles) {
      if (!fs.existsSync(file)) continue;
      const html = fs.readFileSync(file, 'utf8');
      for (const m of html.matchAll(/<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi)) {
        try {
          const obj = JSON.parse(m[1]);
          assert.equal(obj['@context'], 'https://schema.org');
          assert.ok(typeof obj['@type'] === 'string' && obj['@type'].length > 0);
          parsedCount++;
        } catch (err) {
          errors.push(`${path.relative(DIST_DIR, file)}: ${err.message}`);
        }
      }
    }
    assert.ok(parsedCount >= 20, `Expected >=20 JSON-LD blocks, found ${parsedCount}`);
    assert.equal(errors.length, 0, `Invalid JSON-LD blocks: ${errors.slice(0, 5).join('; ')}`);
  },
);

await test(
  'T28',
  'Output Integrity',
  'ZERO "Invalid Date", "[object Object]", or rendered "undefined" tokens across ALL dist/ HTML & XML files',
  () => {
    const bad = [];
    for (const file of allDistHtml) {
      const html = fs.readFileSync(file, 'utf8');
      const visible = html
        .replace(/<script[\s\S]*?<\/script>/gi, '')
        .replace(/<style[\s\S]*?<\/style>/gi, '');
      if (/\bInvalid Date\b/.test(visible) || /\[object Object\]/.test(visible) || />undefined</.test(visible) || /href="[^"]*undefined/.test(visible)) {
        bad.push(path.relative(DIST_DIR, file));
      }
    }
    for (const file of allDistXml) {
      const xml = fs.readFileSync(file, 'utf8');
      if (/\bInvalid Date\b/.test(xml) || /\[object Object\]/.test(xml)) {
        bad.push(path.relative(DIST_DIR, file));
      }
    }
    assert.equal(bad.length, 0, `Corrupted rendered values in dist/: ${bad.slice(0, 10).join(', ')}`);
  },
);

await test(
  'T29',
  'Link Hygiene',
  'ZERO raw RSS/Atom/API URLs in external links on /vi/sources and /en/sources',
  () => {
    const bad = [];
    for (const rel of ['vi/sources/index.html', 'en/sources/index.html']) {
      const html = fs.readFileSync(path.join(DIST_DIR, rel), 'utf8');
      for (const m of html.matchAll(/<a[^>]*target="_blank"[^>]*href="([^"]+)"[^>]*>|<a[^>]*href="([^"]+)"[^>]*target="_blank"[^>]*>/gi)) {
        const href = m[1] || m[2] || '';
        if (/(\/rss\b|\.rss\b|\.xml\b|\/feed\b|\/feeds\/|api\.stackexchange|hn\.algolia)/i.test(href)) {
          bad.push(`${rel}: ${href}`);
        }
      }
    }
    assert.equal(bad.length, 0, `Raw feed/API URLs leaked onto sources page: ${bad.join(', ')}`);
  },
);

await test(
  'T30',
  'UI Guardrails',
  'ZERO emojis in UI source files (src/, public/js/, public/offline.html)',
  () => {
    // True emoji ranges (Supplemental Symbols, Emoticons, Dingbats, Misc Symbols, Variation Selector-16)
    const strictEmojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u;
    const files = [...walkFiles(path.join(ROOT, 'src')), ...walkFiles(path.join(ROOT, 'public/js')), path.join(ROOT, 'public/offline.html')];
    const hits = [];
    for (const file of files) {
      const content = fs.readFileSync(file, 'utf8');
      const lines = content.split(/\r?\n/);
      lines.forEach((line, idx) => {
        if (strictEmojiRegex.test(line)) {
          hits.push(`${path.relative(ROOT, file)}:${idx + 1} -> ${line.trim().slice(0, 80)}`);
        }
      });
    }
    assert.equal(hits.length, 0, `Emojis found in UI files: ${hits.join('; ')}`);
  },
);

await test(
  'T31',
  'Security & Privacy Hygiene',
  'ZERO inline onerror= attributes AND ZERO tips-admin@users.noreply.github.com anywhere in dist/',
  () => {
    const onerrorHits = [];
    const emailHits = [];
    for (const file of allDistFiles) {
      if (!/\.(html|xml|json|js|txt|webmanifest)$/i.test(file)) continue;
      const content = fs.readFileSync(file, 'utf8');
      if (file.endsWith('.html') && /\sonerror\s*=/i.test(content)) {
        onerrorHits.push(path.relative(DIST_DIR, file));
      }
      if (content.includes('tips-admin@users.noreply.github.com')) {
        emailHits.push(path.relative(DIST_DIR, file));
      }
    }
    assert.equal(onerrorHits.length, 0, `Inline onerror= found in: ${onerrorHits.slice(0, 5).join(', ')}`);
    assert.equal(emailHits.length, 0, `Placeholder admin email leaked in: ${emailHits.slice(0, 5).join(', ')}`);
  },
);

await test(
  'T32',
  'Performance / Architecture',
  'SearchModal JS MUST NOT be inlined into dist/{vi,en}/tip/*/index.html (must load /js/search.js)',
  () => {
    const tipPages = allDistHtml.filter((f) => /[\\/](vi|en)[\\/]tip[\\/][^\\/]+[\\/]index\.html$/.test(f));
    assert.ok(tipPages.length > 50, 'Expected tip pages in dist/');
    const bad = [];
    for (const file of tipPages) {
      const html = fs.readFileSync(file, 'utf8');
      if (!html.includes('id="search-modal"')) continue; // skip hex-id redirect stubs
      if (!html.includes('src="/js/search.js"')) {
        bad.push(`${path.relative(DIST_DIR, file)}: missing external /js/search.js`);
      }
      const inlines = extractInlineScripts(html);
      if (inlines.some((s) => s.includes('openTechTipsSearch') || s.includes('buildNormMap'))) {
        bad.push(`${path.relative(DIST_DIR, file)}: SearchModal JS is inlined!`);
      }
    }
    assert.equal(bad.length, 0, `SearchModal JS inline violation: ${bad.slice(0, 5).join('; ')}`);
  },
);

await test(
  'T33',
  'Navigation & Feeds',
  'Built pages MUST link /{vi,en}/submit and /{vi,en}/feed.xml, and RSS feeds MUST be valid XML',
  () => {
    for (const lang of ['vi', 'en']) {
      const homeHtml = fs.readFileSync(path.join(DIST_DIR, `${lang}/index.html`), 'utf8');
      assert.ok(homeHtml.includes(`href="/${lang}/submit"`), `/${lang} must link /${lang}/submit`);
      assert.ok(homeHtml.includes(`href="/${lang}/feed.xml"`), `/${lang} must link /${lang}/feed.xml`);
      assert.ok(fs.existsSync(path.join(DIST_DIR, `${lang}/submit/index.html`)), `/${lang}/submit page must exist`);
      const feedXml = fs.readFileSync(path.join(DIST_DIR, `${lang}/feed.xml`), 'utf8');
      assert.ok(feedXml.startsWith('<?xml version="1.0" encoding="UTF-8"?>'));
      assert.ok(feedXml.includes('<rss version="2.0"'));
      assert.ok(feedXml.includes('</rss>'));
      assert.ok(feedXml.includes(`/${lang}/feed.xml`));
    }
  },
);

await test(
  'T34',
  'SSR vs CSR Parity',
  'TipCard.astro SSR dates MUST match public/js/tip-card.js CSR dates identically (including UTC/GMT+7 boundary timestamps)',
  () => {
    for (const lang of ['vi', 'en']) {
      const sb = createBrowserSandbox({ lang });
      sb.runFile('public/js/tip-card.js');
      const homeHtml = fs.readFileSync(path.join(DIST_DIR, `${lang}/index.html`), 'utf8');
      const apiTips = JSON.parse(fs.readFileSync(path.join(DIST_DIR, `api/tips-${lang}.json`), 'utf8'));
      const byId = new Map(apiTips.map((t) => [t.id, t]));
      const articles = [...homeHtml.matchAll(/<article[^>]*data-tip-id="([^"]+)"[^>]*>([\s\S]*?)<\/article>/g)];
      assert.ok(articles.length >= 10, `Expected SSR cards on /${lang}`);

      for (const [, id, ssrBody] of articles) {
        const tip = byId.get(id);
        assert.ok(tip, `SSR tip ${id} missing from /api/tips-${lang}.json`);
        const csrCard = sb.win.TipCardRenderer.create(tip, lang, DEFAULT_LABELS);
        const metaRow = csrCard.childNodes[0].childNodes[0];
        const metaSpans = metaRow.querySelectorAll('span').map((s) => s.textContent);
        const dateSpan = metaSpans.find((txt) => /^\d{2}\/\d{2}$/.test(txt));
        const updatedSpan = metaSpans.find((txt) => /\d{2}\/\d{2}\s+\d{2}:\d{2}/.test(txt));
        if (dateSpan) {
          assert.ok(
            ssrBody.includes(`>${dateSpan}<`),
            `SSR/CSR published date mismatch on ${lang} tip ${id}: CSR produced "${dateSpan}"`,
          );
        }
        if (updatedSpan) {
          const tsOnly = updatedSpan.match(/\d{2}\/\d{2}\s+\d{2}:\d{2}/)[0];
          assert.ok(
            ssrBody.includes(tsOnly),
            `SSR/CSR updated timestamp mismatch on ${lang} tip ${id}: CSR produced "${tsOnly}"`,
          );
        }
      }

      // Edge-case timezone rollover check: 2026-11-20T17:30:00Z -> 21/11 00:30 in GMT+7 (vi), 20/11 17:30 in UTC (en)
      const edgeCard = sb.win.TipCardRenderer.create(
        {
          id: 'edge-tz',
          slug: 'edge-tz',
          url: 'https://example.com',
          title: { vi: 'TZ', en: 'TZ' },
          summary: { vi: 'TZ', en: 'TZ' },
          source: { id: 's', name: 'Src' },
          categories: ['dev'],
          original_lang: 'en',
          published_at: '2026-11-20T17:30:00Z',
          fetched_at: '2026-11-20T17:30:00Z',
          score: 1,
        },
        lang,
        DEFAULT_LABELS,
      );
      const text = edgeCard.textContent;
      if (lang === 'vi') {
        assert.ok(text.includes('21/11'), `Expected vi GMT+7 rollover 21/11, got ${text}`);
        assert.ok(text.includes('21/11 00:30'), `Expected vi 00:30 (not 24:30), got ${text}`);
      } else {
        assert.ok(text.includes('20/11'), `Expected en UTC 20/11, got ${text}`);
        assert.ok(text.includes('20/11 17:30'), `Expected en 17:30, got ${text}`);
      }
    }
  },
);

// ============================================================================
// VECTOR 5: PWA, Service Worker & WCAG 2.1 AA Contrast Ratios
// ============================================================================

await test(
  'T35',
  'PWA Manifest & Binary PNG Integrity',
  'manifest.webmanifest MUST be valid JSON and PNG icons MUST have valid PNG magic bytes & exact IHDR dimensions (192, 512, 180)',
  () => {
    const manifest = JSON.parse(fs.readFileSync(path.join(DIST_DIR, 'manifest.webmanifest'), 'utf8'));
    assert.ok(Array.isArray(manifest.icons) && manifest.icons.length >= 4);
    for (const icon of manifest.icons) {
      assert.ok(fs.existsSync(path.join(DIST_DIR, icon.src)), `Manifest icon missing from dist/: ${icon.src}`);
    }

    const expectedPngs = [
      { rel: 'icons/icon-192.png', w: 192, h: 192 },
      { rel: 'icons/icon-512.png', w: 512, h: 512 },
      { rel: 'icons/apple-touch-icon.png', w: 180, h: 180 },
    ];
    for (const png of expectedPngs) {
      for (const base of [path.join(ROOT, 'public'), DIST_DIR]) {
        const buf = fs.readFileSync(path.join(base, png.rel));
        assert.equal(buf.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', `Invalid PNG signature: ${png.rel}`);
        assert.equal(buf.subarray(12, 16).toString('ascii'), 'IHDR', `Missing IHDR chunk: ${png.rel}`);
        assert.equal(buf.readUInt32BE(16), png.w, `Width mismatch for ${png.rel}`);
        assert.equal(buf.readUInt32BE(20), png.h, `Height mismatch for ${png.rel}`);
      }
    }
  },
);

await test(
  'T36',
  'PWA Service Worker Runtime',
  'public/sw.js MUST parse cleanly, precache only existing dist/ assets, enforce MAX_DYNAMIC_ENTRIES cap, and serve offline fallbacks',
  async () => {
    const swCode = fs.readFileSync(path.join(ROOT, 'public/sw.js'), 'utf8');
    // Syntax check via vm.Script
    new vm.Script(swCode, { filename: 'public/sw.js' });

    const shellMatch = swCode.match(/SHELL_ASSETS\s*=\s*\[([\s\S]*?)\]/);
    assert.ok(shellMatch, 'SHELL_ASSETS not found in sw.js');
    const shellAssets = [...shellMatch[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
    for (const asset of shellAssets) {
      assert.ok(fs.existsSync(path.join(DIST_DIR, asset)), `Precached SHELL_ASSET missing in dist/: ${asset}`);
    }

    // Simulate ServiceWorkerGlobalScope
    const cacheMap = new Map();
    const openCache = (name) => {
      if (!cacheMap.has(name)) cacheMap.set(name, new Map());
      const entries = cacheMap.get(name);
      return {
        async addAll(urls) {
          for (const u of urls) {
            entries.set(`https://meocongnghe.vercel.app${u}`, new Response(`cached:${u}`, { status: 200 }));
          }
        },
        async put(req, res) {
          const k = typeof req === 'string' ? `https://meocongnghe.vercel.app${req}` : req.url;
          entries.set(k, res);
        },
        async match(req) {
          const k = typeof req === 'string' ? `https://meocongnghe.vercel.app${req}` : req.url;
          return entries.get(k);
        },
        async keys() {
          return Array.from(entries.keys()).map((u) => ({ url: u }));
        },
        async delete(req) {
          return entries.delete(req.url);
        },
      };
    };

    const swListeners = new Map();
    let offlineMode = false;
    const swSelf = {
      location: { origin: 'https://meocongnghe.vercel.app' },
      addEventListener(type, fn) {
        swListeners.set(type, fn);
      },
      skipWaiting: async () => {},
      clients: { claim: async () => {} },
      caches: {
        open: async (name) => openCache(name),
        keys: async () => Array.from(cacheMap.keys()),
        delete: async (name) => cacheMap.delete(name),
      },
      fetch: async (req) => {
        if (offlineMode) throw new Error('Network offline');
        const res = new Response('ok', { status: 200 });
        Object.defineProperty(res, 'type', { value: 'basic' });
        return res;
      },
      URL,
      Response,
      Set,
      Promise,
    };
    swSelf.self = swSelf;

    vm.runInNewContext(swCode, swSelf, { filename: 'public/sw.js' });

    // Run install
    let installWait;
    swListeners.get('install')({
      waitUntil(p) {
        installWait = p;
      },
    });
    await installWait;

    // Push 95 dynamic API responses to verify MAX_DYNAMIC_ENTRIES=80 cap
    for (let i = 0; i < 95; i++) {
      let respPromise;
      swListeners.get('fetch')({
        request: { method: 'GET', url: `https://meocongnghe.vercel.app/api/item-${i}.json`, mode: 'cors' },
        respondWith(p) {
          respPromise = p;
        },
      });
      await respPromise;
      await new Promise((r) => setTimeout(r, 1));
    }

    const activeCache = cacheMap.values().next().value;
    const shellSet = new Set(shellAssets.map((a) => `https://meocongnghe.vercel.app${a}`));
    const dynamicCount = Array.from(activeCache.keys()).filter((k) => !shellSet.has(k)).length;
    assert.ok(dynamicCount <= 80, `Dynamic cache exceeded 80 cap: got ${dynamicCount}`);
    for (const shellUrl of shellSet) {
      assert.ok(activeCache.has(shellUrl), `Shell asset was evicted by trimCache: ${shellUrl}`);
    }

    // Offline API request -> 503 JSON
    offlineMode = true;
    let apiResp;
    swListeners.get('fetch')({
      request: { method: 'GET', url: 'https://meocongnghe.vercel.app/api/uncached.json', mode: 'cors' },
      respondWith(p) {
        apiResp = p;
      },
    });
    const rApi = await apiResp;
    assert.equal(rApi.status, 503);
    assert.deepEqual(await rApi.json(), { error: 'offline' });

    // Offline navigation -> /offline.html
    let navResp;
    swListeners.get('fetch')({
      request: { method: 'GET', url: 'https://meocongnghe.vercel.app/vi/some-uncached-page', mode: 'navigate' },
      respondWith(p) {
        navResp = p;
      },
    });
    const rNav = await navResp;
    assert.equal(await rNav.text(), 'cached:/offline.html');
  },
);

await test(
  'T37',
  'PWA Offline Dead-End & Lifecycle Bug',
  'public/sw.js MUST precache /vi/saved & /en/saved (linked by offline.html) AND track putWithCap via event.waitUntil()',
  () => {
    const offlineHtml = fs.readFileSync(path.join(ROOT, 'public/offline.html'), 'utf8');
    const swCode = fs.readFileSync(path.join(ROOT, 'public/sw.js'), 'utf8');
    const shellMatch = swCode.match(/SHELL_ASSETS\s*=\s*\[([\s\S]*?)\]/);
    const shellAssets = [...shellMatch[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);

    if (offlineHtml.includes('href="/vi/saved"') && offlineHtml.includes("'/en/saved'")) {
      assert.ok(
        shellAssets.includes('/vi/saved') && shellAssets.includes('/en/saved'),
        'public/offline.html directs offline users to /vi/saved & /en/saved, yet public/sw.js SHELL_ASSETS omits both (causing an offline dead-end loop back to /offline.html)!',
      );
    }
    assert.ok(
      swCode.includes('event.waitUntil') && /fetch[\s\S]*waitUntil/.test(swCode),
      'public/sw.js fetch handler fires unawaited putWithCap() without event.waitUntil(), risking cache write truncation when SW idles!',
    );
  },
);

await test(
  'T38',
  'WCAG 2.1 AA Accessibility Contrast',
  'ALL Dark & Light theme token pairs in global.css AND SourcesPage health status text MUST meet WCAG 2.1 AA (>= 4.5:1)',
  () => {
    const css = fs.readFileSync(path.join(ROOT, 'src/styles/global.css'), 'utf8');
    const parseVars = (block) => {
      const vars = {};
      for (const m of block.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
        vars[m[1]] = m[2].trim();
      }
      return vars;
    };
    const darkVars = parseVars(css.match(/:root\s*\{([\s\S]*?)\}/)[1]);
    const lightVars = parseVars(css.match(/\[data-theme="light"\]\s*\{([\s\S]*?)\}/)[1]);

    const failures = [];
    for (const [theme, vars] of [
      ['dark', darkVars],
      ['light', lightVars],
    ]) {
      for (const fg of ['--text-primary', '--text-secondary', '--text-muted', '--accent']) {
        for (const bg of ['--bg-primary', '--bg-surface', '--bg-muted']) {
          const ratio = contrastRatio(hexToRgb(vars[fg]), hexToRgb(vars[bg]));
          if (ratio < 4.5) {
            failures.push(`${theme}: ${fg} (${vars[fg]}) on ${bg} (${vars[bg]}) = ${ratio.toFixed(2)}:1 (< 4.5)`);
          }
        }
      }
      for (const heroFg of ['#0e0f13', '#15110A', '#1c1d22']) {
        const ratio = contrastRatio(hexToRgb(heroFg), hexToRgb(vars['--accent-hero']));
        if (ratio < 4.5) {
          failures.push(`${theme}: ${heroFg} on --accent-hero (${vars['--accent-hero']}) = ${ratio.toFixed(2)}:1 (< 4.5)`);
        }
      }
      const onAccentRatio = contrastRatio(hexToRgb(vars['--on-accent']), hexToRgb(vars['--accent']));
      if (onAccentRatio < 4.5) {
        failures.push(`${theme}: --on-accent on --accent = ${onAccentRatio.toFixed(2)}:1 (< 4.5)`);
      }
      for (const badge of ['easy', 'med', 'adv', 'info', 'hn']) {
        const bgRgb = blendColor(vars[`--badge-${badge}-bg`], vars['--bg-surface']);
        const fgRgb = hexToRgb(vars[`--badge-${badge}-text`]);
        const ratio = contrastRatio(fgRgb, bgRgb);
        if (ratio < 4.5) {
          failures.push(`${theme}: --badge-${badge}-text on --badge-${badge}-bg = ${ratio.toFixed(2)}:1 (< 4.5)`);
        }
      }
    }

    // Check SourcesPage.astro hardcoded Tailwind text-*-500 health colors on Light Mode --bg-surface (#FFFFFF)
    const sourcesSrc = fs.readFileSync(path.join(ROOT, 'src/components/pages/SourcesPage.astro'), 'utf8');
    const tailwindColors = {
      'text-emerald-500': '#10B981',
      'text-amber-500': '#F59E0B',
      'text-red-500': '#EF4444',
    };
    const lightSurfaceRgb = hexToRgb(lightVars['--bg-surface']);
    for (const [cls, hex] of Object.entries(tailwindColors)) {
      if (sourcesSrc.includes(cls)) {
        const ratio = contrastRatio(hexToRgb(hex), lightSurfaceRgb);
        if (ratio < 4.5) {
          failures.push(`light SourcesPage.astro: ${cls} (${hex}) on --bg-surface (${lightVars['--bg-surface']}) = ${ratio.toFixed(2)}:1 (< 4.5)`);
        }
      }
    }

    assert.equal(failures.length, 0, `WCAG 2.1 AA contrast failures:\n  - ${failures.join('\n  - ')}`);
  },
);

// ============================================================================
// Summary
// ============================================================================

const passed = results.filter((r) => r.status === 'PASS').length;
const failed = results.filter((r) => r.status === 'FAIL').length;
console.log(`\n=== RED-TEAM FRONTEND AUDIT SUMMARY: ${passed} passed, ${failed} failed (total ${results.length}) ===`);
if (failed > 0) {
  process.exitCode = 1;
}
