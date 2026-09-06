import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

/** What one editing surface registers with the shell chrome (issue #328). */
export interface EditSession {
  /** Names the thing being edited, for the toolbar's `Editing <what>`. */
  what: string
  changeCount: number
  /**
   * Non-null while a stale-Semester (or similar) condition blocks saving —
   * the exact message a `Stale*SemesterError` carries, rendered verbatim
   * by `BlockNote`. `null` means the surface isn't blocked.
   */
  blockedReason: string | null
  discard: () => void
  /** Opens the Save popup (#334 supplies the popup itself). */
  requestSave: () => void
}

interface EditSessionContextValue {
  session: EditSession | null
  registerSession: (session: EditSession) => void
  clearSession: () => void
}

const EditSessionReactContext = createContext<EditSessionContextValue | null>(
  null,
)

/**
 * Holds at most one active `EditSession`, the seam between an editing
 * surface and the shell chrome (`EditToolbar`, the phone top bar's Save,
 * and the sidebar's Save changes button all read it). Wraps `AppShell`.
 */
export function EditSessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<EditSession | null>(null)

  const registerSession = useCallback(
    (next: EditSession) => setSession(next),
    [],
  )
  const clearSession = useCallback(() => setSession(null), [])

  const value = useMemo(
    () => ({ session, registerSession, clearSession }),
    [session, registerSession, clearSession],
  )

  return (
    <EditSessionReactContext.Provider value={value}>
      {children}
    </EditSessionReactContext.Provider>
  )
}

/** Returns the raw context value, throwing if called outside an `EditSessionProvider`. */
function useEditSessionContext(): EditSessionContextValue {
  const context = useContext(EditSessionReactContext)
  if (context === null) {
    throw new Error(
      'useEditSession/useRegisterEditSession must be used inside an EditSessionProvider.',
    )
  }
  return context
}

/** Read by the shell chrome: the active `EditSession`, or `null` on a surface with nothing to save. */
export function useEditSession(): EditSession | null {
  return useEditSessionContext().session
}

/**
 * Called by an editing surface to publish its state to the shell chrome for
 * as long as it's mounted. Registers on mount and on every change to
 * `session`'s primitive fields, and clears itself on unmount so navigating
 * away from an edit route can never leave a stale toolbar behind.
 *
 * Pass `null` when this surface has nothing to register *right now* but
 * another mounted surface might (e.g. a parent page that hands the toolbar
 * off to a nested editor for as long as that editor is mounted) — a `null`
 * call is a complete no-op, it neither registers nor clears. This matters
 * because child effects run before parent effects: a parent that always
 * registered *something* (even a disabled stub) would stomp a child's real
 * session the instant both are mounted, since the child's registration
 * (running first) would be immediately overwritten by the parent's
 * (running second) — leaving the toolbar's Discard/Save wired to the
 * parent's stub until some unrelated change made the child's effect rerun.
 *
 * `discard`/`requestSave` are read through a ref rather than listed in the
 * effect's dependencies: a caller that passes inline arrow functions (the
 * common case) gives them a new identity every render, and depending on
 * that identity would re-run the effect — which calls `registerSession`,
 * which re-renders this provider, which re-runs the effect — every render,
 * forever.
 */
export function useRegisterEditSession(session: EditSession | null): void {
  const { registerSession, clearSession } = useEditSessionContext()
  const what = session?.what ?? null
  const changeCount = session?.changeCount ?? null
  const blockedReason = session?.blockedReason ?? null

  const latestSession = useRef(session)
  useEffect(() => {
    latestSession.current = session
  })

  useEffect(() => {
    // `what`/`changeCount` are `null` exactly when `session` itself is (see
    // their derivation above) — checking them, rather than `session`
    // directly, means this effect never has to list `session` itself as a
    // dependency, which would defeat the point of reading discard/
    // requestSave through a ref instead (see the docstring above).
    if (what === null || changeCount === null) return undefined
    registerSession({
      what,
      changeCount,
      blockedReason,
      discard: () => latestSession.current?.discard(),
      requestSave: () => latestSession.current?.requestSave(),
    })
    return clearSession
  }, [registerSession, clearSession, what, changeCount, blockedReason])
}
