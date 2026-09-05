import { PageHead } from '../components/ui/PageHead'
import { usePageTitle } from '../shell/PageTitleContext'

/** Renders for any client route the router doesn't recognize (issue #325 user story 3, #328 user story 44).
 *
 * The Django catch-all always returns the shell with a 200, so the SPA —
 * not the server — decides whether a path is real. Rendered inside
 * `AppShell` like any other route, so nav stays reachable from a 404.
 */
export function NotFound() {
  usePageTitle('Page not found')
  return <PageHead title="Page not found" />
}
