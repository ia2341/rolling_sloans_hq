import { useSyncExternalStore } from 'react'

const PHONE_QUERY = '(max-width: 640px)'

/** `useSyncExternalStore` subscribe: re-runs `callback` whenever the phone breakpoint's match state changes. */
function subscribe(callback: () => void) {
  const mediaQueryList = window.matchMedia(PHONE_QUERY)
  mediaQueryList.addEventListener('change', callback)
  return () => mediaQueryList.removeEventListener('change', callback)
}

/** `useSyncExternalStore` snapshot: whether the viewport currently matches the phone breakpoint. */
function getSnapshot() {
  return window.matchMedia(PHONE_QUERY).matches
}

/**
 * The single "is this a phone?" answer for the whole SPA (issue #328 user
 * story 39). Every responsive decision — table vs. cards, modal vs. sheet,
 * drag grip vs. up/down buttons — reads this hook rather than declaring its
 * own breakpoint, so two surfaces can never disagree about where the phone
 * viewport starts.
 */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}
