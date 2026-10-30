// public/js/actions.js
// Quản lý Bookmark, trạng thái đã xem, Copy Link và Toast.

(function () {
  const SAVED_KEY = 'techtips_saved';
  const READ_KEY = 'techtips_read';

  function getStored(key) {
    try {
      return JSON.parse(localStorage.getItem(key)) || [];
    } catch {
      return [];
    }
  }

  function setStored(key, arr) {
    try {
      localStorage.setItem(key, JSON.stringify(arr));
    } catch {}
  }

  // Toast notification
  function showToast(message) {
    const existing = document.getElementById('techtips-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'techtips-toast';
    toast.className = 'fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl border border-[var(--border-color)] bg-[var(--bg-surface)] text-[var(--text-primary)] text-xs font-mono font-semibold shadow-xl toast-animate';
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

    document.querySelectorAll('.tip-card, .compact-tip-row').forEach((card) => {
      const id = card.getAttribute('data-tip-id');
      if (!id) return;
      if (read.includes(id)) card.classList.add('opacity-80');
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
      if (icon) icon.setAttribute('fill', isSaved ? 'currentColor' : 'none');

      if (label) label.textContent = isSaved ? 'Đã lưu' : 'Lưu để xem sau';
    });
  }

  // Delegated click handling
  document.addEventListener('click', (e) => {
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
        showToast('Đã bỏ lưu thủ thuật');
      } else {
        saved.push(id);
        showToast('Đã lưu vào danh sách xem sau 🔖');
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
      if (url) {
        navigator.clipboard.writeText(url).then(() => {
          showToast('Đã sao chép liên kết vào bộ nhớ tạm 📋');
        }).catch(() => {
          showToast('Sao chép liên kết thất bại');
        });
      }
      return;
    }
  });

  function init() {
    updateCardsUI();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('astro:page-load', init);
})();
