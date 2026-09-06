import { useSyncExternalStore } from 'react'

/**
 * A store outside the React tree, parallel to `contextStore` (issue #402):
 * a counter bumped whenever the viewing Semester is created or deleted, so
 * `Home` can refetch even while already mounted on `/`. `NewSemesterDialog`
 * and `DeleteSemesterDialog` live in the sidebar's `SemesterPanel`, a
 * different part of the tree entirely, so there is no prop path from
 * either dialog to `Home` — this store is the shared signal both sides
 * observe, deliberately explicit rather than inferred from `contextStore`'s
 * `viewing_semester` churning on every unrelated `/api/` response.
 */
let counter = 0
const listeners = new Set<() => void>()

/** Returns the current bump count, for `useSyncExternalStore`'s snapshot getter. */
export function getViewingSemesterChangeSnapshot(): number {
  return counter
}

/** Called by a lifecycle dialog on a successful create or delete. */
export function notifyViewingSemesterChanged(): void {
  counter += 1
  for (const listener of listeners) listener()
}

/** Registers `listener` to be called on every bump, for `useSyncExternalStore`'s subscribe function; returns the unsubscribe. */
export function subscribeToViewingSemesterChange(
  listener: () => void,
): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Test-only escape hatch: resets the counter between tests so one test's bump can't leak into the next. */
export function resetViewingSemesterChangeForTests(): void {
  counter = 0
  listeners.clear()
}

/** Subscribes to the signal, returning a value that changes identity each time a lifecycle dialog reports a create or delete. */
export function useViewingSemesterChangeSignal(): number {
  return useSyncExternalStore(
    subscribeToViewingSemesterChange,
    getViewingSemesterChangeSnapshot,
    () => 0,
  )
}
