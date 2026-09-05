/** Renders for any client route the router doesn't recognize (issue #325 user story 3).
 *
 * The Django catch-all always returns the shell with a 200, so the SPA —
 * not the server — decides whether a path is real.
 */
export function NotFound() {
  return <p>Page not found</p>
}
