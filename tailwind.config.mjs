/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        paper: {
          50: '#fdfbf7',
          100: '#f7f3ec',
          200: '#ede6db',
          300: '#ded3c3',
          400: '#c5b59e',
          500: '#9e8c74',
          800: '#2c251f',
          900: '#1c1713',
          950: '#120f0d',
        },
        ink: {
          50: '#f6f7f9',
          100: '#eceef2',
          200: '#d5dae2',
          300: '#b0bccb',
          400: '#8396ae',
          500: '#627794',
          700: '#3c4b60',
          800: '#232b38',
          900: '#161b23',
          950: '#0d1117',
        },
        terracotta: {
          50: '#fdf6f0',
          100: '#faebde',
          200: '#f4d3bc',
          300: '#ebb591',
          400: '#df8e60',
          500: '#c85a17', // Primary accent
          600: '#b0490f',
          700: '#8e370e',
          800: '#732e12',
          900: '#5e2712',
        }
      },
      fontFamily: {
        sans: ['"Be Vietnam Pro"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        display: ['"Lexend"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'kbd': '0 2px 0 var(--kbd-shadow)',
        'craft': '0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.03)',
        'craft-hover': '0 4px 12px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.04)',
      }
    },
  },
  plugins: [],
}

