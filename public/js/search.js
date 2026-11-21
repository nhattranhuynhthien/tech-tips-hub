// public/js/search.js
// Global instant search modal controller (loaded once, reads active locale dynamically).

(function () {
  function getLang() {
    return (document.documentElement.getAttribute('lang') || '').toLowerCase() === 'en' ? 'en' : 'vi';
  }

  function strings(lang) {
    return lang === 'en'
      ? {
          placeholder: 'Search tips, shortcuts, terminal, Docker...',
          emptyPrompt: 'Type a query to search handcrafted tips instantly...',
          loading: 'Loading tips index...',
          noMatch: 'No tips matched your query.',
          loadFailed: 'Could not load tips index. Please try again.',
        }
      : {
          placeholder: 'Tìm thủ thuật, phím tắt, terminal, Docker...',
          emptyPrompt: 'Nhập từ khóa để tìm kiếm thủ thuật tức thì...',
          loading: 'Đang tải kho thủ thuật...',
          noMatch: 'Không tìm thấy thủ thuật nào khớp với từ khóa.',
          loadFailed: 'Không tải được dữ liệu tìm kiếm. Vui lòng thử lại.',
        };
  }

  function normalizeSearch(str) {
    return String(str || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/đ/g, 'd');
  }

  function buildNormMap(str) {
    const chars = Array.from(String(str || ''));
    let norm = '';
    const origIndices = [];
    for (let i = 0; i < chars.length; i++) {
      const piece = chars[i]
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/đ/g, 'd');
      for (let j = 0; j < piece.length; j++) {
        norm += piece[j];
        origIndices.push(i);
      }
    }
    return { chars, norm, origIndices };
  }

  function appendHighlightedText(parent, text, rawQuery) {
    const source = String(text || '');
    const qNorm = normalizeSearch(rawQuery).trim();
    if (!qNorm || !source) {
      parent.appendChild(document.createTextNode(source));
      return;
    }

    const { chars, norm, origIndices } = buildNormMap(source);
    let searchFrom = 0;
    let cursor = 0;
    let foundAny = false;

    while (searchFrom < norm.length) {
      const matchPos = norm.indexOf(qNorm, searchFrom);
      if (matchPos === -1) break;
      const startOrig = origIndices[matchPos];
      let endOrig = origIndices[matchPos + qNorm.length - 1] + 1;

      // Keep trailing Unicode combining marks attached to their base character inside <mark>
      while (endOrig < chars.length && /\p{M}/u.test(chars[endOrig])) {
        endOrig++;
      }

      if (startOrig > cursor) {
        parent.appendChild(document.createTextNode(chars.slice(cursor, startOrig).join('')));
      }
      if (endOrig > startOrig) {
        const mark = document.createElement('mark');
        mark.className = 'bg-[var(--accent-bg)] text-[var(--accent)] rounded px-0.5';
        mark.textContent = chars.slice(startOrig, endOrig).join('');
        parent.appendChild(mark);
        cursor = endOrig;
        foundAny = true;
      }
      searchFrom = matchPos + qNorm.length;
    }

    if (!foundAny) {
      parent.appendChild(document.createTextNode(source));
      return;
    }

    if (cursor < chars.length) {
      parent.appendChild(document.createTextNode(chars.slice(cursor).join('')));
    }
  }

  function pickText(field, activeLang, origLang) {
    if (!field || typeof field !== 'object') return '';
    return field[activeLang] || (origLang && field[origLang]) || field.en || Object.values(field)[0] || '';
  }

  function getTipSlugOrId(tip) {
    if (!tip || typeof tip !== 'object') return '';
    if (typeof tip.slug === 'string' && tip.slug.trim()) return tip.slug.trim();
    if (typeof tip.id === 'string' && tip.id.trim()) return tip.id.trim();
    return '';
  }

  function safeStringArray(val) {
    if (!Array.isArray(val)) return [];
    return val.filter((item) => typeof item === 'string');
  }

  function makeStateMessage(text, id) {
    const div = document.createElement('div');
    if (id) div.id = id;
    div.className = 'py-8 text-center text-xs text-[var(--text-muted)] font-mono';
    div.textContent = text;
    return div;
  }

  const tipsByLang = {};
  const loadPromises = {};
  let activeIndex = -1;
  let activeController = null;
  let globalKeydownBound = false;

  function bindGlobalKeydownOnce() {
    if (globalKeydownBound) return;
    globalKeydownBound = true;

    document.addEventListener('keydown', (e) => {
      if (!activeController) return;
      const modal = document.getElementById('search-modal');
      if (!modal) return;

      const activeEl = document.activeElement;
      const inEditable =
        activeEl &&
        (activeEl.tagName === 'INPUT' ||
          activeEl.tagName === 'TEXTAREA' ||
          activeEl.tagName === 'SELECT' ||
          activeEl.isContentEditable);

      if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
        activeController.closeModal();
      } else if (
        modal.classList.contains('hidden') &&
        (((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') || (e.key === '/' && !inEditable))
      ) {
        e.preventDefault();
        activeController.openModal();
      }
    });
  }

  function init() {
    const modal = document.getElementById('search-modal');
    const input = document.getElementById('search-input');
    const resultsContainer = document.getElementById('search-results');
    const openBtn = document.getElementById('open-search-btn');
    const openBtnMobile = document.getElementById('open-search-btn-mobile');
    const closeBtn = document.getElementById('search-close-btn');
    const backdrop = document.getElementById('search-backdrop');

    if (!modal || !input || !resultsContainer || modal.dataset.searchBound === 'true') {
      return;
    }
    modal.dataset.searchBound = 'true';

    function loadTips(lang) {
      if (tipsByLang[lang]) return Promise.resolve(tipsByLang[lang]);
      if (!loadPromises[lang]) {
        loadPromises[lang] = fetch(`/api/all-${lang}.json`)
          .then((resp) => {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
          })
          .then((data) => {
            tipsByLang[lang] = Array.isArray(data) ? data : [];
            if (input.value.trim() && getLang() === lang) {
              renderResults(input.value);
            }
            return tipsByLang[lang];
          })
          .catch((err) => {
            loadPromises[lang] = null;
            console.error('Failed to load tips for search:', err);
            if (getLang() === lang && input.value.trim()) {
              resultsContainer.replaceChildren(makeStateMessage(strings(lang).loadFailed));
            }
            return [];
          });
      }
      return loadPromises[lang];
    }

    function createResultItem(tip, lang, rawQuery) {
      const slugOrId = getTipSlugOrId(tip);
      if (!slugOrId) return null;

      const title = pickText(tip.title, lang, tip.original_lang);
      const summary = pickText(tip.summary, lang, tip.original_lang);
      const sourceName = (tip.source && typeof tip.source.name === 'string' && tip.source.name) || '';
      const cats = safeStringArray(tip.categories);
      const category = cats[0] || 'tips';

      const link = document.createElement('a');
      link.href = `/${lang}/tip/${encodeURIComponent(slugOrId)}`;
      link.setAttribute('data-search-result', 'true');
      link.setAttribute('aria-selected', 'false');
      link.className = 'block p-3 rounded-xl hover:bg-[var(--bg-muted)] transition-colors group';

      const meta = document.createElement('div');
      meta.className = 'flex items-center gap-2 text-[11px] font-mono text-[var(--text-muted)] mb-1';

      const srcSpan = document.createElement('span');
      srcSpan.className = 'text-[var(--text-secondary)]';
      srcSpan.textContent = sourceName;

      const sep = document.createElement('span');
      sep.textContent = '·';

      const catSpan = document.createElement('span');
      catSpan.className = 'text-[var(--accent)] font-semibold';
      catSpan.textContent = `#${category}`;

      meta.append(srcSpan, sep, catSpan);

      const heading = document.createElement('h4');
      heading.className =
        'text-sm font-bold text-[var(--text-primary)] group-hover:text-[var(--accent)] transition-colors leading-snug';
      appendHighlightedText(heading, title, rawQuery);

      const para = document.createElement('p');
      para.className = 'text-xs text-[var(--text-secondary)] line-clamp-1 mt-1';
      para.textContent = summary;

      link.append(meta, heading, para);
      return link;
    }

    function renderResults(rawQuery) {
      const lang = getLang();
      const s = strings(lang);
      const qRaw = String(rawQuery || '').toLowerCase().trim();

      if (!qRaw) {
        resultsContainer.replaceChildren(makeStateMessage(s.emptyPrompt, 'search-empty-state'));
        activeIndex = -1;
        return;
      }

      const cached = tipsByLang[lang];
      if (!cached) {
        resultsContainer.replaceChildren(makeStateMessage(s.loading));
        loadTips(lang);
        return;
      }

      const qNorm = normalizeSearch(qRaw);
      const matches = cached
        .filter((tip) => {
          if (!getTipSlugOrId(tip)) return false;
          const tText = pickText(tip.title, lang, tip.original_lang);
          const origTitle =
            tip.original_lang &&
            tip.title &&
            typeof tip.title[tip.original_lang] === 'string' &&
            tip.title[tip.original_lang] !== tText
              ? tip.title[tip.original_lang]
              : '';
          const sText = pickText(tip.summary, lang, tip.original_lang);
          const cText = safeStringArray(tip.categories).join(' ');
          const tagText = safeStringArray(tip.tags).join(' ');
          const srcText = (tip.source && typeof tip.source.name === 'string' && tip.source.name) || '';
          const combined = `${tText} ${origTitle} ${sText} ${cText} ${tagText} ${srcText}`;
          return (
            combined.toLowerCase().includes(qRaw) ||
            (qNorm.length > 0 && normalizeSearch(combined).includes(qNorm))
          );
        })
        .slice(0, 8);

      if (matches.length === 0) {
        resultsContainer.replaceChildren(makeStateMessage(s.noMatch));
        activeIndex = -1;
        return;
      }

      const frag = document.createDocumentFragment();
      matches.forEach((tip) => {
        const node = createResultItem(tip, lang, rawQuery);
        if (node) frag.appendChild(node);
      });
      resultsContainer.replaceChildren(frag);
      activeIndex = -1;
    }

    function openModal(initialQuery) {
      const lang = getLang();
      const s = strings(lang);
      input.placeholder = s.placeholder;
      modal.classList.remove('hidden');
      document.body.classList.add('overflow-hidden');

      const hasQuery = typeof initialQuery === 'string' && initialQuery.length > 0;
      if (hasQuery) {
        input.value = initialQuery;
        renderResults(initialQuery);
      } else {
        resultsContainer.replaceChildren(makeStateMessage(s.emptyPrompt, 'search-empty-state'));
        loadTips(lang);
      }
      setTimeout(() => input.focus(), 50);
    }

    function closeModal() {
      const s = strings(getLang());
      modal.classList.add('hidden');
      document.body.classList.remove('overflow-hidden');
      input.value = '';
      resultsContainer.replaceChildren(makeStateMessage(s.emptyPrompt, 'search-empty-state'));
      activeIndex = -1;
    }

    function resultLinks() {
      return Array.from(resultsContainer.querySelectorAll('[data-search-result]'));
    }

    function setActive(index) {
      const links = resultLinks();
      if (!links.length) {
        activeIndex = -1;
        return;
      }
      activeIndex = (index + links.length) % links.length;
      links.forEach((link, i) => {
        if (i === activeIndex) {
          link.classList.add('bg-[var(--bg-muted)]');
          link.setAttribute('aria-selected', 'true');
          link.scrollIntoView({ block: 'nearest' });
        } else {
          link.classList.remove('bg-[var(--bg-muted)]');
          link.setAttribute('aria-selected', 'false');
        }
      });
    }

    activeController = { openModal, closeModal };
    window.openTechTipsSearch = openModal;
    bindGlobalKeydownOnce();

    openBtn?.addEventListener('click', () => openModal());
    openBtnMobile?.addEventListener('click', () => openModal());
    closeBtn?.addEventListener('click', closeModal);
    backdrop?.addEventListener('click', closeModal);

    input.addEventListener('keydown', (e) => {
      const links = resultLinks();
      if (!links.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive(activeIndex + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive(activeIndex - 1);
      } else if (e.key === 'Enter' && activeIndex >= 0) {
        e.preventDefault();
        links[activeIndex].click();
      }
    });

    input.addEventListener('input', (e) => {
      renderResults(e.target.value);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('astro:page-load', init);
})();
