// public/js/actions.js
// Quản lý Bookmark và Trạng thái đã xem qua localStorage (0đ, không cần server)

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

  function updateCardsUI() {
    const saved = getStored(SAVED_KEY);
    const read = getStored(READ_KEY);

    document.querySelectorAll('.tip-card').forEach((card) => {
      const id = card.getAttribute('data-tip-id');
      if (!id) return;

      // Update bookmark state
      const btn = card.querySelector('.bookmark-btn');
      const icon = card.querySelector('.bookmark-icon');
      if (btn && icon) {
        if (saved.includes(id)) {
          btn.classList.add('text-[#c85a17]', 'dark:text-[#e07a38]');
          btn.classList.remove('text-[var(--text-muted)]');
          icon.setAttribute('fill', 'currentColor');
        } else {
          btn.classList.remove('text-[#c85a17]', 'dark:text-[#e07a38]');
          btn.classList.add('text-[var(--text-muted)]');
          icon.setAttribute('fill', 'none');
        }
      }

      // Update read state (subtle dimming)
      if (read.includes(id)) {
        card.classList.add('opacity-85');
      }
    });
  }

  // Delegated click event
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.bookmark-btn');
    if (!btn) return;
    e.preventDefault();
    const id = btn.getAttribute('data-id');
    if (!id) return;

    let saved = getStored(SAVED_KEY);
    if (saved.includes(id)) {
      saved = saved.filter((x) => x !== id);
    } else {
      saved.push(id);
    }
    setStored(SAVED_KEY, saved);
    updateCardsUI();

    // Custom event if on saved page
    window.dispatchEvent(new CustomEvent('techtips:bookmark_changed', { detail: { id, saved } }));
  });

  // Run on page load and astro page transitions
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updateCardsUI);
  } else {
    updateCardsUI();
  }
  document.addEventListener('astro:page-load', updateCardsUI);
})();
