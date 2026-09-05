/** Overrides `window.matchMedia` so `useIsPhone()` resolves to `matchesPhone` for the rest of the test. */
export function mockMatchMedia(matchesPhone: boolean): void {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: matchesPhone,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}
