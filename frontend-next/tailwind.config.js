/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg:      'rgb(var(--bg) / <alpha-value>)',
        surface: 'rgb(var(--surface) / <alpha-value>)',
        sunken:  'rgb(var(--sunken) / <alpha-value>)',
        border:  'rgb(var(--border) / <alpha-value>)',
        text:    'rgb(var(--text) / <alpha-value>)',
        muted:   'rgb(var(--muted) / <alpha-value>)',
        accent:  'rgb(var(--accent) / <alpha-value>)',
      },
      fontFamily: {
        sans:   ['Inter', 'ui-sans-serif', 'system-ui', '"PingFang SC"', '"Noto Sans SC"', 'sans-serif'],
        serif:  ['"Source Serif 4"', '"Source Han Serif SC"', '"Noto Serif SC"', 'Georgia', 'serif'],
        mono:   ['"JetBrains Mono"', 'ui-monospace', 'Menlo', 'monospace'],
      },
      fontSize: {
        prose: ['18px', { lineHeight: '1.85' }],
      },
      borderRadius: {
        DEFAULT: '6px',
      },
      boxShadow: {
        soft: '0 1px 2px rgb(0 0 0 / 0.06), 0 4px 16px rgb(0 0 0 / 0.08)',
      },
    },
  },
  plugins: [],
};
