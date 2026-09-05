import type { AppContext } from './types'

/**
 * A store outside the React tree that the fetch wrapper (`apiFetch`) writes
 * to on every successful `/api/` response (issue #328). `ContextProvider`
 * subscribes to it with `useSyncExternalStore`; nothing in the shell issues
 * a context request of its own — the envelope is the only way this store
 * changes.
 */
let current: AppContext | null = null
const listeners = new Set<() => void>()

export function getContextSnapshot(): AppContext | null {
  return current
}

export function setContext(next: AppContext): void {
  current = next
  for (const listener of listeners) listener()
}

/** Test-only escape hatch: clears the store between tests so one test's context can't leak into the next. */
export function resetContextForTests(): void {
  current = null
  for (const listener of listeners) listener()
}

export function subscribeToContext(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
