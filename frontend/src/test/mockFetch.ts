import { vi } from 'vitest'

/** Stubs `window.fetch` to resolve once with `status`/`body`, for a route component test against the mocked `/api/` fetch layer (issue #330). */
export function mockFetchOnce(status: number, body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      status,
      ok: status >= 200 && status < 300,
      json: () => Promise.resolve(body),
    }),
  )
}

/** Stubs `window.fetch` with a dispatcher keyed by a substring of the request URL, for a test that needs more than one distinct response (e.g. a page's own read plus a popup's separate fetch). */
export function mockFetchByUrl(
  handlers: Record<string, () => { status: number; body: unknown }>,
): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      const key = Object.keys(handlers).find((candidate) =>
        url.includes(candidate),
      )
      if (key === undefined) {
        throw new Error(`No mock handler registered for fetch(${url})`)
      }
      const { status, body } = handlers[key]!()
      return Promise.resolve({
        status,
        ok: status >= 200 && status < 300,
        json: () => Promise.resolve(body),
      })
    }),
  )
}

/** Stubs `window.fetch` to resolve each call with the next `{status, body}` in `responses`, in order -- for a test spanning more than one distinct round trip to the same URL (e.g. an initial load, then a write). */
export function stubFetchSequence(
  responses: Array<{ status: number; body: unknown }>,
): ReturnType<typeof vi.fn> {
  const fetchSpy = vi.fn()
  for (const { status, body } of responses) {
    fetchSpy.mockResolvedValueOnce({
      status,
      ok: status >= 200 && status < 300,
      json: () => Promise.resolve(body),
    })
  }
  vi.stubGlobal('fetch', fetchSpy)
  return fetchSpy
}
