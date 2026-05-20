import path from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['smoothstudy.ai'],
    proxy: {
      '/api': { target: 'http://api:8000', rewrite: (p) => p.replace(/^\/api/, '') },
      '/vnc': { target: 'http://localhost:6080', ws: true },
    }
  },
  test: {
    passWithNoTests: true
  }
})
