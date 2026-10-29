import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  site: process.env.SITE_URL || process.env.PUBLIC_SITE_URL || 'https://meocongnghe.vercel.app',
  integrations: [
    tailwind({
      applyBaseStyles: false
    })
  ]
});

