// public/js/actions.js
// Quản lý Bookmark, Trạng thái đã xem, Copy Link Toast và Chế độ xem Grid / Compact List

(function () {
  const SAVED_KEY = 'techtips_saved';
  const READ_KEY = 'techtips_read';
  const VIEW_KEY = 'techtips_view_mode';

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
      <span>${message}</span>
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 2300);
  }

  // Update card bookmark and read statuses
  function updateCardsUI() {
    const saved = getStored(SAVED_KEY);
    const read = getStored(READ_KEY);

    document.querySelectorAll('.tip-card, .compact-tip-row').forEach((card) => {
      const id = card.getAttribute('data-tip-id');
      if (!id) return;

      // Update bookmark state
      const btn = card.querySelector('.bookmark-btn');
      const icon = card.querySelector('.bookmark-icon');
      if (btn && icon) {
        if (saved.includes(id)) {
          btn.classList.add('text-[var(--accent)]');
          btn.classList.remove('text-[var(--text-muted)]');
          icon.setAttribute('fill', 'currentColor');
        } else {
          btn.classList.remove('text-[var(--accent)]');
          btn.classList.add('text-[var(--text-muted)]');
          icon.setAttribute('fill', 'none');
        }
      }

      // Update read state (subtle dimming)
      if (read.includes(id)) {
        card.classList.add('opacity-80');
      }
    });
  }

  // View Mode: Grid vs Compact List
  function applyViewMode(mode) {
    const gridEl = document.getElementById('tips-grid');
    const compactEl = document.getElementById('tips-compact-list');
    const gridBtn = document.getElementById('view-grid-btn');
    const compactBtn = document.getElementById('view-compact-btn');

    if (!gridEl || !compactEl) return;

    if (mode === 'compact') {
      gridEl.classList.add('hidden');
      compactEl.classList.remove('hidden');
      if (compactBtn) {
        compactBtn.className = 'view-mode-btn p-1.5 rounded-md border border-[var(--accent)] bg-[var(--accent)] text-white shadow-sm';
      }
      if (gridBtn) {
        gridBtn.className = 'view-mode-btn p-1.5 rounded-md border border-[var(--border-color)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:text-[var(--accent)]';
      }
    } else {
      compactEl.classList.add('hidden');
      gridEl.classList.remove('hidden');
      if (gridBtn) {
        gridBtn.className = 'view-mode-btn p-1.5 rounded-md border border-[var(--accent)] bg-[var(--accent)] text-white shadow-sm';
      }
      if (compactBtn) {
        compactBtn.className = 'view-mode-btn p-1.5 rounded-md border border-[var(--border-color)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:text-[var(--accent)]';
      }
    }
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

    // 3. View mode buttons
    const gridBtn = e.target.closest('#view-grid-btn');
    if (gridBtn) {
      e.preventDefault();
      localStorage.setItem(VIEW_KEY, 'grid');
      applyViewMode('grid');
      return;
    }

    const compactBtn = e.target.closest('#view-compact-btn');
    if (compactBtn) {
      e.preventDefault();
      localStorage.setItem(VIEW_KEY, 'compact');
      applyViewMode('compact');
      return;
    }
  });

  function init() {
    updateCardsUI();
    const savedMode = localStorage.getItem(VIEW_KEY) || 'grid';
    applyViewMode(savedMode);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('astro:page-load', init);
})();
