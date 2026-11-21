// public/js/tip-card.js
// Shared client-side TipCard renderer matching src/components/TipCard.astro
// and deterministic Asia/Ho_Chi_Minh (vi) / UTC (en) date formatting in src/lib/dates.ts.

(function () {
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function localized(value, lang) {
    if (!value) return '';
    return value[lang] || value.en || Object.values(value)[0] || '';
  }

  function safeExternalUrl(url) {
    if (typeof url !== 'string') return '#';
    const trimmed = url.trim();
    if (!trimmed) return '#';
    try {
      const parsed = new URL(trimmed);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return parsed.toString();
      }
    } catch {}
    return '#';
  }

  function getDateParts(value, lang, options) {
    if (!value) return null;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    try {
      const formatter = new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-US', {
        timeZone: lang === 'vi' ? 'Asia/Ho_Chi_Minh' : 'UTC',
        ...options,
      });
      const parts = {};
      for (const part of formatter.formatToParts(d)) {
        if (part.type !== 'literal') parts[part.type] = part.value;
      }
      if (parts.hour === '24') parts.hour = '00';
      return parts;
    } catch {
      return null;
    }
  }

  function formatDate(value, lang) {
    const parts = getDateParts(value, lang, { day: '2-digit', month: '2-digit' });
    if (!parts || !parts.day || !parts.month) return '';
    return `${parts.day}/${parts.month}`;
  }

  function formatUpdated(value, lang) {
    const parts = getDateParts(value, lang, {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    });
    if (!parts || !parts.day || !parts.month || !parts.hour || !parts.minute) return '';
    return `${parts.day}/${parts.month} ${parts.hour}:${parts.minute}`;
  }

  function createBookmarkIcon() {
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('class', 'bookmark-icon w-3.5 h-3.5');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute('d', 'M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(path);
    return svg;
  }

  function create(tip, lang, labels) {
    const source = tip.source || {};
    const titleText = localized(tip.title, lang);
    const summaryText = localized(tip.summary, lang);
    const isMachineTranslated = !!(tip.translated && tip.translated[lang] === 'machine');
    const isUntranslated = tip.original_lang !== lang && !isMachineTranslated;
    const primaryCat = (tip.categories || [])[0] || 'dev';
    const contentType = source.content_type || 'article';
    const contentTypeLabel = (labels.contentTypes && labels.contentTypes[contentType]) || contentType;
    const communitySourceLabel =
      tip.source_type === 'community-facebook'
        ? 'Facebook'
        : tip.source_type === 'community-telegram'
          ? 'Telegram'
          : tip.source_type === 'community-web'
            ? 'Web'
            : '';
    const isActualVi = lang === 'vi' ? tip.original_lang === 'vi' || isMachineTranslated : true;
    const slugOrId = tip.slug || tip.id;

    const article = el(
      'article',
      'tip-card group bg-[var(--bg-surface)] border border-[var(--border-color)] hover:border-[var(--border-strong)] rounded-xl p-5 transition-all duration-200 flex flex-col justify-between'
    );
    article.setAttribute('data-tip-id', tip.id);
    article.setAttribute('data-category', (tip.categories || []).join(' '));
    article.setAttribute('data-difficulty', tip.difficulty || '');
    article.setAttribute('data-lang-display', isActualVi ? 'vi' : 'en');
    article.setAttribute('data-original-lang', tip.original_lang || 'en');
    article.setAttribute('data-source', source.id || '');
    article.setAttribute('data-content-type', contentType);
    article.setAttribute('data-pub-date', tip.published_at || '');
    article.setAttribute('data-score', tip.score != null ? String(tip.score) : '0');

    const body = el('div');
    const meta = el(
      'div',
      'flex items-center gap-2 text-xs font-mono text-[var(--text-muted)] mb-2.5 flex-wrap tabular-nums'
    );

    const sourceId = source.id ? String(source.id).trim() : '';
    const favicon = el('img', 'w-4 h-4 rounded-sm shrink-0');
    favicon.setAttribute('data-fallback-src', '/favicons/default.svg');
    favicon.src = sourceId
      ? `/favicons/${encodeURIComponent(sourceId)}.png`
      : '/favicons/default.svg';
    favicon.alt = '';
    favicon.width = 16;
    favicon.height = 16;
    favicon.loading = 'lazy';
    meta.appendChild(favicon);

    meta.appendChild(el('span', 'text-[var(--text-secondary)] font-medium lowercase', source.name || ''));

    if (communitySourceLabel) {
      meta.appendChild(
        el(
          'span',
          'rounded border border-[var(--accent-border)] bg-[var(--accent-bg)] px-1.5 py-0.5 text-[10px] text-[var(--accent)]',
          `${labels.community} · ${communitySourceLabel}`
        )
      );
    }

    if (isUntranslated) {
      meta.appendChild(
        el(
          'span',
          'px-1.5 py-0.5 rounded text-[10px] font-mono font-bold border border-[var(--badge-info-border)] bg-[var(--badge-info-bg)] text-[var(--badge-info-text)]',
          labels.notTranslated
        )
      );
    }

    if (tip.alsoFrom && tip.alsoFrom.length) {
      meta.appendChild(
        el('span', 'text-[10px] text-[var(--text-muted)]', `+${tip.alsoFrom.length} ${labels.moreSources}`)
      );
    }

    const dateText = formatDate(tip.published_at, lang);
    if (dateText) {
      meta.appendChild(el('span', '', '·'));
      meta.appendChild(el('span', '', dateText));
    }

    meta.appendChild(el('span', '', '·'));
    meta.appendChild(el('span', 'lowercase text-[var(--text-muted)]', primaryCat));

    const updatedText = formatUpdated(tip.fetched_at, lang);
    if (updatedText) {
      meta.appendChild(el('span', 'text-[var(--text-muted)]', `· ${labels.updated} ${updatedText}`));
    }

    const heading = el(
      'h3',
      'text-base sm:text-lg font-bold leading-snug mb-2 text-[var(--text-primary)] group-hover:text-[var(--accent)] transition-colors'
    );
    const titleLink = el('a', 'block focus:outline-none', titleText);
    titleLink.href = `/${lang}/tip/${encodeURIComponent(slugOrId)}`;
    heading.appendChild(titleLink);

    const summary = el(
      'p',
      'text-xs sm:text-sm text-[var(--text-secondary)] leading-relaxed mb-4 line-clamp-2',
      summaryText
    );

    body.append(meta, heading, summary);

    const footer = el(
      'div',
      'pt-3 border-t border-[var(--border-subtle)] flex items-center justify-between gap-2 text-xs font-mono'
    );
    const badges = el('div', 'flex items-center gap-2 flex-wrap');

    if (tip.difficulty) {
      badges.appendChild(
        el(
          'span',
          'px-2 py-0.5 rounded text-[11px] border border-[var(--border-color)] bg-[var(--bg-muted)] text-[var(--text-secondary)]',
          (labels.difficulty && labels.difficulty[tip.difficulty]) || tip.difficulty
        )
      );
    } else {
      badges.appendChild(
        el(
          'span',
          'px-2 py-0.5 rounded text-[11px] border border-[var(--border-subtle)] bg-[var(--bg-muted)] text-[var(--text-muted)]',
          contentTypeLabel
        )
      );
    }

    if (isMachineTranslated) {
      badges.appendChild(
        el(
          'span',
          'px-2 py-0.5 rounded text-[11px] border border-[var(--border-subtle)] bg-[var(--bg-muted)] text-[var(--text-muted)]',
          labels.machineTranslated
        )
      );
    }

    if (tip.hn_points) {
      badges.appendChild(
        el(
          'span',
          'px-2 py-0.5 rounded text-[11px] border border-[var(--badge-hn-border)] bg-[var(--badge-hn-bg)] text-[var(--badge-hn-text)] tabular-nums',
          `HN: ${tip.hn_points}`
        )
      );
    }

    const rightActions = el('div', 'flex items-center gap-2 shrink-0 ml-auto');

    const saveTitle = lang === 'vi' ? 'Lưu xem sau' : 'Save for later';
    const bookmarkBtn = el(
      'button',
      'bookmark-btn p-1.5 rounded-lg border border-transparent text-[var(--text-muted)] hover:text-[var(--accent)] hover:bg-[var(--bg-muted)] transition-colors'
    );
    bookmarkBtn.type = 'button';
    bookmarkBtn.setAttribute('data-id', tip.id);
    bookmarkBtn.setAttribute('aria-pressed', 'false');
    bookmarkBtn.setAttribute('aria-label', saveTitle);
    bookmarkBtn.title = saveTitle;
    bookmarkBtn.appendChild(createBookmarkIcon());

    const readOriginal = el(
      'a',
      'text-[var(--accent)] hover:underline font-semibold inline-flex items-center gap-1'
    );
    readOriginal.href = safeExternalUrl(tip.url);
    readOriginal.target = '_blank';
    readOriginal.rel = 'noopener noreferrer';
    readOriginal.setAttribute('aria-label', `${labels.readOriginal}: ${titleText}`);
    readOriginal.append(
      el('span', 'hidden sm:inline', labels.readOriginal),
      el('span', 'sm:hidden', labels.original),
      el('span', '', '↗')
    );
    readOriginal.querySelectorAll('span').forEach((span) => span.setAttribute('aria-hidden', 'true'));

    rightActions.append(bookmarkBtn, readOriginal);
    footer.append(badges, rightActions);
    article.append(body, footer);
    return article;
  }

  window.TipCardRenderer = { create };
})();
