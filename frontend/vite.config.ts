/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Matches Django's STATIC_URL. Vite prepends this to every asset reference
// it emits internally (dynamic imports, CSS `url()`), so the built chunks
// resolve through the same prefix WhiteNoise serves in production and the
// Django dev server serves locally (issue #325).
const STATIC_URL = '/static/'

export default defineConfig({
  base: STATIC_URL,
  // Tailwind's own Vite plugin (issue #328) — no postcss.config.js, since
  // Tailwind v4 no longer needs one for this setup.
  plugins: [react(), tailwindcss()],
  build: {
    // A separate STATICFILES_DIRS entry from the vendored static/ tree
    // (issue #325) — the two coexist until issue #341 deletes the old one.
    outDir: 'dist',
    // Written at the build root rather than Vite's default `.vite/`
    // sub-directory: collectstatic's default ignore patterns drop
    // dotfiles, which would silently leave the manifest out of
    // STATIC_ROOT in production.
    manifest: 'manifest.json',
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
