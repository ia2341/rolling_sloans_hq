import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

// `vite.config.ts` doesn't set `test.globals: true`, so React Testing
// Library's own automatic cleanup (which detects a global `afterEach`)
// never registers itself — every `render()` in a file would otherwise pile
// up in the same jsdom document instead of unmounting between tests.
afterEach(cleanup)

// jsdom has no layout engine, so `window.matchMedia` doesn't exist at all
// (issue #328's `useIsPhone()` needs it). Individual tests override
// `matches` by reassigning `window.matchMedia` where the phone/desktop
// distinction matters; this default keeps every other test on the
// desktop breakpoint.
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}
