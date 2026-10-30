import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: process.env.SITE_URL || process.env.PUBLIC_SITE_URL || 'https://meocongnghe.vercel.app',
  integrations: [
    tailwind({
      applyBaseStyles: false
    }),
    sitemap({
      filter: (page) => {
        try {
          const { pathname } = new URL(page);
          // Trang chủ gốc chỉ redirect sang /vi
          if (pathname === '/') return false;
          // /page/1 trùng nội dung với trang chủ
          if (/^\/(vi|en)\/page\/1\/?$/.test(pathname)) return false;
          // URL tip dạng id 16 ký tự hex là bản trùng của URL slug
          if (/^\/(vi|en)\/tip\/[0-9a-f]{16}\/?$/.test(pathname)) return false;
          // /gui-trick trùng nội dung với /vi/submit
          if (/^\/gui-trick\/?$/.test(pathname)) return false;
          return true;
        } catch {
          return true;
        }
      }
    })
  ]
});

