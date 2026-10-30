// public/js/tip-card.js
// Renderer dùng chung cho các thẻ tip được tạo phía client.
// Giữ cấu trúc markup khớp với src/components/TipCard.astro.

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

  function formatDate(value) {
    const d = new Date(value);
    if (isNaN(d.getTime())) return '';
    return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
  }

  function formatUpdated(value, lang) {
    const d = new Date(value);
    if (isNaN(d.getTime())) return '';
    try {
      return new Intl.DateTimeFormat(lang === 'vi' ? 'vi-VN' : 'en-US', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      }).format(d);
    } catch {
      return '';
    }
  }

  function sourceDomain(tip) {
    try {
      return new URL(tip.source?.site_url || tip.url).hostname;
    } catch {
      return '';
    }
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
      'flex items-center gap-2 text-xs font-mono text-[var(--text-muted)] mb-2.5 flex-wrap'
    );

    const domain = sourceDomain(tip);
    if (domain) {
      const favicon = el('img', 'w-4 h-4 rounded-sm');
      favicon.src = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`;
      favicon.alt = '';
      favicon.width = 16;
      favicon.height = 16;
      favicon.loading = 'lazy';
      meta.appendChild(favicon);
    }

    meta.appendChild(el('span', 'text-[var(--text-secondary)] font-medium lowercase', source.name || ''));

    if (communitySourceLabel) {
      meta.appendChild(
        el(
          'span',
          'rounded border border-[var(--accent)]/30 px-1.5 py-0.5 text-[10px] text-[var(--accent)]',
          `${labels.community} · ${communitySourceLabel}`
        )
      );
    }

    if (isUntranslated) {
      meta.appendChild(
        el(
          'span',
          'px-1.5 py-0.2 rounded text-[10px] font-mono font-bold border border-blue-500/30 bg-blue-500/10 text-blue-400',
          labels.notTranslated
        )
      );
    }

    if (tip.alsoFrom && tip.alsoFrom.length) {
      meta.appendChild(
        el('span', 'text-[10px] text-[var(--text-muted)]', `+${tip.alsoFrom.length} ${labels.moreSources}`)
      );
    }

    const dateText = formatDate(tip.published_at);
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
    const titleLink = el('a', 'focus:outline-none', titleText);
    titleLink.href = `/${lang}/tip/${slugOrId}`;
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
          'px-2 py-0.5 rounded text-[11px] border border-amber-500/20 bg-amber-500/10 text-amber-400',
          `HN: ${tip.hn_points}`
        )
      );
    }

    const readOriginal = el(
      'a',
      'text-[var(--accent)] hover:underline font-semibold inline-flex items-center gap-1 shrink-0 ml-auto'
    );
    readOriginal.href = tip.url || '#';
    readOriginal.target = '_blank';
    readOriginal.rel = 'noopener noreferrer';
    readOriginal.setAttribute('aria-label', `${labels.readOriginal}: ${titleText}`);
    readOriginal.append(
      el('span', 'hidden sm:inline', labels.readOriginal),
      el('span', 'sm:hidden', labels.original),
      el('span', '', '↗')
    );
    readOriginal.querySelectorAll('span').forEach((span) => span.setAttribute('aria-hidden', 'true'));

    footer.append(badges, readOriginal);
    article.append(body, footer);
    return article;
  }

  window.TipCardRenderer = { create };
})();
