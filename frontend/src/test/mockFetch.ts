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
