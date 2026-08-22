import react from '@vitejs/plugin-react'
// vitest's re-export, not vite's: it is the one that knows about `test`.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    // No source maps in the shipped bundle: they would expose the full
    // frontend source on an appliance that manages a domain.
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
  test: {
    // Node, not jsdom, and that is a boundary rather than an oversight.
    // What is worth testing here is the pure logic two screens share: which
    // actions an object offers, and whether a stored width or position
    // survives being read back. Component tests would need a DOM, and in
    // jsdom getBoundingClientRect returns zeros — so every clamp and the whole
    // edge-flip calculation would end up asserting against the stand-in
    // rather than against a browser. Those are checked in a real one.
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
  server: {
    port: 5173,
    // `entrypoint.sh api` runs the backend standalone on 8000 for development.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false,
      },
    },
  },
})
