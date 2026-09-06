import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

interface PageTitleContextValue {
  title: string
  setTitle: (title: string) => void
}

const PageTitleReactContext = createContext<PageTitleContextValue | null>(null)

/** Holds the current route's title, read by the phone `TopBar` (issue #328 user story 43). */
export function PageTitleProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState('')
  const value = useMemo(() => ({ title, setTitle }), [title])
  return (
    <PageTitleReactContext.Provider value={value}>
      {children}
    </PageTitleReactContext.Provider>
  )
}

/** Returns the raw context value, throwing if called outside a `PageTitleProvider`. */
function usePageTitleContext(): PageTitleContextValue {
  const context = useContext(PageTitleReactContext)
  if (context === null) {
    throw new Error('usePageTitle must be used inside a PageTitleProvider.')
  }
  return context
}

/** Read by `TopBar`: the active route's title. */
export function usePageTitleValue(): string {
  return usePageTitleContext().title
}

/**
 * Called by a route to name itself for the phone top bar — "Edit
 * schedule", a rehearsal's date, "Assignments" — so that with the sidebar
 * gone on a phone, the viewer still knows where they are.
 */
export function usePageTitle(title: string): void {
  const { setTitle } = usePageTitleContext()
  useEffect(() => {
    setTitle(title)
    return () => setTitle('')
  }, [setTitle, title])
}
