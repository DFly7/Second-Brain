import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['smoothstudy.ai'],
    proxy: {
      '/api': { target: 'http://api:8000', rewrite: (p) => p.replace(/^\/api/, '') }
    }
  },
  test: {
    passWithNoTests: true
  }
})
