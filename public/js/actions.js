// public/js/actions.js
// Quản lý Bookmark, trạng thái đã xem, Copy Link và Toast (song ngữ VI/EN).

(function () {
  const SAVED_KEY = 'techtips_saved';
  const READ_KEY = 'techtips_read';
  const MAX_READ_ITEMS = 500;

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
          savedToast: 'Saved for later 🔖',
          copiedToast: 'Link copied to clipboard 📋',
          copyFailToast: 'Failed to copy link',
        }
      : {
          savedLabel: 'Đã lưu',
          saveLabel: 'Lưu để xem sau',
          unsaveTitle: 'Bỏ lưu',
          saveTitle: 'Lưu xem sau',
          unsavedToast: 'Đã bỏ lưu thủ thuật',
          savedToast: 'Đã lưu vào danh sách xem sau 🔖',
          copiedToast: 'Đã sao chép liên kết vào bộ nhớ tạm 📋',
          copyFailToast: 'Sao chép liên kết thất bại',
        };
  }

  function getStored(key) {
    try {
      const parsed = JSON.parse(localStorage.getItem(key));
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function setStored(key, arr) {
    try {
      localStorage.setItem(key, JSON.stringify(arr));
    } catch {}
  }

  function markRead(id) {
    if (!id) return;
    let read = getStored(READ_KEY);
    if (!read.includes(id)) {
      read.push(id);
      if (read.length > MAX_READ_ITEMS) {
        read = read.slice(read.length - MAX_READ_ITEMS);
      }
      setStored(READ_KEY, read);
    }
  }

  // Toast notification (tránh thanh điều hướng đáy h-14 trên mobile bằng bottom-20 md:bottom-6)
  function showToast(message) {
    const existing = document.getElementById('techtips-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'techtips-toast';
    toast.className = 'fixed bottom-20 md:bottom-6 right-4 sm:right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl border border-[var(--border-color)] bg-[var(--bg-surface)] text-[var(--text-primary)] text-xs font-mono font-semibold shadow-xl toast-animate';
    toast.innerHTML = `
      <svg class="w-4 h-4 text-[var(--accent)] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path d="M20 6 9 17l-5-5" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>
      <span></span>
    `;
    const label = toast.querySelector('span');
    if (label) label.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 2300);
  }

  // Update bookmark buttons and read state everywhere on the page.
  function updateCardsUI() {
    const saved = getStored(SAVED_KEY);
    const read = getStored(READ_KEY);
    const text = i18n();

    document.querySelectorAll('.tip-card, .compact-tip-row').forEach((card) => {
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

  // Delegated click handling
  document.addEventListener('click', (e) => {
    const text = i18n();

    // 1. Bookmark toggle
    const bookmarkBtn = e.target.closest('.bookmark-btn');
    if (bookmarkBtn) {
      e.preventDefault();
      e.stopPropagation();
      const id = bookmarkBtn.getAttribute('data-id');
      if (!id) return;

      let saved = getStored(SAVED_KEY);
      if (saved.includes(id)) {
        saved = saved.filter((x) => x !== id);
        showToast(text.unsavedToast);
      } else {
        saved.push(id);
        showToast(text.savedToast);
      }
      setStored(SAVED_KEY, saved);
      updateCardsUI();
      window.dispatchEvent(new CustomEvent('techtips:bookmark_changed', { detail: { id, saved } }));
      return;
    }

    // 2. Copy Link button
    const copyBtn = e.target.closest('.copy-link-btn');
    if (copyBtn) {
      e.preventDefault();
      e.stopPropagation();
      const url = copyBtn.getAttribute('data-url');
      if (url && navigator.clipboard) {
        navigator.clipboard.writeText(url).then(() => {
          showToast(text.copiedToast);
        }).catch(() => {
          showToast(text.copyFailToast);
        });
      }
      return;
    }

    // 3. Track read state when opening a tip link inside a card
    const tipLink = e.target.closest('.tip-card a[href], .compact-tip-row a[href]');
    if (tipLink) {
      const card = tipLink.closest('[data-tip-id]');
      const id = card && card.getAttribute('data-tip-id');
      if (id) markRead(id);
    }
  });

  function init() {
    updateCardsUI();
  }

  window.TechTipsActions = { updateCardsUI, markRead };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('astro:page-load', init);
})();
