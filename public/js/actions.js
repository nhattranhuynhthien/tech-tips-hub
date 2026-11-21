// public/js/actions.js
// Global UI actions: Bookmarks, Read State, Theme Toggle, Language Persistence, Favicon Fallback, Toast.

(function () {
  const SAVED_KEY = 'techtips_saved';
  const READ_KEY = 'techtips_read';
  const THEME_KEY = 'techtips_theme';
  const MAX_SAVED_ITEMS = 1000;
  const MAX_READ_ITEMS = 500;
  const MAX_ID_LENGTH = 128;

  function isEn() {
    return (document.documentElement.getAttribute('lang') || '').toLowerCase() === 'en';
  }

  function i18n() {
    return isEn()
      ? {
          savedLabel: 'Saved',
          saveLabel: 'Save for later',
          unsaveTitle: 'Remove bookmark',
          saveTitle: 'Save for later',
          unsavedToast: 'Removed from saved tips',
          savedToast: 'Saved for later',
          storageFailToast: 'Unable to update saved tips (storage unavailable or full)',
          themeLightToast: 'Switched to light mode',
          themeDarkToast: 'Switched to dark mode',
          switchToLight: 'Switch to light mode',
          switchToDark: 'Switch to dark mode',
        }
      : {
          savedLabel: 'Đã lưu',
          saveLabel: 'Lưu để xem sau',
          unsaveTitle: 'Bỏ lưu',
          saveTitle: 'Lưu xem sau',
          unsavedToast: 'Đã bỏ lưu thủ thuật',
          savedToast: 'Đã lưu vào danh sách xem sau',
          storageFailToast: 'Không thể lưu thay đổi (bộ nhớ trình duyệt bị chặn hoặc đã đầy)',
          themeLightToast: 'Đã chuyển sang giao diện sáng',
          themeDarkToast: 'Đã chuyển sang giao diện tối',
          switchToLight: 'Chuyển sang giao diện sáng',
          switchToDark: 'Chuyển sang giao diện tối',
        };
  }

  function sanitizeIdList(raw, maxItems) {
    if (!Array.isArray(raw)) return [];
    const seen = new Set();
    const result = [];
    for (const item of raw) {
      if (typeof item !== 'string') continue;
      const trimmed = item.trim();
      if (!trimmed || trimmed.length > MAX_ID_LENGTH || seen.has(trimmed)) continue;
      seen.add(trimmed);
      result.push(trimmed);
    }
    if (typeof maxItems === 'number' && result.length > maxItems) {
      return result.slice(result.length - maxItems);
    }
    return result;
  }

  function getStored(key) {
    try {
      const parsed = JSON.parse(localStorage.getItem(key));
      const limit = key === READ_KEY ? MAX_READ_ITEMS : MAX_SAVED_ITEMS;
      return sanitizeIdList(parsed, limit);
    } catch {
      return [];
    }
  }

  function setStored(key, arr) {
    try {
      const limit = key === READ_KEY ? MAX_READ_ITEMS : MAX_SAVED_ITEMS;
      const clean = sanitizeIdList(arr, limit);
      localStorage.setItem(key, JSON.stringify(clean));
      return true;
    } catch {
      return false;
    }
  }

  function markRead(id) {
    if (typeof id !== 'string') return;
    const cleanId = id.trim();
    if (!cleanId || cleanId.length > MAX_ID_LENGTH) return;
    let read = getStored(READ_KEY);
    if (!read.includes(cleanId)) {
      read.push(cleanId);
      if (read.length > MAX_READ_ITEMS) {
        read = read.slice(read.length - MAX_READ_ITEMS);
      }
      setStored(READ_KEY, read);
    }
  }

  function applyTheme(theme) {
    const isLight = theme === 'light';
    if (isLight) {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute('content', isLight ? '#F7F6F2' : '#0F1114');
    }
    syncThemeUI();
  }

  function syncThemeUI() {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    const text = i18n();
    const label = isLight ? text.switchToDark : text.switchToLight;
    document.querySelectorAll('[data-theme-toggle]').forEach((btn) => {
      btn.setAttribute('aria-pressed', String(isLight));
      btn.setAttribute('aria-label', label);
      btn.setAttribute('title', label);
    });
  }

  function showToast(message, variant) {
    const existing = document.getElementById('techtips-toast');
    if (existing) existing.remove();

    const isError = variant === 'error';
    const toast = document.createElement('div');
    toast.id = 'techtips-toast';
    toast.setAttribute('role', isError ? 'alert' : 'status');
    toast.setAttribute('aria-live', isError ? 'assertive' : 'polite');
    toast.className = `fixed bottom-20 md:bottom-6 right-4 sm:right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl border ${
      isError ? 'border-red-500/40' : 'border-[var(--border-color)]'
    } bg-[var(--bg-surface)] text-[var(--text-primary)] text-xs font-mono font-semibold shadow-xl toast-animate`;

    const svgNS = 'http://www.w3.org/2000/svg';
    const icon = document.createElementNS(svgNS, 'svg');
    icon.setAttribute('class', `w-4 h-4 ${isError ? 'text-red-500' : 'text-[var(--accent)]'} shrink-0`);
    icon.setAttribute('fill', 'none');
    icon.setAttribute('stroke', 'currentColor');
    icon.setAttribute('viewBox', '0 0 24 24');
    icon.setAttribute('aria-hidden', 'true');

    if (isError) {
      const circle = document.createElementNS(svgNS, 'circle');
      circle.setAttribute('cx', '12');
      circle.setAttribute('cy', '12');
      circle.setAttribute('r', '9');
      circle.setAttribute('stroke-width', '2');
      const path = document.createElementNS(svgNS, 'path');
      path.setAttribute('d', 'M12 8v5m0 3h.01');
      path.setAttribute('stroke-width', '2.2');
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('stroke-linejoin', 'round');
      icon.append(circle, path);
    } else {
      const path = document.createElementNS(svgNS, 'path');
      path.setAttribute('d', 'M20 6 9 17l-5-5');
      path.setAttribute('stroke-width', '2.5');
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('stroke-linejoin', 'round');
      icon.appendChild(path);
    }

    const label = document.createElement('span');
    label.textContent = String(message ?? '');
    toast.append(icon, label);
    document.body.appendChild(toast);

    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 2300);
  }

  function updateCardsUI() {
    const saved = getStored(SAVED_KEY);
    const read = getStored(READ_KEY);
    const text = i18n();

    document.querySelectorAll('.tip-card').forEach((card) => {
      const id = card.getAttribute('data-tip-id');
      if (!id) return;
      card.classList.toggle('opacity-80', read.includes(id));
    });

    document.querySelectorAll('.bookmark-btn[data-id]').forEach((btn) => {
      const id = btn.getAttribute('data-id');
      if (!id) return;
      const isSaved = saved.includes(id);
      const label = btn.querySelector('[data-bookmark-label]');
      const neutralClass = label ? 'text-[var(--text-secondary)]' : 'text-[var(--text-muted)]';
      const otherNeutralClass = label ? 'text-[var(--text-muted)]' : 'text-[var(--text-secondary)]';

      btn.classList.toggle('text-[var(--accent)]', isSaved);
      btn.classList.toggle(neutralClass, !isSaved);
      btn.classList.remove(otherNeutralClass);
      btn.classList.toggle('border-[var(--accent)]', isSaved);
      btn.setAttribute('aria-pressed', String(isSaved));

      const icon = btn.querySelector('.bookmark-icon');
      if (icon) {
        icon.setAttribute('fill', isSaved ? 'currentColor' : 'none');
        if (!label) {
          btn.classList.toggle('border-transparent', !isSaved);
          const tipTitle = isSaved ? text.unsaveTitle : text.saveTitle;
          btn.setAttribute('title', tipTitle);
          btn.setAttribute('aria-label', tipTitle);
        }
      }

      if (label) label.textContent = isSaved ? text.savedLabel : text.saveLabel;
    });
  }

  function resolveEventElement(target) {
    if (!target) return null;
    if (typeof target.closest === 'function') return target;
    if (target.parentElement && typeof target.parentElement.closest === 'function') {
      return target.parentElement;
    }
    if (target.parentNode && typeof target.parentNode.closest === 'function') {
      return target.parentNode;
    }
    return null;
  }

  // Delegated capture-phase image fallback handler (replaces inline onerror attributes)
  document.addEventListener(
    'error',
    (e) => {
      const target = e.target;
      if (target && target.tagName === 'IMG') {
        const fallback = target.getAttribute('data-fallback-src');
        if (fallback && target.getAttribute('src') !== fallback) {
          target.removeAttribute('data-fallback-src');
          target.src = fallback;
        }
      }
    },
    true
  );

  // Delegated click handling
  document.addEventListener('click', (e) => {
    const targetEl = resolveEventElement(e.target);
    if (!targetEl) return;
    const text = i18n();

    // 1. Theme toggle
    const themeBtn = targetEl.closest('[data-theme-toggle]');
    if (themeBtn) {
      e.preventDefault();
      const nextTheme = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      try {
        localStorage.setItem(THEME_KEY, nextTheme);
      } catch {}
      applyTheme(nextTheme);
      showToast(nextTheme === 'light' ? text.themeLightToast : text.themeDarkToast);
      return;
    }

    // 2. Language switcher persistence
    const langLink = targetEl.closest('[data-set-lang]');
    if (langLink) {
      const chosen = langLink.getAttribute('data-set-lang');
      if (chosen === 'vi' || chosen === 'en') {
        try {
          localStorage.setItem('techtips_lang', chosen);
        } catch {}
        try {
          document.cookie = `techtips_lang=${chosen};path=/;max-age=31536000;samesite=lax`;
        } catch {}
      }
      return;
    }

    // 3. Bookmark toggle
    const bookmarkBtn = targetEl.closest('.bookmark-btn');
    if (bookmarkBtn) {
      e.preventDefault();
      e.stopPropagation();
      const rawId = bookmarkBtn.getAttribute('data-id');
      const id = typeof rawId === 'string' ? rawId.trim() : '';
      if (!id || id.length > MAX_ID_LENGTH) return;

      let saved = getStored(SAVED_KEY);
      const wasSaved = saved.includes(id);
      if (wasSaved) {
        saved = saved.filter((x) => x !== id);
      } else {
        saved.push(id);
        if (saved.length > MAX_SAVED_ITEMS) {
          saved = saved.slice(saved.length - MAX_SAVED_ITEMS);
        }
      }

      if (!setStored(SAVED_KEY, saved)) {
        showToast(text.storageFailToast, 'error');
        return;
      }

      showToast(wasSaved ? text.unsavedToast : text.savedToast);
      updateCardsUI();
      window.dispatchEvent(new CustomEvent('techtips:bookmark_changed', { detail: { id, saved } }));
      return;
    }

    // 4. Track read state when opening a tip link inside a card
    const tipLink = targetEl.closest('.tip-card a[href]');
    if (tipLink) {
      const card = tipLink.closest('[data-tip-id]');
      const id = card && card.getAttribute('data-tip-id');
      if (id) markRead(id);
    }
  });

  async function copyText(text) {
    const value = String(text ?? '');
    if (!value) return false;
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch {}
    }
    try {
      const ta = document.createElement('textarea');
      ta.value = value;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return Boolean(ok);
    } catch {
      return false;
    }
  }

  function init() {
    syncThemeUI();
    updateCardsUI();
  }

  window.TechTipsActions = { updateCardsUI, markRead, showToast, syncThemeUI, copyText };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('astro:page-load', init);
})();
