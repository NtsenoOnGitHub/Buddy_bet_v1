import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#eefbf3',
          100: '#d6f5e3',
          200: '#b0eac9',
          300: '#7dd8a9',
          400: '#47be84',
          500: '#25a267',
          600: '#178252',
          700: '#136843',
          800: '#115337',
          900: '#0f452e',
          950: '#072619',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
