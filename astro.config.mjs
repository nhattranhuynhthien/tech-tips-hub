import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  site: 'https://techtipshub.pages.dev',
  integrations: [
    tailwind({
      applyBaseStyles: false
    })
  ]
});
