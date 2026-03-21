import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // Load .env variables so the dev proxy target can be overridden without
  // touching this file.  Only VITE_* vars are exposed to the browser bundle;
  // here we read the raw env in Node context so we can use the full value.
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_BASE_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 3000,
      // Dev-only proxy: forwards /api/* to the backend so the browser never
      // has to deal with CORS during local development.
      // In production the browser talks directly to VITE_API_BASE_URL.
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
