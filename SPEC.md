# Tech Tips Hub — Architecture, Security & Upgrade Specification (`SPEC.md`)

## 1. System Overview & Trust Boundaries

Tech Tips Hub (`tips.hub`) is a bilingual (VI/EN) static tech tips & tech news aggregator powered by:
1. **Python ETL & QA Pipeline (`scripts/`)**: Scheduled hourly via GitHub Actions (`.github/workflows/fetch.yml`), outputting `data/index.json`, `data/cache/translations.json`, `data/history_featured.json`, and `data/health.json`.
2. **Telegram Community Webhook (`api/telegram.ts`)**: Vercel Serverless Function accepting authenticated Telegram updates, queuing submissions as GitHub Issues, and committing admin-approved items to `data/community.json`.
3. **Astro Static Site (`src/`, `public/`)**: Pre-rendered static site + per-locale/per-feed JSON APIs (`/api/tips-{vi,en}.json`, `/api/news-{vi,en}.json`, `/api/all-{vi,en}.json`) and RSS/Atom feeds deployed on Vercel.

### Trust Boundaries
- **External RSS/Atom/API feeds** → untrusted text/HTML/dates. Must be stripped of HTML/scripts, entities unescaped, dates normalized to ISO-8601 UTC, and treated as untrusted input in LLM translation prompts (`UNTRUSTED DATA RULE`).
- **Telegram Webhook (`POST /api/telegram`)** → untrusted HTTP traffic. Must verify `x-telegram-bot-api-secret-token` in constant time (`safeEqual`), reject private/local/non-HTTP(S) URLs, enforce per-user daily submission caps, verify numeric `ADMIN_IDS` for privileged actions (`/danhsach`, `/sua`, `/tag`, approval callbacks), and escape HTML/JSON fences before rendering or storing.
- **Browser Client (`public/js/*`, Astro inline scripts)** → untrusted query params, `localStorage` JSON imports, and API strings. Must render dynamic strings with `textContent` / safe DOM APIs (never raw `innerHTML` on untrusted text), enforce import size/schema caps (`<= 5MB`, version `1`), and never leak secrets.

---

## 2. Core Data Invariants

### `data/index.json` Item Schema
- Visible items (`!item.hidden`) MUST satisfy:
  - Non-empty `title[lang]` and non-empty `summary[lang]` (<= 500 chars, no HTML entities, no raw HTML tags, no boilerplate, no URL-only summary, no mixed EN/VI grammar).
  - Valid ISO-8601 UTC `published_at` (no locale-specific strings like `10/16/2026 8:42:00\u202fAM`).
  - `1 <= len(categories) <= 2`, every category ID in `config/categories.yml`.
  - If `translated[lang] === "machine"`, BOTH `title[lang]` AND `summary[lang]` must match target-language checks (`looks_vietnamese` / `looks_english`) and not be verbatim copies of a different source language.
  - Optional `key_points`: map of valid lang codes → 1..4 clean plain-text strings (<= 200 chars, no HTML).
- Hidden items (`item.hidden === true`) MUST NEVER:
  - Consume translation quota in `batch_translate_pending()` or `_translate_chinese_items()`.
  - Absorb incoming fresh articles during duplicate-title merging.
  - Count against active item archiving limits improperly.

### `data/health.json` Schema (Optional, written by `run_pipeline.py`)
```json
{
  "updated_at": "2026-11-21T00:00:00+00:00",
  "sources": {
    "<source_id>": {
      "status": "ok | degraded | paused",
      "failure_count": 0,
      "last_success": "ISO-8601 | null",
      "last_failure": "ISO-8601 | null",
      "paused_until": "ISO-8601 | null",
      "last_error": "string | null"
    }
  }
}
```

### URL & Routing Contracts
- All localized pages exist identically under `/vi/...` and `/en/...` using shared Astro page components.
- `hreflang="x-default"` MUST point to `${SITE_URL}${viEquivalentPath}` (exact Vietnamese counterpart, not hardcoded `/vi`).
- `rel="prev"` and `rel="next"` MUST be absolute URLs (`${SITE_URL}...`).
- Query parameters supported on `/vi`, `/en`, `/vi/news`, `/en/news`: `?q=`, `?cat=`, `?diff=`, `?source=`, `?type=`, `?lang=`, `?sort=`, `?page=`, synced via `history.replaceState`.
- Clicking `#tag` on tip detail routes to `/${lang}?q=<tag>` (for tips) or `/${lang}/news?q=<tag>` (for news); client search includes `tip.tags` and normalizes Vietnamese diacritics (`NFD` + `đ -> d`).
- Timestamps use deterministic timezone (`Asia/Ho_Chi_Minh` for `vi`, `UTC` for `en`) identically on SSR and CSR (`tip-card.js`).

### UI & PWA Contracts
- Preserve Tech Tips Hub Dark Terminal identity (`#0F1114`, `#171A1E`, `#FFB547`, Lexend / Be Vietnam Pro / JetBrains Mono) with optional restrained Light Mode toggle (`[data-theme="light"]`) meeting WCAG AA (`>= 4.5:1`).
- **Zero emojis in UI** (buttons, headings, badges, toasts, navigation) — use crisp inline SVGs (`1.5px`–`2px` stroke).
- **Zero AI glow / neon gradients / symmetric 3-card clichés**.
- PWA: PNG icons `192x192`, `512x512`, `apple-touch-icon.png` (180x180); Service Worker with cache-entry cap and styled bilingual `/offline.html`.
- `SearchModal` JS lives in `/js/search.js` (not duplicated inline across 900+ HTML pages).

---

## 3. Verification Gates (Iron Law)
All of the following MUST exit 0 before completion:
1. `npm run check` (`astro check` — 0 errors, 0 warnings)
2. `npm run check:telegram` (`tsc --noEmit` on `api/telegram.ts`)
3. `npx tsc --noEmit`
4. `npm run test:telegram` (including Red-Team adversarial tests)
5. `python tests/test_translate.py` + all Python unit & adversarial tests
6. `python scripts/qa.py` (0 QA violations)
7. `npm run build` (clean static build + valid XML RSS + valid sitemap)
8. Live browser end-to-end verification against `astro preview` (desktop + mobile, VI + EN, search, filters, theme toggle, saved export/import, tip detail, sources, 0 console/network errors).
